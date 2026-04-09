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
from utils.logging_config import setup_logging, start_run_log, end_run_log
from scraper.urls import build_search_url
from scraper.browser import Browser
from scraper.extractor import extract_listings
from analysis.rules import apply_filters, enrich_listings
from analysis.llm import LLMAnalyzer, LLMResult
from storage.csv_writer import write_results
from storage import history_db
from storage.trends import build_trend_charts_html
from notifications.email_alert import send_summary, should_send

log = logging.getLogger(__name__)


# ── Main run cycle ────────────────────────────────────────────────────────────

def run_once(
    skip_llm:      bool = False,
    force_backend: str | None = None,
    dry_run:       bool = False,
    force_email:   bool = False,
    no_email:      bool = False,
) -> list[dict]:
    """Execute one full search-and-save cycle. Returns enriched listings."""
    start_time = time.monotonic()
    run_id     = str(uuid.uuid4())
    run_at     = datetime.now(timezone.utc).isoformat()
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Per-run log file (captures everything at DEBUG level)
    run_log_handler = start_run_log(config.OUTPUT_DIR, run_id, timestamp)

    _log_run_header(run_id, run_at, dry_run)

    try:
        # ── Phase 1: Scrape ───────────────────────────────────────────────────
        log.info("--- PHASE 1: SCRAPING ---")
        all_raw, vehicle_stats = _scrape(run_id)

        _log_scrape_summary(vehicle_stats, all_raw)

        # ── Phase 2: Deduplicate ──────────────────────────────────────────────
        log.info("--- PHASE 2: DEDUPLICATION ---")
        deduped = _deduplicate(all_raw)

        # ── Phase 3: Filter ───────────────────────────────────────────────────
        log.info("--- PHASE 3: FILTERING ---")
        filtered = apply_filters(deduped)
        if not filtered:
            log.warning("No listings passed filters — run complete with no output.")
            return []

        # ── Phase 4: Enrich + score ───────────────────────────────────────────
        log.info("--- PHASE 4: ENRICHMENT & SCORING ---")
        enriched = enrich_listings(filtered)
        enriched.sort(key=lambda x: x.get("value_score") or 0, reverse=True)
        _log_enrichment_summary(enriched)

        # ── Phase 5: LLM analysis ─────────────────────────────────────────────
        log.info("--- PHASE 5: LLM ANALYSIS ---")
        llm_result = _run_llm(enriched, skip_llm, force_backend)
        _log_llm_summary(llm_result)

        if dry_run:
            _print_summary(enriched)
            _print_llm_result(llm_result)
            log.info("Dry run complete — no data saved.")
            return enriched

        # ── Phase 6: Save ─────────────────────────────────────────────────────
        log.info("--- PHASE 6: SAVING ---")
        csv_path = write_results(enriched, run_id, llm_backend=llm_result.backend_used)
        log.debug("CSV written: %s", csv_path)

        history_db.init_db()
        current_vins = {r.get("vin") for r in enriched if r.get("vin")}
        new_vins     = history_db.get_new_listings(current_vins)

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
        history_db.save_listings(enriched, run_id)
        history_db.save_model_stats(enriched, run_id)
        log.info("Saved %d listings to DB (run_id=%s)", len(enriched), run_id)

        # ── Phase 7: Alerts ───────────────────────────────────────────────────
        log.info("--- PHASE 7: ALERTS & NOTIFICATIONS ---")
        price_drops = history_db.get_price_drops(enriched)
        _log_alert_summary(new_vins, price_drops)

        # ── Output ────────────────────────────────────────────────────────────
        _print_summary(enriched)
        _print_llm_result(llm_result)

        trends = history_db.get_model_price_trends(days=60)
        log.info("Price trend data: %d models, up to 60 days", len(trends))

        if no_email:
            log.info("Email skipped (--no-email)")
        elif force_email or (config.SEND_EMAIL and should_send(enriched, new_vins, price_drops)):
            sent = send_summary(enriched, llm_result, new_vins, price_drops,
                                trends=trends, force=force_email)
            log.info("Email dispatch: %s", "sent" if sent else "failed")
        else:
            log.info("Email skipped (no alert conditions met or SEND_EMAIL=False)")

        # ── Run summary ───────────────────────────────────────────────────────
        total_duration = time.monotonic() - start_time
        _log_run_footer(run_id, enriched, llm_result, new_vins, price_drops, total_duration, csv_path)

        return enriched

    finally:
        end_run_log(run_log_handler)


# ── Scraping ──────────────────────────────────────────────────────────────────

