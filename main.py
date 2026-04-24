"""
Carvana SUV Tracker — entry point.

Usage:
    python main.py                   # Run once immediately
    python main.py --once            # Explicit single run (same as no args)
    python main.py --schedule        # Run now, then repeat every CHECK_INTERVAL_HOURS
    python main.py --dry-run         # Scrape and analyse but do not save or email
    python main.py --no-llm          # Skip LLM analysis (rules only)
    python main.py --backend ollama  # Force Ollama, no fallback
    python main.py --backend api     # Force Anthropic API, no Ollama
    python main.py --email           # Force email send this run
    python main.py --history         # Print run history from DB and exit
    python main.py --check-setup     # Validate config, test backends, exit
"""

import argparse
import io
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

# Ensure Unicode output works on Windows consoles (cp1252 -> utf-8)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import config
from profiles import SearchProfile, load_profiles, resolve_reference_doc, resolve_reference_doc_for_make
from utils.logging_config import setup_logging, start_run_log, end_run_log
from scraper.urls import build_search_url
from scraper.browser import Browser
from scraper.extractor import extract_listings, fetch_listing_drivetrain
from analysis.rules import apply_filters, enrich_listings
from utils.vin_decode import enrich_drivetrain
from analysis.llm import LLMAnalyzer, LLMResult
from storage.csv_writer import write_results
from storage import history_db
from storage.trends import build_trend_charts_html
from notifications.email_alert import build_email_html, send_summary, should_send
from analysis.validator import validate_llm_result, validate_email_html, build_warning_banner

log = logging.getLogger(__name__)


# ── Main run cycle ────────────────────────────────────────────────────────────

def run_once(
    profiles:       list[SearchProfile],
    skip_llm:       bool = False,
    force_backend:  str | None = None,
    dry_run:        bool = False,
    force_email:    bool = False,
    no_email:       bool = False,
    preview_output: str | None = None,
) -> list[dict]:
    """Run all profiles in sequence. Returns combined enriched listings from all profiles."""
    all_enriched: list[dict] = []

    _warm_up_ollama()

    for profile in profiles:
        log.info("=" * 60)
        log.info("STARTING PROFILE: %s (%s)", profile.profile_id, profile.label)
        log.info("=" * 60)
        result = _run_profile(
            profile,
            skip_llm=skip_llm,
            force_backend=force_backend,
            dry_run=dry_run,
            force_email=force_email,
            no_email=no_email,
            preview_output=preview_output,
        )
        all_enriched.extend(result)

    return all_enriched


