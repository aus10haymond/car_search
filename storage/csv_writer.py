"""
CSV output — writes a timestamped file and overwrites carvana_latest.csv.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_COLUMNS = [
    "run_id", "scraped_at", "year", "make", "model", "trim", "price", "mileage",
    "monthly_carvana", "monthly_estimated",
    "price_per_mile", "value_score", "is_hybrid", "is_alert", "price_drop_pct",
    "vin", "url", "llm_backend_used", "extraction_strategy",
    "color_exterior",
]


def write_results(listings: list[dict], run_id: str, llm_backend: str = "none") -> Path:
    """
    Write two CSV files:
      1. Timestamped: carvana_YYYYMMDD_HHMMSS.csv
      2. Latest:      carvana_latest.csv (always overwritten)

    Returns the path of the timestamped file.
    """
    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = out_dir / f"carvana_{timestamp}.csv"
    latest_path      = out_dir / "carvana_latest.csv"

    rows = [_build_row(listing, run_id, llm_backend) for listing in listings]

    for path in (timestamped_path, latest_path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    log.info(
        "Saved %d listings -> %s (and carvana_latest.csv)",
        len(listings), timestamped_path.name,
    )
    return timestamped_path


def _build_row(listing: dict, run_id: str, llm_backend: str) -> dict:
    row = {col: listing.get(col, "") for col in _COLUMNS}
    row["run_id"]          = run_id
    row["llm_backend_used"] = llm_backend
    # Normalise bool → 0/1 for CSV readability
    if "is_hybrid" in listing:
        row["is_hybrid"] = int(bool(listing["is_hybrid"]))
    return row