def _scrape(run_id: str) -> tuple[list[dict], list[dict]]:
    """Scrape all vehicles. Returns (all_listings, per_vehicle_stats)."""
    all_raw: list[dict] = []
    vehicle_stats: list[dict] = []

    with Browser() as browser:
        for make, model, min_year, max_year in config.VEHICLES:
            browser.reset_context()
            vehicle_total = 0
            pages_scraped = 0
            strategy_used = "none"
            t0 = time.monotonic()

            for page in range(1, config.MAX_PAGES_PER_SEARCH + 1):
                url = build_search_url(make, model, min_year, max_year, page)
                log.info("Scraping %s %s (page %d)...", make, model, page)
                log.debug("URL: %s", url)

                html = browser.get_page_content(url)
                if not html:
                    log.warning("No HTML returned for %s %s page %d", make, model, page)
                    break

                listings = extract_listings(html, make, model)

                if listings:
                    strategy_used = listings[0].get("extraction_strategy", "unknown")
                    pages_scraped = page

                if not listings:
                    log.info("No listings on page %d for %s %s — stopping pagination", page, make, model)
                    break

                all_raw.extend(listings)
                vehicle_total += len(listings)
                log.debug("%s %s page %d: %d listings", make, model, page, len(listings))

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

    return all_raw, vehicle_stats


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