def _run_profile(
    profile:        SearchProfile,
    skip_llm:       bool = False,
    force_backend:  str | None = None,
    dry_run:        bool = False,
    force_email:    bool = False,
    no_email:       bool = False,
    preview_output: str | None = None,
) -> list[dict]:
    """Execute one full search-and-save cycle for a single profile."""
    start_time = time.monotonic()
    run_id     = str(uuid.uuid4())
    run_at     = datetime.now(timezone.utc).isoformat()
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

    run_log_handler = start_run_log(config.OUTPUT_DIR, run_id, timestamp)
    _log_run_header(run_id, run_at, dry_run, profile)

    try:
        # ── Phase 1: Scrape ───────────────────────────────────────────────────
        log.info("--- PHASE 1: SCRAPING ---")
        fuel_filters = profile.fuel_type_filters or [None]
        log.info("Fuel type searches: %s", ", ".join(f or "all" for f in fuel_filters))
        all_raw, vehicle_stats, scrape_browser = _scrape(run_id, profile)
        _log_scrape_summary(vehicle_stats, all_raw)

        # scrape_browser must be closed regardless of what happens next
        try:
            # ── Phase 2: Deduplicate ──────────────────────────────────────────
            log.info("--- PHASE 2: DEDUPLICATION ---")
            deduped = _deduplicate(all_raw)

            # ── Phase 3: Filter ───────────────────────────────────────────────
            log.info("--- PHASE 3: FILTERING ---")
            filtered = apply_filters(
                deduped,
                max_price=profile.max_price,
                max_mileage=profile.max_mileage,
                min_year=profile.min_year,
                max_year=profile.max_year,
                excluded_trim_keywords=profile.excluded_trim_keywords,
                excluded_years=profile.excluded_years,
            )
            if not filtered:
                log.warning("No listings passed filters — profile complete with no output.")
                return []

            # ── Phase 4: Enrich + score ───────────────────────────────────────
            log.info("--- PHASE 4: ENRICHMENT & SCORING ---")
            has_hybrid_interest = any(f == "Hybrid" for f in (profile.fuel_type_filters or []))
            enriched = enrich_listings(
                filtered,
                max_year=profile.max_year,
                max_mileage=profile.max_mileage,
                min_year=profile.min_year,
                model_preference=profile.model_preference,
                hybrid_bonus=has_hybrid_interest,
                down_payment=profile.down_payment,
            )
            _pref = profile.model_preference
            _n    = len(_pref)
            enriched.sort(key=lambda x: (
                _pref.index(x["model"]) if x.get("model") in _pref else _n,
                -(x.get("value_score") or 0),
            ))
            _log_enrichment_summary(enriched)

            # ── Phase 4.5: Drivetrain lookup via NHTSA VIN decode ────────────
            log.info("--- PHASE 4.5: DRIVETRAIN LOOKUP ---")
            enrich_drivetrain(enriched)

            # ── Phase 4.6: Override drivetrain for table rows from listing pages
            # NHTSA misclassifies some hybrid AWD systems as 4WD. Scraping the
            # individual Carvana listing page for the ~5-20 table-visible listings
            # gets Carvana's own label, which is accurate and consistent with what
            # the reader sees when they click through.
            # The main scrape browser is reused (same trusted session) so Carvana's
            # bot detection does not flag the requests.
            log.info("--- PHASE 4.6: LISTING PAGE DRIVETRAIN SCRAPE ---")
            _scrape_listing_drivetrains(
                enriched,
                num_vehicles=len(profile.vehicles),
                browser=scrape_browser,
            )
        finally:
            scrape_browser.close()

        # ── Phase 5: LLM analysis (per-make, isolated reference docs) ────────
        log.info("--- PHASE 5: LLM ANALYSIS ---")
        llm_result = _run_llm(
            profile, enriched, skip_llm, force_backend,
            max_price=profile.max_price,
            has_hybrid_interest=has_hybrid_interest,
            show_financing=profile.show_financing,
            down_payment=profile.down_payment,
        )
        _log_llm_summary(llm_result)

        # ── Phase 5.5: Validate LLM output ───────────────────────────────────
        log.info("--- PHASE 5.5: VALIDATION ---")
        if llm_result.analysis and not skip_llm:
            from analysis.anthropic_client import AnthropicClient
            _validator_client = AnthropicClient(
                api_key=config.ANTHROPIC_API_KEY,
                model=config.ANTHROPIC_MODEL,
                max_tokens=2000,
            )
            _makes = list({make for make, _ in profile.vehicles})
            _llm_validation = validate_llm_result(
                llm_result.analysis, _makes, _validator_client,
            )
            if not _llm_validation.passed:
                log.warning(
                    "LLM analysis failed validation — %d issue(s)",
                    len(_llm_validation.issues),
                )
                if _llm_validation.corrected_text:
                    log.info("Replacing analysis with auto-corrected version")
                    llm_result = LLMResult(
                        analysis=_llm_validation.corrected_text,
                        backend_used=llm_result.backend_used,
                        model_used=llm_result.model_used,
                        tokens_used=llm_result.tokens_used,
                        latency_ms=llm_result.latency_ms,
                        error=llm_result.error,
                        cache_hit=llm_result.cache_hit,
                        top_pick_vins=llm_result.top_pick_vins,
                    )
                else:
                    log.warning("Auto-correction unavailable — proceeding with original analysis")
        else:
            log.debug("Validation skipped (no analysis or LLM disabled)")

        if dry_run or preview_output:
            _print_summary(enriched)
            _print_llm_result(llm_result)
            if preview_output:
                _write_preview_html(enriched, llm_result, profile, preview_output)
            log.info("Dry run complete — no data saved.")
            return enriched

        # ── Phase 6: Save ─────────────────────────────────────────────────────
        log.info("--- PHASE 6: SAVING ---")
        history_db.init_db()
        current_vins = {str(r["vin"]) for r in enriched if r.get("vin")}
        new_vins     = history_db.get_new_listings(current_vins, profile.profile_id)
        price_drops  = history_db.get_price_drops(enriched)

        _mark_alert_flags(enriched, new_vins, price_drops, profile.max_price)

        csv_path = write_results(enriched, run_id, llm_backend=llm_result.backend_used)
        log.debug("CSV written: %s", csv_path)

        duration = time.monotonic() - start_time
        history_db.save_run(history_db.RunRecord(
            run_id=run_id,
            run_at=run_at,
            listings_found=len(all_raw),
            listings_saved=len(enriched),
            llm_backend=llm_result.backend_used,
            llm_model=llm_result.model_used,
            duration_seconds=round(duration, 2),
        ))
        history_db.save_listings(enriched, run_id, profile.profile_id)
        history_db.save_model_stats(enriched, run_id)
        history_db.save_profile_llm_analysis(profile.profile_id, run_id, run_at, llm_result)
        log.info("Saved %d listings to DB (run_id=%s, profile=%s)",
                 len(enriched), run_id, profile.profile_id)

        # ── Phase 7: Alerts ───────────────────────────────────────────────────
        log.info("--- PHASE 7: ALERTS & NOTIFICATIONS ---")
        _log_alert_summary(new_vins, price_drops)

        _print_summary(enriched)
        _print_llm_result(llm_result)

        trends = history_db.get_model_price_trends(days=180, vehicles=profile.vehicles)
        log.info("Price trend data: %d models, up to 180 days", len(trends))

        if no_email:
            log.info("Email skipped (--no-email)")
        elif force_email or (config.SEND_EMAIL and _should_send_for_profile(
                profile, enriched, new_vins, price_drops)):
            # Build HTML up front so we can validate it before sending
            email_html = build_email_html(
                enriched, llm_result, price_drops,
                trends=trends, new_vins=new_vins,
                profile_label=profile.label,
                show_financing=profile.show_financing,
                down_payment=profile.down_payment,
                num_vehicles=len(profile.vehicles),
            )
            _makes = list({make for make, _ in profile.vehicles})
            _html_validation = validate_email_html(email_html, _makes)
            if not _html_validation.passed:
                log.warning(
                    "Email HTML validation: %d issue(s) — injecting warning banner",
                    len(_html_validation.issues),
                )
                banner = build_warning_banner(_html_validation.issues)
                # Inject banner after the opening <h2> header
                insert_at = email_html.find("<h2 ")
                if insert_at != -1:
                    insert_at = email_html.find(">", insert_at) + 1
                    email_html = email_html[:insert_at] + "\n" + banner + email_html[insert_at:]
                else:
                    email_html = banner + email_html

            sent = send_summary(
                enriched, llm_result, price_drops,
                trends=trends, csv_path=csv_path, force=force_email,
                new_vins=new_vins,
                email_to=profile.email_to,
                profile_label=profile.label,
                show_financing=profile.show_financing,
                down_payment=profile.down_payment,
                num_vehicles=len(profile.vehicles),
                pre_built_html=email_html,
            )
            log.info("Email dispatch: %s", "sent" if sent else "failed")
        else:
            log.info("Email skipped (no alert conditions met or SEND_EMAIL=False)")

        total_duration = time.monotonic() - start_time
        _log_run_footer(run_id, enriched, llm_result, new_vins, price_drops, total_duration, csv_path)

        return enriched

    finally:
        end_run_log(run_log_handler)


