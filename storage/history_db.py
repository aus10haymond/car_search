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
CREATE TABLE IF NOT EXISTS model_price_stats (
    run_id     TEXT NOT NULL,
    run_at     TEXT NOT NULL,
    make       TEXT NOT NULL,
    model      TEXT NOT NULL,
    avg_price  REAL,
    med_price  REAL,
    min_price  REAL,
    max_price  REAL,
    count      INTEGER,
    PRIMARY KEY (run_id, make, model)
);

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
    profile_id        TEXT NOT NULL DEFAULT 'default',
    vin               TEXT,
    scraped_at        TEXT,
    year              INTEGER,
    make              TEXT,
    model             TEXT,
    trim              TEXT,
    price             REAL,
    mileage           INTEGER,
    monthly_estimated REAL,
    value_score       REAL,
    is_hybrid         INTEGER,
    drivetrain        TEXT,
    color_exterior    TEXT,
    shipping          REAL,
    url               TEXT,
    UNIQUE(run_id, vin, profile_id)
);

CREATE TABLE IF NOT EXISTS profile_llm_analysis (
    profile_id    TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    run_at        TEXT NOT NULL,
    analysis      TEXT,
    backend_used  TEXT,
    model_used    TEXT,
    top_pick_vins TEXT
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
    """Create tables if they don't exist, and migrate schema if needed."""
    with _connect() as conn:
        conn.executescript(_DDL)
        _migrate_listings_profile_id(conn)
        _migrate_add_listing_extra_fields(conn)
    log.debug("Database initialised at %s", config.DB_PATH)


def _migrate_add_listing_extra_fields(conn: sqlite3.Connection) -> None:
    """Add drivetrain, color_exterior, and shipping columns to listings if absent."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    for col, coltype in [("drivetrain", "TEXT"), ("color_exterior", "TEXT"), ("shipping", "REAL")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {coltype}")
            log.info("Migration: added '%s' column to listings table", col)


def _migrate_listings_profile_id(conn: sqlite3.Connection) -> None:
    """
    Add profile_id to listings and update the UNIQUE constraint if not already present.
    SQLite cannot drop/modify constraints, so this rebuilds the table in place.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "profile_id" in cols:
        return  # already migrated

    log.info("Migrating listings table: adding profile_id column")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listings_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id            TEXT NOT NULL REFERENCES runs(run_id),
            profile_id        TEXT NOT NULL DEFAULT 'default',
            vin               TEXT,
            scraped_at        TEXT,
            year              INTEGER,
            make              TEXT,
            model             TEXT,
            trim              TEXT,
            price             REAL,
            mileage           INTEGER,
            monthly_estimated REAL,
            value_score       REAL,
            is_hybrid         INTEGER,
            url               TEXT,
            UNIQUE(run_id, vin, profile_id)
        );

        INSERT INTO listings_new
            (run_id, profile_id, vin, scraped_at, year, make, model, trim,
             price, mileage, monthly_estimated, value_score, is_hybrid, url)
        SELECT run_id, 'default', vin, scraped_at, year, make, model, trim,
               price, mileage, monthly_estimated, value_score, is_hybrid, url
        FROM listings;

        DROP TABLE listings;

        ALTER TABLE listings_new RENAME TO listings;
    """)
    log.info("Listings table migration complete — existing rows tagged as profile 'default'")


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


def save_listings(listings: list[dict], run_id: str, profile_id: str = "default") -> None:
    """
    Insert listings into the listings and price_history tables.
    Duplicate (run_id, vin, profile_id) triples are silently ignored.
    price_history uses (vin, run_id) as its key — if two profiles scrape the same
    VIN in the same run the second insert is silently ignored (price is identical).
    """
    run_at = _get_run_at(run_id)

    listing_rows = []
    price_rows   = []

    for listing in listings:
        vin = listing.get("vin") or ""
        listing_rows.append((
            run_id,
            profile_id,
            vin,
            listing.get("scraped_at", ""),
            listing.get("year"),
            listing.get("make", ""),
            listing.get("model", ""),
            listing.get("trim", ""),
            listing.get("price"),
            listing.get("mileage"),
            listing.get("monthly_estimated"),
            listing.get("value_score"),
            int(bool(listing.get("is_hybrid", False))),
            listing.get("drivetrain") or None,
            listing.get("color_exterior") or None,
            listing.get("shipping"),
            listing.get("url", ""),
        ))
        if vin and listing.get("price"):
            price_rows.append((vin, run_id, run_at, listing["price"]))

    with _connect() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO listings
               (run_id, profile_id, vin, scraped_at, year, make, model, trim, price, mileage,
                monthly_estimated, value_score, is_hybrid, drivetrain, color_exterior, shipping, url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            listing_rows,
        )
        if price_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO price_history (vin, run_id, run_at, price)
                   VALUES (?,?,?,?)""",
                price_rows,
            )

    log.debug("Saved %d listings to DB for run %s (profile=%s)", len(listings), run_id, profile_id)