def _run_llm(
    listings: list[dict],
    skip_llm: bool,
    force_backend: str | None,
) -> LLMResult:
    if skip_llm:
        log.info("LLM analysis skipped (--no-llm)")
        return LLMResult(analysis=None, backend_used="none", model_used="",
                         tokens_used=None, latency_ms=0, error="skipped via --no-llm")

    original_ollama    = config.OLLAMA_ENABLED
    original_anthropic = config.ANTHROPIC_ENABLED
    if force_backend == "ollama":
        config.ANTHROPIC_ENABLED = False
        log.info("Backend forced to Ollama only")
    elif force_backend == "api":
        config.OLLAMA_ENABLED = False
        log.info("Backend forced to Anthropic API only")

    try:
        analyzer = LLMAnalyzer()
        prompt   = analyzer.build_prompt(listings)
        log.debug("LLM prompt length: %d characters, ~%d tokens", len(prompt), len(prompt) // 4)
        result = analyzer.analyze(listings)
    finally:
        config.OLLAMA_ENABLED    = original_ollama
        config.ANTHROPIC_ENABLED = original_anthropic

    return result


# ── Structured log helpers ────────────────────────────────────────────────────

def _log_run_header(run_id: str, run_at: str, dry_run: bool) -> None:
    log.info("=" * 60)
    log.info("CARVANA TRACKER RUN STARTED")
    log.info("  Time:    %s", datetime.now().strftime("%b %d %Y %I:%M %p"))
    log.info("  Run ID:  %s", run_id)
    log.info("  Dry run: %s", dry_run)
    log.debug("  Vehicles: %s", [(m, mo) for m, mo, *_ in config.VEHICLES])
    log.debug("  Filters: max_price=$%d, max_mileage=%d, years=%d-%d",
              config.MAX_PRICE, config.MAX_MILEAGE, config.MIN_YEAR, config.MAX_YEAR)
    log.debug("  Ollama: %s (%s), Anthropic: %s (%s)",
              config.OLLAMA_ENABLED, config.OLLAMA_MODEL,
              config.ANTHROPIC_ENABLED, config.ANTHROPIC_MODEL)
    log.info("=" * 60)


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
    log.info("  Price:     min=$%,.0f  avg=$%,.0f  max=$%,.0f",
             min(prices), sum(prices) / len(prices), max(prices))
    log.info("  By make:   %s", "  ".join(f"{k}={v}" for k, v in sorted(by_make.items())))
    log.debug("  Top 5 by score:")
    for r in enriched[:5]:
        log.debug("    [%d] %s %s %s %s — $%,.0f | %s mi | score=%.0f",
                  enriched.index(r) + 1,
                  r.get("year"), r.get("make"), r.get("model"), r.get("trim", ""),
                  r.get("price") or 0, r.get("mileage") or "N/A", r.get("value_score") or 0)


def _log_llm_summary(result: LLMResult) -> None:
    log.info("LLM result:")
    log.info("  Backend:  %s", result.backend_used)
    log.info("  Model:    %s", result.model_used or "N/A")
    log.info("  Latency:  %dms", result.latency_ms)
    if result.tokens_used:
        log.info("  Tokens:   %d", result.tokens_used)
    if result.error:
        log.info("  Error:    %s", result.error)
    if result.analysis:
        log.debug("LLM analysis output (%d chars):\n%s", len(result.analysis), result.analysis)


def _log_alert_summary(new_vins: set[str], price_drops: list[dict]) -> None:
    log.info("New listings:  %d", len(new_vins))
    log.info("Price drops:   %d", len(price_drops))
    for drop in price_drops:
        log.info("  Price drop: %s %s %s — $%,.0f -> $%,.0f (%.1f%%)",
                 drop.get("year"), drop.get("make"), drop.get("model"),
                 drop.get("prev_price"), drop.get("price"), drop.get("drop_pct"))


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
    print("\n=== Carvana Tracker — Setup Check ===\n")

    print(f"  Vehicles:      {len(config.VEHICLES)} configured")
    print(f"  Max price:     ${config.MAX_PRICE:,}")
    print(f"  Max mileage:   {config.MAX_MILEAGE:,} mi")
    print(f"  Year range:    {config.MIN_YEAR}-{config.MAX_YEAR}")
    print(f"  Output dir:    {config.OUTPUT_DIR}")
    print()

    from analysis.ollama_client import OllamaClient
    ollama = OllamaClient(config.OLLAMA_BASE_URL, config.OLLAMA_MODEL, timeout=5)
    if ollama.is_available():
        print(f"  [OK] Ollama: reachable, model '{config.OLLAMA_MODEL}' found")
    else:
        print(f"  [--] Ollama: NOT available at {config.OLLAMA_BASE_URL} (model: {config.OLLAMA_MODEL})")

    from analysis.anthropic_client import AnthropicClient, AnthropicUnavailableError
    anthropic = AnthropicClient(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL, max_tokens=10)
    if not anthropic.is_configured():
        print("  [--] Anthropic API: key not set (ANTHROPIC_API_KEY in .env)")
    else:
        try:
            anthropic.analyze("Reply with only the word OK.")
            print(f"  [OK] Anthropic API: key valid, model '{config.ANTHROPIC_MODEL}' reachable")
        except AnthropicUnavailableError as exc:
            print(f"  [!!] Anthropic API: key present but request failed -- {exc}")

    if config.MAILJET_API_KEY and config.MAILJET_SECRET_KEY:
        print(f"  [OK] Mailjet: API key configured")
    else:
        print("  [--] Mailjet: not configured (MAILJET_API_KEY / MAILJET_SECRET_KEY in .env)")

    if config.SEND_EMAIL:
        if config.EMAIL_FROM and config.EMAIL_TO and config.MAILJET_API_KEY:
            print(f"  [OK] Email: enabled, {len(config.EMAIL_TO)} recipient(s)")
        else:
            print("  [!!] Email: SEND_EMAIL=True but configuration incomplete")
    else:
        to_list = ", ".join(config.EMAIL_TO) if config.EMAIL_TO else "none"
        print(f"  [--] Email: disabled (SEND_EMAIL=False) — recipients: {to_list}")

    print()


# ── --history ─────────────────────────────────────────────────────────────────

def print_history() -> None:
    history_db.init_db()
    runs = history_db.get_history_summary()
    if not runs:
        print("No run history found.")
        return

    try:
        from tabulate import tabulate
        rows = [
            [
                r["run_at"][:19],
                r["listings_saved"],
                r["llm_backend"],
                r["llm_model"] or "-",
                f"{r['duration_seconds']:.1f}s",
            ]
            for r in runs
        ]
        print("\n" + tabulate(
            rows,
            headers=["Run At (UTC)", "Listings", "LLM Backend", "Model", "Duration"],
            tablefmt="rounded_outline",
        ))
    except ImportError:
        for r in runs:
            print(f"  {r['run_at'][:19]} | {r['listings_saved']} listings | {r['llm_backend']}")
    print()


# ── Output helpers ────────────────────────────────────────────────────────────

def _print_summary(listings: list[dict]) -> None:
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
            f"${r.get('monthly_estimated',0):,.0f}/mo",
            f"${r.get('shipping'):,.0f}" if r.get("shipping") else "N/A",
            "Y" if r.get("is_hybrid") else "",
            f"{r.get('value_score', 0):.0f}",
        ])

    headers = ["Vehicle", "Trim", "Price", "Mileage", "Est. Payment", "Shipping", "Hybrid", "Score"]
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
    parser.add_argument("--backend",     choices=["ollama", "api"], help="Force a specific LLM backend")
    parser.add_argument("--email",       action="store_true", help="Force email send this run")
    parser.add_argument("--no-email",    action="store_true", help="Suppress email this run even if SEND_EMAIL=True")
    parser.add_argument("--history",     action="store_true", help="Print run history and exit")
    parser.add_argument("--check-setup", action="store_true", help="Validate config and test backends")
    args = parser.parse_args()

    setup_logging(config.LOG_FILE)

    if args.check_setup:
        check_setup()
        return

    if args.history:
        print_history()
        return

    kwargs = dict(
        skip_llm=args.no_llm,
        force_backend=args.backend,
        dry_run=args.dry_run,
        force_email=args.email,
        no_email=args.no_email,
    )

    if args.schedule:
        try:
            import schedule as sched
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