# ── Preview helper ────────────────────────────────────────────────────────────

def _write_preview_html(
    enriched:    list[dict],
    llm_result:  LLMResult,
    profile:     SearchProfile,
    output_path: str,
) -> None:
    """Build email HTML with empty alert signals and write it to output_path.

    Called when --preview-output is passed.  No history DB is queried because
    this is a dry run — new_vins, price_drops, and trends are left empty so the
    HTML still renders correctly (it just won't show alert badges).
    """
    email_html = build_email_html(
        enriched, llm_result, [],
        trends={}, new_vins=set(),
        profile_label=profile.label,
        show_financing=profile.show_financing,
        down_payment=profile.down_payment,
        num_vehicles=len(profile.vehicles),
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(email_html)
    log.info("Email preview written to: %s", output_path)


# ── Scraping ──────────────────────────────────────────────────────────────────

def _scrape(run_id: str, profile: SearchProfile) -> tuple[list[dict], list[dict], Browser]:
    """Scrape all vehicles for a profile across all configured fuel types.
    Returns (all_listings, per_vehicle_stats, browser).

    The browser is returned still open so Phase 4.6 can reuse the established
    Carvana session for individual listing page loads. The caller MUST close it.
    """
    all_raw: list[dict] = []
    vehicle_stats: list[dict] = []

    fuel_types = profile.fuel_type_filters or [None]

    browser = Browser()
    browser.start()

    for make, model in profile.vehicles:
        min_year, max_year = profile.min_year, profile.max_year
        vehicle_total = 0
        pages_scraped = 0
        strategy_used = "none"
        t0 = time.monotonic()

        for fuel_type in fuel_types:
            browser.reset_context()
            label = fuel_type or "all"
            log.info("Scraping %s %s [%s]...", make, model, label)

            for page in range(1, config.MAX_PAGES_PER_SEARCH + 1):
                url = build_search_url(make, model, min_year, max_year, page, fuel_type=fuel_type)
                log.debug("URL: %s", url)

                html = browser.get_page_content(url)
                if not html:
                    log.warning("No HTML returned for %s %s [%s] page %d", make, model, label, page)
                    break

                listings = extract_listings(html, make, model)

                if listings:
                    strategy_used = listings[0].get("extraction_strategy", "unknown")
                    pages_scraped = max(pages_scraped, page)

                if not listings:
                    log.info("No listings on page %d for %s %s [%s] — stopping", page, make, model, label)
                    break

                all_raw.extend(listings)
                vehicle_total += len(listings)
                log.debug("%s %s [%s] page %d: %d listings", make, model, label, page, len(listings))

                if len(listings) < 20:
                    break

        elapsed = time.monotonic() - t0
        vehicle_stats.append({
            "make": make, "model": model,
            "listings": vehicle_total,
            "pages": pages_scraped,
            "strategy": strategy_used,
            "elapsed_s": round(elapsed, 1),
        })

    return all_raw, vehicle_stats, browser


def _scrape_listing_drivetrains(
    enriched: list[dict],
    num_vehicles: int,
    browser: Browser,
) -> None:
    """
    Load individual Carvana listing pages for the top table-row candidates and
    update their drivetrain field with Carvana's own label.

    Uses the same per-model cap as the email table (5 for multi-vehicle profiles,
    15 for single-vehicle) so every listing the reader sees gets an accurate value.
    NHTSA data on non-table listings is unaffected.

    Accepts the already-open scrape browser so Carvana's bot detection does not
    flag the requests — the session is already trusted from Phase 1 scraping.
    """
    table_limit = 5 if num_vehicles > 1 else 15

    # Mirror the email table's fill logic: top-N per (make, model) in score order
    seen_counts: dict[tuple[str, str], int] = {}
    table_candidates: list[dict] = []
    for r in enriched:
        key = (r.get("make") or "", r.get("model") or "")
        if seen_counts.get(key, 0) < table_limit:
            table_candidates.append(r)
            seen_counts[key] = seen_counts.get(key, 0) + 1

    to_scrape = [r for r in table_candidates if r.get("url")]
    if not to_scrape:
        log.debug("No listing URLs available — skipping listing page drivetrain scrape")
        return

    log.info("Scraping Carvana listing pages for drivetrain: %d listing(s)", len(to_scrape))
    updated = 0

    # Reset context once so we share session state but start a clean page
    browser.reset_context()

    for r in to_scrape:
        url = r.get("url", "")
        drivetrain = fetch_listing_drivetrain(url, browser)
        if drivetrain:
            old = r.get("drivetrain")
            if old != drivetrain:
                log.info(
                    "Drivetrain updated — %s %s %s %s: %s → %s",
                    r.get("year"), r.get("make"), r.get("model"),
                    (r.get("trim") or "")[:24], old or "None", drivetrain,
                )
            r["drivetrain"] = drivetrain
            updated += 1
        else:
            log.debug(
                "No drivetrain found on listing page: %s %s %s",
                r.get("year"), r.get("make"), r.get("model"),
            )

    log.info(
        "Listing page drivetrain scrape complete: %d/%d resolved",
        updated, len(to_scrape),
    )


def _deduplicate(all_raw: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped = []
    dupes = 0
    for listing in all_raw:
        vin = listing.get("vin") or ""
        if vin and vin in seen:
            dupes += 1
            continue
        seen.add(vin)
        deduped.append(listing)
    if dupes:
        log.info("Removed %d duplicate VINs — %d unique listings remain", dupes, len(deduped))
    else:
        log.info("No duplicates found — %d listings", len(deduped))
    return deduped


# ── LLM ──────────────────────────────────────────────────────────────────────

def _warm_up_ollama() -> None:
    """
    Select the best available Ollama server and warm it up before any profile
    runs to ensure a model is loaded into memory.

    When multiple servers are configured (OLLAMA_NETWORK_HOSTS), they are
    probed in parallel and the fastest/best-provisioned one is chosen.
    config.OLLAMA_NETWORK_BASE_URL is updated in-place so the rest of the
    run uses the selected server.
    """
    if not config.OLLAMA_ENABLED:
        return

    from analysis.ollama_client import OllamaClient, select_best_server

    hosts = config.OLLAMA_NETWORK_HOSTS
    if not hosts:
        log.debug("No Ollama hosts configured — skipping warm-up")
        return

    if len(hosts) > 1:
        best = select_best_server(hosts, config.OLLAMA_PREFERRED_MODELS)
        if not best:
            log.warning("No Ollama servers reachable — will fall back to Anthropic API")
            config.OLLAMA_NETWORK_BASE_URL = ""
            return
        config.OLLAMA_NETWORK_BASE_URL = best
    elif not config.OLLAMA_NETWORK_BASE_URL:
        return

    client = OllamaClient(
        base_url=config.OLLAMA_NETWORK_BASE_URL,
        timeout=config.OLLAMA_TIMEOUT,
    )
    client.warm_up(config.OLLAMA_PREFERRED_MODELS)


def _run_llm(
    profile: SearchProfile,
    listings: list[dict],
    skip_llm: bool,
    force_backend: str | None,
    max_price: int = 0,
    has_hybrid_interest: bool = False,
    show_financing: bool = True,
    down_payment: int | None = None,
) -> LLMResult:
    """
    Run LLM analysis with isolated per-make reference docs to prevent brand
    terminology bleed between makes.  One LLM call is made per distinct make
    in `listings`; results are merged into a single LLMResult.
    """
    if skip_llm:
        log.info("LLM analysis skipped (--no-llm)")
        return LLMResult(analysis=None, backend_used="none", model_used="",
                         tokens_used=None, latency_ms=0, error="skipped via --no-llm")

    original_nvidia    = config.NVIDIA_ENABLED
    original_ollama    = config.OLLAMA_ENABLED
    original_anthropic = config.ANTHROPIC_ENABLED
    original_cerebras  = config.CEREBRAS_ENABLED
    if force_backend == "nvidia":
        config.CEREBRAS_ENABLED  = False
        config.ANTHROPIC_ENABLED = False
        config.OLLAMA_ENABLED    = False
        config.NVIDIA_ENABLED    = True
        log.info("Backend forced to NVIDIA NIM only")
    elif force_backend == "ollama":
        config.NVIDIA_ENABLED    = False
        config.ANTHROPIC_ENABLED = False
        config.CEREBRAS_ENABLED  = False
        log.info("Backend forced to Ollama only")
    elif force_backend == "api":
        config.NVIDIA_ENABLED   = False
        config.OLLAMA_ENABLED   = False
        config.CEREBRAS_ENABLED = False
        log.info("Backend forced to Anthropic API only")
    elif force_backend == "cerebras":
        config.NVIDIA_ENABLED    = False
        config.OLLAMA_ENABLED    = False
        config.ANTHROPIC_ENABLED = False
        config.CEREBRAS_ENABLED  = True
        log.info("Backend forced to Cerebras only")

    try:
        # One shared analyzer — Ollama/Anthropic clients are reused across makes
        analyzer = LLMAnalyzer(
            max_price=max_price,
            has_hybrid_interest=has_hybrid_interest,
            show_financing=show_financing,
            down_payment=down_payment,
        )

        # Preserve the existing sort order while collecting distinct makes
        makes: list[str] = list(dict.fromkeys(
            r.get("make", "") for r in listings if r.get("make")
        ))

        # For multi-model profiles, cap each make at top 5 listings for the LLM
        # so that every vehicle the LLM recommends is guaranteed to appear in
        # the email table (which also shows top 5 per model).
        llm_cap = 5 if len(makes) > 1 else 30

        per_make_results: list[tuple[str, LLMResult]] = []
        for make in makes:
            make_listings = [r for r in listings if r.get("make", "").lower() == make.lower()]
            llm_make_listings = make_listings[:llm_cap]
            ref_doc = resolve_reference_doc_for_make(profile, make)
            log.info(
                "LLM analysis — %s: %d listings (capped at %d for LLM), %d-char ref doc",
                make, len(make_listings), len(llm_make_listings), len(ref_doc),
            )
            result = analyzer.analyze(llm_make_listings, reference_doc=ref_doc)
            per_make_results.append((make, result))

        # Cross-model synthesis: one final call that sees all makes together
        if len(makes) > 1:
            successful = [
                (make, result.analysis)
                for make, result in per_make_results
                if result.analysis
            ]
            if successful:
                # Build a top-5-per-(make, model) slice for synthesis — mirrors
                # the email table cap so LLM picks are always present in the table.
                _seen: dict[tuple, int] = {}
                top_for_synthesis: list[dict] = []
                for r in listings:
                    key = (r.get("make", ""), r.get("model", ""))
                    if _seen.get(key, 0) < 5:
                        top_for_synthesis.append(r)
                        _seen[key] = _seen.get(key, 0) + 1

                log.info(
                    "Running cross-model synthesis across %d makes (%d listings)",
                    len(successful), len(top_for_synthesis),
                )
                synthesis_prompt = analyzer.build_synthesis_prompt(top_for_synthesis, successful)
                synthesis_result = analyzer.analyze(
                    top_for_synthesis, reference_doc="", _prompt_override=synthesis_prompt
                )
                per_make_results.append(("_synthesis", synthesis_result))

        return _merge_llm_results(per_make_results)
    finally:
        config.NVIDIA_ENABLED    = original_nvidia
        config.OLLAMA_ENABLED    = original_ollama
        config.ANTHROPIC_ENABLED = original_anthropic
        config.CEREBRAS_ENABLED  = original_cerebras


def _merge_llm_results(per_make_results: list[tuple[str, LLMResult]]) -> LLMResult:
    """
    Combine per-make LLMResults into one.

    - Single make: return its result unchanged (no section headers added).
    - Multiple makes: prefix each analysis block with a ### Make header and
      concatenate.  top_pick_vins is the ordered union of all makes' picks.
    """
    if not per_make_results:
        return LLMResult(
            analysis=None, backend_used="none", model_used="",
            tokens_used=None, latency_ms=0, error="no makes in results",
        )

    if len(per_make_results) == 1:
        return per_make_results[0][1]

    analysis_sections: list[str] = []
    synthesis_result: LLMResult | None = None
    per_make_vins: list[str] = []
    total_latency = 0
    total_tokens = 0
    last_backend = "none"
    last_model = ""
    any_cache_hit: bool | None = None
    errors: list[str] = []

    for make, result in per_make_results:
        total_latency += result.latency_ms
        if result.tokens_used:
            total_tokens += result.tokens_used
        if result.backend_used != "none":
            last_backend = result.backend_used
            last_model   = result.model_used
        if result.cache_hit is True:
            any_cache_hit = True
        elif result.cache_hit is False and any_cache_hit is None:
            any_cache_hit = False
        if result.error:
            errors.append(f"{make}: {result.error}")

        if make == "_synthesis":
            synthesis_result = result
        else:
            if result.analysis:
                analysis_sections.append(f"### {make}\n\n{result.analysis}")
            if result.top_pick_vins:
                per_make_vins.extend(result.top_pick_vins)

    # For multi-make searches, only show the synthesis section in the email —
    # per-make sections are used internally but not surfaced to the reader.
    if synthesis_result and synthesis_result.analysis:
        final_analysis = synthesis_result.analysis
    else:
        # Synthesis failed or wasn't run; fall back to concatenated per-make sections
        final_analysis = "\n\n".join(analysis_sections) if analysis_sections else None

    # Synthesis picks are cross-model winners; use them first if available
    if synthesis_result and synthesis_result.top_pick_vins:
        final_vins = synthesis_result.top_pick_vins
    else:
        final_vins = per_make_vins

    return LLMResult(
        analysis=final_analysis,
        backend_used=last_backend,
        model_used=last_model,
        tokens_used=total_tokens or None,
        latency_ms=total_latency,
        error="; ".join(errors) if errors else None,
        cache_hit=any_cache_hit,
        top_pick_vins=final_vins,
    )


# ── Email send decision ───────────────────────────────────────────────────────

def _should_send_for_profile(
    profile: SearchProfile,
    enriched: list[dict],
    new_vins: set[str],
    price_drops: list[dict],
) -> bool:
    """
    Decide whether to send an email for this profile run.

    If email_only_on_new_or_drops is True, only send when there are new vehicles
    (never seen before) or price drops — ignoring the normal value/price conditions.
    Otherwise, delegate to the standard should_send() logic.
    """
    if profile.email_only_on_new_or_drops:
        has_new   = bool(new_vins)
        has_drops = bool(price_drops)
        if has_new or has_drops:
            log.info(
                "email_only_on_new_or_drops: sending (new=%d, drops=%d)",
                len(new_vins), len(price_drops),
            )
            return True
        log.info("email_only_on_new_or_drops: skipping (no new listings or price drops)")
        return False
    return should_send(enriched, new_vins, price_drops, max_price=profile.max_price)


# ── Alert flag helper ─────────────────────────────────────────────────────────

def _mark_alert_flags(
    enriched: list[dict],
    new_vins: set[str],
    price_drops: list[dict],
    max_price: int = 0,
) -> None:
    """Stamp is_alert and price_drop_pct onto each listing dict for CSV output."""
    drop_by_vin = {d["vin"]: d["drop_pct"] for d in price_drops if d.get("vin")}
    for listing in enriched:
        vin   = listing.get("vin") or ""
        price = listing.get("price") or 999999
        score = listing.get("value_score") or 0
        listing["is_alert"] = int(
            (max_price is not None and max_price > 0 and price < max_price)
            or (vin in new_vins and score > 70)
            or vin in drop_by_vin
        )
        listing["price_drop_pct"] = drop_by_vin.get(vin, "")


# ── Structured log helpers ────────────────────────────────────────────────────

def _log_run_header(run_id: str, run_at: str, dry_run: bool, profile: SearchProfile) -> None:
    log.info("  Profile: %s (%s)", profile.profile_id, profile.label)
    log.info("  Time:    %s", datetime.now().strftime("%b %d %Y %I:%M %p"))
    log.info("  Run ID:  %s", run_id)
    log.info("  Dry run: %s", dry_run)
    log.debug("  Vehicles: %s", profile.vehicles)
    max_price_str = f"${profile.max_price:,}" if profile.max_price is not None else "none"
    log.debug("  Filters: max_price=%s, max_mileage=%d, years=%d-%d",
              max_price_str, profile.max_mileage, profile.min_year, profile.max_year)
    log.debug("  Ollama: enabled=%s host=%s, Anthropic: enabled=%s model=%s",
              config.OLLAMA_ENABLED, config.OLLAMA_NETWORK_HOST,
              config.ANTHROPIC_ENABLED, config.ANTHROPIC_MODEL)


def _log_scrape_summary(vehicle_stats: list[dict], all_raw: list[dict]) -> None:
    log.info("Scrape complete — %d total raw listings across %d vehicles:",
             len(all_raw), len(vehicle_stats))
    for s in vehicle_stats:
        log.info("  %-8s %-10s | %2d listings | %d page(s) | strategy=%-10s | %.1fs",
                 s["make"], s["model"], s["listings"], s["pages"], s["strategy"], s["elapsed_s"])


def _log_enrichment_summary(enriched: list[dict]) -> None:
    if not enriched:
        return
    scores   = [r.get("value_score") or 0 for r in enriched]
    hybrids  = sum(1 for r in enriched if r.get("is_hybrid"))
    prices   = [r.get("price") or 0 for r in enriched]
    by_make  = {}
    for r in enriched:
        by_make[r.get("make", "?")] = by_make.get(r.get("make", "?"), 0) + 1

    log.info("Enrichment summary:")
    log.info("  Listings:  %d", len(enriched))
    log.info("  Hybrids:   %d", hybrids)
    log.info("  Score:     min=%.0f  avg=%.0f  max=%.0f",
             min(scores), sum(scores) / len(scores), max(scores))
    avg_price = sum(prices) / len(prices)
    log.info("  Price:     min=$%s  avg=$%s  max=$%s",
             f"{min(prices):,.0f}", f"{avg_price:,.0f}", f"{max(prices):,.0f}")
    log.info("  By make:   %s", "  ".join(f"{k}={v}" for k, v in sorted(by_make.items())))
    log.debug("  Top 5 by score:")
    for r in enriched[:5]:
        log.debug("    [%d] %s %s %s %s — $%s | %s mi | score=%.0f",
                  enriched.index(r) + 1,
                  r.get("year"), r.get("make"), r.get("model"), r.get("trim", ""),
                  f"{r.get('price') or 0:,.0f}", r.get("mileage") or "N/A", r.get("value_score") or 0)


def _log_llm_summary(result: LLMResult) -> None:
    log.info("LLM result:")
    log.info("  Backend:  %s", result.backend_used)
    log.info("  Model:    %s", result.model_used or "N/A")
    log.info("  Latency:  %dms", result.latency_ms)
    if result.tokens_used:
        log.info("  Tokens:   %d", result.tokens_used)
    if result.cache_hit is not None:
        log.info("  Cache hit: %s", result.cache_hit)
    if result.error:
        log.info("  Error:    %s", result.error)
    if result.analysis:
        log.debug("LLM analysis output (%d chars):\n%s", len(result.analysis), result.analysis)


def _log_alert_summary(new_vins: set[str], price_drops: list[dict]) -> None:
    log.info("New listings:  %d", len(new_vins))
    log.info("Price drops:   %d", len(price_drops))
    for drop in price_drops:
        log.info("  Price drop: %s %s %s — $%s -> $%s (%.1f%%)",
                 drop.get("year"), drop.get("make"), drop.get("model"),
                 f"{drop.get('prev_price') or 0:,.0f}", f"{drop.get('price') or 0:,.0f}",
                 drop.get("drop_pct"))


def _log_run_footer(
    run_id: str,
    enriched: list[dict],
    llm_result: LLMResult,
    new_vins: set[str],
    price_drops: list[dict],
    duration: float,
    csv_path,
) -> None:
    log.info("=" * 60)
    log.info("RUN COMPLETE")
    log.info("  Run ID:        %s", run_id)
    log.info("  Duration:      %.1fs", duration)
    log.info("  Listings saved: %d", len(enriched))
    log.info("  New listings:  %d", len(new_vins))
    log.info("  Price drops:   %d", len(price_drops))
    log.info("  LLM backend:   %s (%s)", llm_result.backend_used, llm_result.model_used or "N/A")
    log.info("  CSV:           %s", csv_path)
    log.info("=" * 60)


# ── --check-setup ─────────────────────────────────────────────────────────────

def check_setup() -> None:
    """CLI-facing setup check: delegates to setup_checks.run_setup_checks() and
    pretty-prints the structured results for console output."""
    print("\n=== Autospy — Setup Check ===\n")

    from dashboard.backend.setup_checks import run_setup_checks
    results = run_setup_checks()

    # ── Profiles ──────────────────────────────────────────────────────────────
    prof = results.get("profiles", {})
    if prof.get("status") == "ok":
        # Re-load profiles here so we can print per-profile details in the CLI.
        try:
            profiles = load_profiles("profiles.yaml")
            print(f"  Profiles:      {len(profiles)} loaded")
            for p in profiles:
                print(f"    [{p.profile_id}] {p.label} — "
                      f"{len(p.vehicles)} vehicle(s), "
                      f"{'$' + f'{p.max_price:,}' if p.max_price is not None else 'no'} max, "
                      f"{len(p.email_to)} recipient(s)")
        except Exception as exc:
            print(f"  [!!] profiles.yaml error: {exc}")
    else:
        print(f"  [!!] profiles.yaml error: {prof.get('detail', 'unknown error')}")
    print(f"  Output dir:    {config.OUTPUT_DIR}")
    print()

    # ── Ollama ────────────────────────────────────────────────────────────────
    oll = results.get("ollama", {})
    status = oll.get("status")
    if status == "ok":
        print(f"  [OK] Ollama: reachable at {oll['host']}, loaded model: {oll['loaded_model']}")
    elif status == "warning":
        print(f"  [--] Ollama: reachable at {oll['host']} but no model loaded (will fall back to Anthropic)")
    elif status == "error":
        print(f"  [--] Ollama: NOT reachable at {oll['host']}")
    else:
        print("  [--] Ollama: OLLAMA_NETWORK_HOST not set in .env")

    # ── Anthropic ─────────────────────────────────────────────────────────────
    ant = results.get("anthropic", {})
    status = ant.get("status")
    if status == "ok":
        print(f"  [OK] Anthropic API: key valid, model '{ant['model']}' reachable")
    elif status == "error":
        print(f"  [!!] Anthropic API: key present but request failed -- {ant.get('detail', '')}")
    else:
        print("  [--] Anthropic API: key not set (ANTHROPIC_API_KEY in .env)")

    # ── Gmail ─────────────────────────────────────────────────────────────────
    gml = results.get("gmail", {})
    if gml.get("status") == "ok":
        print(f"  [OK] Gmail API: configured (sender: {gml['sender']})")
    else:
        print("  [--] Gmail API: not configured (run  python setup_gmail_oauth.py)")

    if config.SEND_EMAIL:
        if gml.get("status") == "ok":
            print("  [OK] Email: enabled (recipients set per-profile in profiles.yaml)")
        else:
            print("  [!!] Email: SEND_EMAIL=True but Gmail OAuth not configured")
    else:
        print("  [--] Email: disabled (SEND_EMAIL=False)")

    print()


# ── --history ─────────────────────────────────────────────────────────────────

def print_history() -> None:
    history_db.init_db()
    runs  = history_db.get_history_summary()
    stats = history_db.get_all_time_stats()

    if not runs:
        print("No run history found.")
        return

    tabulate = None
    try:
        from tabulate import tabulate
        use_tabulate = True
    except ImportError:
        use_tabulate = False

    # ── Section 1: Run log ────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  RUN HISTORY")
    print("=" * 62)
    run_rows = [
        [
            r["run_at"][:19].replace("T", " "),
            r["listings_saved"],
            r["llm_backend"] or "-",
            (r["llm_model"] or "-")[:28],
            f"{r['duration_seconds']:.0f}s",
        ]
        for r in runs
    ]
    if use_tabulate and tabulate is not None:
        print(tabulate(
            run_rows,
            headers=["Run At (UTC)", "Listings", "LLM Backend", "Model", "Duration"],
            tablefmt="rounded_outline",
        ))
    else:
        for row in run_rows:
            print("  " + " | ".join(str(c) for c in row))

    # ── Section 2: Per-model latest prices ────────────────────────────────────
    print("\n" + "=" * 62)
    print("  LATEST PRICES BY MODEL  (from most recent run per model)")
    print("=" * 62)
    model_rows = [
        [
            f"{r['make']} {r['model']}",
            f"${r['avg_price']:,.0f}",
            f"${r['min_price']:,.0f}",
            r["count"],
            r["run_at"][:10],
        ]
        for r in stats["model_latest"]
    ]
    if use_tabulate and tabulate is not None:
        print(tabulate(
            model_rows,
            headers=["Model", "Avg Price", "Best Price", "# Listings", "As Of"],
            tablefmt="rounded_outline",
        ))
    else:
        for row in model_rows:
            print("  " + " | ".join(str(c) for c in row))

    # ── Section 3: All-time summary ───────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  ALL-TIME SUMMARY")
    print("=" * 62)
    print(f"  Total runs tracked : {stats['total_runs']}")
    print(f"  Unique VINs seen   : {stats['total_unique_vins']}")
    if stats["cheapest"]:
        c = stats["cheapest"]
        print(
            f"  Cheapest ever      : ${c['price']:,.0f} — "
            f"{c['year']} {c['make']} {c['model']} {c['trim'] or ''} "
            f"(seen {c['run_at'][:10]})"
        )
    print()


# ── Output helpers ────────────────────────────────────────────────────────────

def _print_summary(listings: list[dict]) -> None:
    tabulate = None
    try:
        from tabulate import tabulate
    except ImportError:
        for r in listings:
            print(
                f"  {r.get('year')} {r.get('make')} {r.get('model')} {r.get('trim','')} | "
                f"${r.get('price',0):,.0f} | {r.get('mileage') or 'N/A'} mi | "
                f"score={r.get('value_score')}"
            )
        return

    rows = []
    for r in listings:
        rows.append([
            f"{r.get('year','')} {r.get('make','')} {r.get('model','')}",
            (r.get("trim") or "")[:22],
            f"${r.get('price',0):,.0f}",
            f"{r.get('mileage'):,}" if r.get("mileage") else "N/A",
            f"${r.get('monthly_carvana') or r.get('monthly_estimated') or 0:,.0f}/mo",
            "Y" if r.get("is_hybrid") else "",
            f"{r.get('value_score', 0):.0f}",
        ])

    assert tabulate is not None
    headers = ["Vehicle", "Trim", "Price", "Mileage", "Est. Payment", "Hybrid", "Score"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="rounded_outline"))
    print(
        f"\n  {len(listings)} listings | "
        f"Down: ${config.DOWN_PAYMENT:,} | "
        f"{config.INTEREST_RATE}% APR | "
        f"{config.LOAN_TERM_MONTHS}mo\n"
    )


def _print_llm_result(result: LLMResult) -> None:
    print(f"  LLM backend: {result.backend_used}")
    if result.model_used:
        print(f"  Model:       {result.model_used}")
    if result.latency_ms:
        print(f"  Latency:     {result.latency_ms}ms")
    if result.error:
        print(f"  Note:        {result.error}")
    if result.analysis:
        print("\n" + "=" * 60)
        print("  AI ANALYSIS")
        print("=" * 60)
        print(result.analysis)
        print("=" * 60 + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Carvana SUV Tracker")
    parser.add_argument("--once",        action="store_true", help="Run once (default)")
    parser.add_argument("--schedule",    action="store_true", help="Run on a repeating schedule")
    parser.add_argument("--dry-run",     action="store_true", help="Scrape and analyse but do not save or email")
    parser.add_argument("--no-llm",      action="store_true", help="Skip LLM analysis")
    parser.add_argument("--backend",     choices=["nvidia", "ollama", "api", "cerebras"], help="Force a specific LLM backend")
    parser.add_argument("--email",       action="store_true", help="Force email send this run")
    parser.add_argument("--no-email",    action="store_true", help="Suppress email this run even if SEND_EMAIL=True")
    parser.add_argument("--history",     action="store_true", help="Print run history and exit")
    parser.add_argument("--check-setup",    action="store_true", help="Validate config and test backends")
    parser.add_argument("--debug",          action="store_true", help="Show DEBUG messages on console")
    parser.add_argument("--backfill-stats", action="store_true", help="Recompute price trend stats from existing DB listings and exit")
    parser.add_argument(
        "--profile", nargs="+", metavar="PROFILE_ID",
        help="Run only the specified profile IDs (default: all profiles)",
    )
    parser.add_argument(
        "--preview-output", metavar="PATH",
        help="Write the generated email HTML to PATH instead of sending (implies --dry-run behaviour: no save, no send)",
    )
    args = parser.parse_args()

    setup_logging(config.LOG_FILE, console_debug=args.debug)

    if args.check_setup:
        check_setup()
        return

    if args.backfill_stats:
        history_db.init_db()
        filled = history_db.backfill_model_stats()
        if filled:
            log.info("Backfilled model price stats for %d run/model combinations", filled)
        else:
            log.info("Nothing to backfill — all runs already have stats")
        return

    if args.history:
        print_history()
        return

    try:
        profiles = load_profiles("profiles.yaml")
    except (FileNotFoundError, ValueError) as exc:
        log.error("Failed to load profiles: %s", exc)
        sys.exit(1)

    if args.profile:
        profiles = [p for p in profiles if p.profile_id in args.profile]
        if not profiles:
            log.error("No matching profiles for: %s", args.profile)
            sys.exit(1)

    kwargs = dict(
        profiles=profiles,
        skip_llm=args.no_llm,
        force_backend=args.backend,
        dry_run=args.dry_run,
        force_email=args.email,
        no_email=args.no_email,
        preview_output=args.preview_output,
    )

    if args.schedule:
        try:
            import schedule as sched  # type: ignore[import-untyped]
        except ImportError:
            log.error("Install schedule: pip install schedule")
            return

        interval = config.CHECK_INTERVAL_HOURS
        log.info("Scheduled mode: running every %d hours. Press Ctrl+C to stop.", interval)

        run_once(**kwargs)
        sched.every(interval).hours.do(run_once, **kwargs)

        heartbeat_counter = 0
        try:
            while True:
                sched.run_pending()
                time.sleep(60)
                heartbeat_counter += 1
                if heartbeat_counter >= 30:
                    log.info("Heartbeat — tracker is running, next run in ~%s", sched.next_run())
                    heartbeat_counter = 0
        except KeyboardInterrupt:
            log.info("Shutting down.")
            sys.exit(0)
    else:
        run_once(**kwargs)


if __name__ == "__main__":
    main()
