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
from utils.logging_config import setup_logging
from scraper.urls import build_search_url
from scraper.browser import Browser
from scraper.extractor import extract_listings
from analysis.rules import apply_filters, enrich_listings
from analysis.llm import LLMAnalyzer, LLMResult
from storage.csv_writer import write_results
from storage import history_db
from notifications.email_alert import send_summary, should_send

log = logging.getLogger(__name__)


# ── Main run cycle ────────────────────────────────────────────────────────────

def run_once(
    skip_llm:      bool = False,
    force_backend: str | None = None,
    dry_run:       bool = False,
    force_email:   bool = False,
) -> list[dict]:
    """Execute one full search-and-save cycle. Returns enriched listings."""
    start_time = time.monotonic()
    run_id     = str(uuid.uuid4())
    run_at     = datetime.now(timezone.utc).isoformat()

    log.info("=" * 60)
    log.info("Carvana Tracker run started — %s", datetime.now().strftime("%b %d %Y %I:%M %p"))
    log.info("Run ID: %s", run_id)
    if dry_run:
        log.info("DRY RUN — nothing will be saved or emailed")
    log.info("=" * 60)

    # ── 1-4. Scrape, dedup, filter, enrich ───────────────────────────────────
    enriched = _scrape_filter_enrich()
    if not enriched:
        return []

    # ── 5. LLM analysis ───────────────────────────────────────────────────────
    llm_result = _run_llm(enriched, skip_llm, force_backend)

    if dry_run:
        _print_summary(enriched)
        _print_llm_result(llm_result)
        log.info("Dry run complete — no data saved.")
        return enriched

    # ── 6. Save to CSV ────────────────────────────────────────────────────────
    write_results(enriched, run_id, llm_backend=llm_result.backend_used)

    # ── 7. Save to DB ─────────────────────────────────────────────────────────
    history_db.init_db()

    # Detect new VINs before saving this run's listings
    current_vins = {r.get("vin") for r in enriched if r.get("vin")}
    new_vins     = history_db.get_new_listings(current_vins)

    duration = time.monotonic() - start_time
    history_db.save_run(history_db.RunRecord(
        run_id=run_id,
        run_at=run_at,
        listings_found=len(enriched),
        listings_saved=len(enriched),
        llm_backend=llm_result.backend_used,
        llm_model=llm_result.model_used,
        duration_seconds=round(duration, 2),
    ))
    history_db.save_listings(enriched, run_id)

    # ── 8. Price drops + new listing detection ────────────────────────────────
    price_drops = history_db.get_price_drops(enriched)

    if new_vins:
        log.info("%d new listing(s) detected this run", len(new_vins))
    if price_drops:
        log.info("%d price drop(s) detected (>=5%%):", len(price_drops))
        for drop in price_drops:
            log.info(
                "  %s %s %s -- $%,.0f -> $%,.0f (%.1f%% drop)",
                drop.get("year"), drop.get("make"), drop.get("model"),
                drop.get("prev_price"), drop.get("price"), drop.get("drop_pct"),
            )

    # ── 9. Print summary + LLM output ────────────────────────────────────────
    _print_summary(enriched)
    _print_llm_result(llm_result)

    # ── 10. Email ─────────────────────────────────────────────────────────────
    if force_email or (config.SEND_EMAIL and should_send(enriched, new_vins, price_drops)):
        send_summary(enriched, llm_result, new_vins, price_drops, force=force_email)

    log.info(
        "Run complete in %.1fs — %d listings | LLM backend: %s",
        time.monotonic() - start_time, len(enriched), llm_result.backend_used,
    )
    return enriched


def _scrape_filter_enrich() -> list[dict]:
    all_raw: list[dict] = []
    with Browser() as browser:
        for make, model, min_year, max_year in config.VEHICLES:
            browser.reset_context()
            for page in range(1, config.MAX_PAGES_PER_SEARCH + 1):
                url = build_search_url(make, model, min_year, max_year, page)
                log.info("Scraping %s %s (page %d)...", make, model, page)
                html = browser.get_page_content(url)
                if not html:
                    log.warning("No HTML for %s %s page %d — stopping", make, model, page)
                    break
                listings = extract_listings(html, make, model)
                if not listings:
                    log.info("No listings on page %d for %s %s — stopping pagination", page, make, model)
                    break
                all_raw.extend(listings)
                if len(listings) < 20:
                    break

    log.info("Total raw listings scraped: %d", len(all_raw))

    seen: set[str] = set()
    deduped = []
    for listing in all_raw:
        vin = listing.get("vin") or ""
        if vin and vin in seen:
            continue
        seen.add(vin)
        deduped.append(listing)
    if len(deduped) < len(all_raw):
        log.info("Deduplicated %d -> %d listings", len(all_raw), len(deduped))

    filtered = apply_filters(deduped)
    if not filtered:
        log.warning("No listings passed filters — nothing to save.")
        return []

    enriched = enrich_listings(filtered)
    enriched.sort(key=lambda x: x.get("value_score") or 0, reverse=True)
    return enriched


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
        result = LLMAnalyzer().analyze(listings)
    finally:
        config.OLLAMA_ENABLED    = original_ollama
        config.ANTHROPIC_ENABLED = original_anthropic

    return result


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
                    log.info("Heartbeat — tracker is running, next run in ~%s",
                             sched.next_run())
                    heartbeat_counter = 0
        except KeyboardInterrupt:
            log.info("Shutting down.")
            sys.exit(0)
    else:
        run_once(**kwargs)


if __name__ == "__main__":
    main()
