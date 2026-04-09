"""
SQLite history database — persists listings across runs for trend detection.
"""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import config

log = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class RunRecord:
    run_id:           str
    run_at:           str   # ISO 8601
    listings_found:   int
    listings_saved:   int
    llm_backend:      str
    llm_model:        str
    duration_seconds: float


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    run_at           TEXT NOT NULL,
    listings_found   INTEGER,
    listings_saved   INTEGER,
    llm_backend      TEXT,
    llm_model        TEXT,
    duration_seconds REAL
);

CREATE TABLE IF NOT EXISTS listings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL REFERENCES runs(run_id),
    vin               TEXT,
    scraped_at        TEXT,
    year              INTEGER,
    make              TEXT,
    model             TEXT,
    trim              TEXT,
    price             REAL,
    mileage           INTEGER,
    monthly_estimated REAL,
    shipping          REAL,
    value_score       REAL,
    is_hybrid         INTEGER,
    url               TEXT,
    UNIQUE(run_id, vin)
);

CREATE TABLE IF NOT EXISTS price_history (
    vin    TEXT NOT NULL,
    run_id TEXT NOT NULL,
    run_at TEXT NOT NULL,
    price  REAL NOT NULL,
    PRIMARY KEY (vin, run_id)
);
"""


# ── Connection helper ─────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    db_path = Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript(_DDL)
    log.debug("Database initialised at %s", config.DB_PATH)


# ── Write operations ──────────────────────────────────────────────────────────

def save_run(run: RunRecord) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, run_at, listings_found, listings_saved,
                llm_backend, llm_model, duration_seconds)
               VALUES (?,?,?,?,?,?,?)""",
            (
                run.run_id, run.run_at, run.listings_found, run.listings_saved,
                run.llm_backend, run.llm_model, run.duration_seconds,
            ),
        )
    log.debug("Run %s saved to DB", run.run_id)


def save_listings(listings: list[dict], run_id: str) -> None:
    """
    Insert listings into the listings and price_history tables.
    Duplicate (run_id, vin) pairs are silently ignored.
    """
    run_at = _get_run_at(run_id)

    listing_rows = []
    price_rows   = []

    for listing in listings:
        vin = listing.get("vin") or ""
        listing_rows.append((
            run_id,
            vin,
            listing.get("scraped_at", ""),
            listing.get("year"),
            listing.get("make", ""),
            listing.get("model", ""),
            listing.get("trim", ""),
            listing.get("price"),
            listing.get("mileage"),
            listing.get("monthly_estimated"),
            listing.get("shipping"),
            listing.get("value_score"),
            int(bool(listing.get("is_hybrid", False))),
            listing.get("url", ""),
        ))
        if vin and listing.get("price"):
            price_rows.append((vin, run_id, run_at, listing["price"]))

    with _connect() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO listings
               (run_id, vin, scraped_at, year, make, model, trim, price, mileage,
                monthly_estimated, shipping, value_score, is_hybrid, url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            listing_rows,
        )
        if price_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO price_history (vin, run_id, run_at, price)
                   VALUES (?,?,?,?)""",
                price_rows,
            )

    log.debug("Saved %d listings to DB for run %s", len(listings), run_id)


# ── Read operations ───────────────────────────────────────────────────────────

def get_price_history(vin: str) -> list[dict]:
    """Return all price records for a VIN ordered by run date."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM price_history WHERE vin=? ORDER BY run_at",
            (vin,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_new_listings(current_vins: set[str]) -> set[str]:
    """Return VINs in current_vins that have never appeared in the DB before."""
    if not current_vins:
        return set()
    with _connect() as conn:
        placeholders = ",".join("?" * len(current_vins))
        known = conn.execute(
            f"SELECT DISTINCT vin FROM listings WHERE vin IN ({placeholders})",
            list(current_vins),
        ).fetchall()
    known_vins = {row["vin"] for row in known}
    return current_vins - known_vins


def get_price_drops(listings: list[dict], threshold_pct: float = 5.0) -> list[dict]:
    """
    For each listing with a VIN and a previous price in the DB,
    return listings where price dropped by >= threshold_pct since last seen.
    """
    drops = []
    with _connect() as conn:
        for listing in listings:
            vin   = listing.get("vin")
            price = listing.get("price")
            if not vin or not price:
                continue
            row = conn.execute(
                """SELECT price FROM price_history
                   WHERE vin=?
                   ORDER BY run_at DESC
                   LIMIT 1""",
                (vin,),
            ).fetchone()
            if row:
                prev_price = row["price"]
                if prev_price > 0:
                    drop_pct = (prev_price - price) / prev_price * 100
                    if drop_pct >= threshold_pct:
                        drops.append({**listing, "prev_price": prev_price, "drop_pct": round(drop_pct, 2)})
    return drops


def get_history_summary() -> list[dict]:
    """Return all runs ordered by date descending."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY run_at DESC").fetchall()
    return [dict(r) for r in rows]


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_run_at(run_id: str) -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT run_at FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    return row["run_at"] if row else ""