# ── Read operations ───────────────────────────────────────────────────────────

def get_price_history(vin: str) -> list[dict]:
    """Return all price records for a VIN ordered by run date."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM price_history WHERE vin=? ORDER BY run_at",
            (vin,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_new_listings(current_vins: set[str], profile_id: str = "default") -> set[str]:
    """Return VINs in current_vins that have never appeared for this profile before."""
    if not current_vins:
        return set()
    with _connect() as conn:
        placeholders = ",".join("?" * len(current_vins))
        known = conn.execute(
            f"SELECT DISTINCT vin FROM listings "
            f"WHERE vin IN ({placeholders}) AND profile_id = ?",
            list(current_vins) + [profile_id],
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


def save_model_stats(listings: list[dict], run_id: str) -> None:
    """
    Compute and store per-model aggregate price stats for this run.
    Groups by (make, model) regardless of trim or year.
    """
    run_at = _get_run_at(run_id)
    groups: dict[tuple, list[float]] = {}
    for listing in listings:
        key   = (listing.get("make", ""), listing.get("model", ""))
        price = listing.get("price")
        if price:
            groups.setdefault(key, []).append(price)

    rows = []
    for (make, model), prices in groups.items():
        sorted_p = sorted(prices)
        n        = len(sorted_p)
        median   = (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2 if n % 2 == 0 else sorted_p[n // 2]
        rows.append((
            run_id, run_at, make, model,
            round(sum(prices) / n, 2),
            round(median, 2),
            round(min(prices), 2),
            round(max(prices), 2),
            n,
        ))

    with _connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO model_price_stats
               (run_id, run_at, make, model, avg_price, med_price, min_price, max_price, count)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    log.debug("Saved model price stats for %d groups (run %s)", len(rows), run_id)


def backfill_model_stats() -> int:
    """
    Recompute model_price_stats for every run in the listings table that
    doesn't already have a stats row. Returns the number of runs filled.
    """
    with _connect() as conn:
        # Find all (run_id, make, model) combos in listings that have no stats row
        missing = conn.execute(
            """
            SELECT l.run_id, l.make, l.model, r.run_at
            FROM listings l
            JOIN runs r ON l.run_id = r.run_id
            WHERE l.price IS NOT NULL AND l.price > 0
              AND NOT EXISTS (
                  SELECT 1 FROM model_price_stats s
                  WHERE s.run_id = l.run_id
                    AND s.make   = l.make
                    AND s.model  = l.model
              )
            GROUP BY l.run_id, l.make, l.model
            """
        ).fetchall()

        if not missing:
            return 0

        # For each missing combo, pull all prices and compute stats
        rows = []
        for row in missing:
            run_id, make, model, run_at = row["run_id"], row["make"], row["model"], row["run_at"]
            prices_raw = conn.execute(
                "SELECT price FROM listings WHERE run_id=? AND make=? AND model=? AND price > 0",
                (run_id, make, model),
            ).fetchall()
            prices = sorted(p["price"] for p in prices_raw)
            n = len(prices)
            if n == 0:
                continue
            median = (prices[n // 2 - 1] + prices[n // 2]) / 2 if n % 2 == 0 else prices[n // 2]
            rows.append((
                run_id, run_at, make, model,
                round(sum(prices) / n, 2),
                round(median, 2),
                round(min(prices), 2),
                round(max(prices), 2),
                n,
            ))

        conn.executemany(
            """INSERT OR IGNORE INTO model_price_stats
               (run_id, run_at, make, model, avg_price, med_price, min_price, max_price, count)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    return len(rows)


