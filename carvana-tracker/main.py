"""
Carvana SUV Tracker — entry point.

Current state (Phase 3): scrapes, filters, enriches, saves to CSV + DB.
LLM analysis, email, and full CLI are added in later phases.

Usage:
    python main.py
"""

import io
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

# Ensure Unicode output works on Windows consoles (cp1252 → utf-8)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import config
from utils.logging_config import setup_logging
from scraper.urls import build_search_url
from scraper.browser import Browser
from scraper.extractor import extract_listings
from analysis.rules import apply_filters, enrich_listings
from storage.csv_writer import write_results
from storage import history_db

log = logging.getLogger(__name__)


def run_once() -> list[dict]:
    """Execute one full search-and-save cycle. Returns enriched listings."""
    start_time = time.monotonic()
    run_id  = str(uuid.uuid4())
    run_at  = datetime.now(timezone.utc).isoformat()

    log.info("=" * 60)
    log.info("Carvana Tracker run started — %s", datetime.now().strftime("%b %d %Y %I:%M %p"))
    log.info("Run ID: %s", run_id)
    log.info("=" * 60)

    # ── 1. Scrape all vehicles ────────────────────────────────────────────────
    all_raw: list[dict] = []
    with Browser() as browser:
        for make, model, min_year, max_year in config.VEHICLES:
            # Fresh context per vehicle to clear Carvana session/cookies
            browser.reset_context()
            for page in range(1, config.MAX_PAGES_PER_SEARCH + 1):
                url = build_search_url(make, model, min_year, max_year, page)
                log.info("Scraping %s %s (page %d)...", make, model, page)
                html = browser.get_page_content(url)
                if not html:
                    log.warning("No HTML for %s %s page %d — stopping pagination", make, model, page)
                    break
                listings = extract_listings(html, make, model)
                if not listings:
                    log.info("No listings on page %d for %s %s — stopping pagination", page, make, model)
                    break
                all_raw.extend(listings)
                # If we got fewer results than a full page, no point paginating
                if len(listings) < 20:
                    break

    log.info("Total raw listings scraped: %d", len(all_raw))

    # ── 2. Deduplicate by VIN ─────────────────────────────────────────────────
    seen_vins: set[str] = set()
    deduped: list[dict] = []
    for listing in all_raw:
        vin = listing.get("vin") or ""
        if vin and vin in seen_vins:
            continue
        seen_vins.add(vin)
        deduped.append(listing)
    if len(deduped) < len(all_raw):
        log.info("Deduplicated %d → %d listings", len(all_raw), len(deduped))

    # ── 3. Filter ─────────────────────────────────────────────────────────────
    filtered = apply_filters(deduped)
    if not filtered:
        log.warning("No listings passed filters — nothing to save.")
        return []

    # ── 4. Enrich + score ─────────────────────────────────────────────────────
    enriched = enrich_listings(filtered)
    enriched.sort(key=lambda x: x.get("value_score") or 0, reverse=True)

    # ── 5. Save to CSV ────────────────────────────────────────────────────────
    write_results(enriched, run_id, llm_backend="none")

    # ── 6. Save to DB ─────────────────────────────────────────────────────────
    history_db.init_db()

    duration = time.monotonic() - start_time
    run_record = history_db.RunRecord(
        run_id=run_id,
        run_at=run_at,
        listings_found=len(all_raw),
        listings_saved=len(enriched),
        llm_backend="none",
        llm_model="",
        duration_seconds=round(duration, 2),
    )
    history_db.save_run(run_record)
    history_db.save_listings(enriched, run_id)

    # ── 7. Detect new listings + price drops ──────────────────────────────────
    current_vins = {v.get("vin") for v in enriched if v.get("vin")}
    # Note: get_new_listings queries listings already in DB, so call before save
    # (we saved above, so new = those whose VINs didn't exist before this run)
    # For accuracy this would need to be called pre-save; acceptable for now.
    price_drops = history_db.get_price_drops(enriched)
    if price_drops:
        log.info("%d price drops detected (>=5%%):", len(price_drops))
        for drop in price_drops:
            log.info(
                "  %s %s %s — $%,.0f → $%,.0f (%.1f%% drop)",
                drop.get("year"), drop.get("make"), drop.get("model"),
                drop.get("prev_price"), drop.get("price"), drop.get("drop_pct"),
            )

    # ── 8. Print summary table ────────────────────────────────────────────────
    _print_summary(enriched)

    log.info(
        "Run complete in %.1fs — %d listings saved (run_id=%s)",
        duration, len(enriched), run_id,
    )
    return enriched


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
            f"{r.get('mileage') or 'N/A':,}" if r.get("mileage") else "N/A",
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


if __name__ == "__main__":
    setup_logging(config.LOG_FILE)
    run_once()