def get_model_price_trends(
    days: int = 60,
    vehicles: list[tuple[str, str]] | None = None,
) -> dict[str, list[dict]]:
    """
    Return price trend data for each make/model over the past `days` days.
    If `vehicles` is provided (list of (make, model) tuples), only those
    models are included — used to scope trends to a single profile.

    Returns a dict keyed by "Make Model" with a list of dicts:
        [{"date": "Apr 08", "avg": 30500, "min": 27990}, ...]
    Ordered oldest-first so charts render left-to-right.
    """
    cutoff = _days_ago_iso(days)
    with _connect() as conn:
        if vehicles:
            placeholders = " OR ".join("(make=? AND model=?)" for _ in vehicles)
            params: list = [cutoff] + [val for pair in vehicles for val in pair]
            rows = conn.execute(
                f"""SELECT make, model, run_at, avg_price, min_price
                    FROM model_price_stats
                    WHERE run_at >= ? AND ({placeholders})
                    ORDER BY make, model, run_at""",
                params,
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT make, model, run_at, avg_price, min_price
                   FROM model_price_stats
                   WHERE run_at >= ?
                   ORDER BY make, model, run_at""",
                (cutoff,),
            ).fetchall()

    trends: dict[str, list[dict]] = {}
    for row in rows:
        key  = f"{row['make']} {row['model']}"
        date = _format_date(row["run_at"])
        trends.setdefault(key, []).append({
            "date":    date,
            "avg":     row["avg_price"],
            "min":     row["min_price"],
        })
    return trends


def save_profile_llm_analysis(profile_id: str, run_id: str, run_at: str, llm_result) -> None:
    """
    Upsert the LLM analysis for a profile.  Only the most recent analysis is
    kept — each successful run overwrites the previous one.
    """
    import json as _json
    top_vins_json = _json.dumps(llm_result.top_pick_vins or [])
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO profile_llm_analysis
               (profile_id, run_id, run_at, analysis, backend_used, model_used, top_pick_vins)
               VALUES (?,?,?,?,?,?,?)""",
            (profile_id, run_id, run_at,
             llm_result.analysis,
             llm_result.backend_used,
             llm_result.model_used,
             top_vins_json),
        )
    log.debug("LLM analysis saved for profile '%s' (run %s)", profile_id, run_id)


def get_profile_llm_analysis(profile_id: str) -> dict | None:
    """Return the stored LLM analysis for a profile, or None if none exists."""
    import json as _json
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM profile_llm_analysis WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["top_pick_vins"] = _json.loads(d.get("top_pick_vins") or "[]")
    except Exception:
        d["top_pick_vins"] = []
    return d


def get_last_run_id_for_profile(profile_id: str) -> str | None:
    """Return the run_id of the most recent run that has listings for this profile."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT l.run_id FROM listings l
               JOIN runs r ON l.run_id = r.run_id
               WHERE l.profile_id = ?
               ORDER BY r.run_at DESC
               LIMIT 1""",
            (profile_id,),
        ).fetchone()
    return row["run_id"] if row else None


def get_listings_for_run(run_id: str, profile_id: str) -> list[dict]:
    """Return all listings stored for a specific (run_id, profile_id) pair, sorted by value_score."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM listings
               WHERE run_id = ? AND profile_id = ?
               ORDER BY value_score DESC""",
            (run_id, profile_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_history_summary() -> list[dict]:
    """Return all runs ordered by date descending."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY run_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_all_time_stats() -> dict:
    """
    Return aggregate stats across all runs for the --history display:
      - total_runs, total_unique_vins
      - per-model: latest avg/min price, number of runs tracked
      - all-time cheapest listing (vin, year, make, model, trim, price, run_at)
    """
    with _connect() as conn:
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        total_vins = conn.execute(
            "SELECT COUNT(DISTINCT vin) FROM listings WHERE vin != ''"
        ).fetchone()[0]

        # Latest avg + min per model (most recent run_at per make/model)
        model_rows = conn.execute(
            """
            SELECT make, model, avg_price, min_price, count, run_at
            FROM model_price_stats
            WHERE (make, model, run_at) IN (
                SELECT make, model, MAX(run_at)
                FROM model_price_stats
                GROUP BY make, model
            )
            ORDER BY make, model
            """
        ).fetchall()

        # All-time cheapest listing with a VIN
        cheapest = conn.execute(
            """
            SELECT l.year, l.make, l.model, l.trim, l.price, r.run_at
            FROM listings l
            JOIN runs r ON l.run_id = r.run_id
            WHERE l.price IS NOT NULL AND l.price > 0
            ORDER BY l.price ASC
            LIMIT 1
            """
        ).fetchone()

    return {
        "total_runs":       total_runs,
        "total_unique_vins": total_vins,
        "model_latest":     [dict(r) for r in model_rows],
        "cheapest":         dict(cheapest) if cheapest else None,
    }


# ── Internal ──────────────────────────────────────────────────────────────────

def _days_ago_iso(days: int) -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _format_date(iso: str) -> str:
    """Convert ISO timestamp to short label like 'Apr 08'."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d")
    except Exception:
        return iso[:10]


def _get_run_at(run_id: str) -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT run_at FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    return row["run_at"] if row else ""
