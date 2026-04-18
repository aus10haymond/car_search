"""
Tests for email table row highlighting:
  - NEW badge on first-time listings
  - Yellow row background on price drops
  - Correct drop % displayed
  - DB queries that feed those flags (get_new_listings, get_price_drops)
"""

import sys
import os
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from analysis.llm import LLMResult
from notifications.email_alert import _build_html
from storage import history_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _listing(**kwargs) -> dict:
    base = {
        "vin": "VIN001",
        "year": 2023, "make": "Toyota", "model": "RAV4",
        "trim": "XLE", "price": 30000.0, "mileage": 40000,
        "color_exterior": "Red", "url": "https://example.com",
        "monthly_estimated": 580.0, "monthly_carvana": None,
        "value_score": 75.0, "is_hybrid": False,
    }
    base.update(kwargs)
    return base


def _no_llm() -> LLMResult:
    return LLMResult(
        analysis=None, backend_used="none", model_used="",
        tokens_used=None, latency_ms=0, error=None,
        top_pick_vins=[],
    )


class _TempDB:
    """Patch config.DB_PATH with a fresh temp file for a single test."""
    def __enter__(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig = config.DB_PATH
        config.DB_PATH = self._tmp.name
        history_db.init_db()
        return self._tmp.name

    def __exit__(self, *_):
        config.DB_PATH = self._orig
        # Windows holds SQLite file locks until GC — suppress cleanup errors
        try:
            Path(self._tmp.name).unlink(missing_ok=True)
        except PermissionError:
            pass


def _seed_known_vin(db_path: str, vin: str, profile_id: str = "default") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO runs "
            "(run_id, run_at, listings_found, listings_saved, llm_backend, llm_model, duration_seconds)"
            " VALUES (?,?,?,?,?,?,?)",
            ("run_prev", "2026-01-01T00:00:00", 1, 1, "none", "", 1.0),
        )
        conn.execute(
            "INSERT OR IGNORE INTO listings "
            "(run_id, profile_id, vin, scraped_at, year, make, model, trim, "
            " price, mileage, monthly_estimated, value_score, is_hybrid, url)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("run_prev", profile_id, vin, "", 2023, "Toyota", "RAV4", "XLE",
             30000, 40000, 580, 75, 0, ""),
        )


def _seed_price_history(db_path: str, vin: str, price: float,
                        run_id: str = "run_hist",
                        run_at: str = "2026-01-01T00:00:00") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO runs "
            "(run_id, run_at, listings_found, listings_saved, llm_backend, llm_model, duration_seconds)"
            " VALUES (?,?,?,?,?,?,?)",
            (run_id, run_at, 1, 1, "none", "", 1.0),
        )
        conn.execute(
            "INSERT OR IGNORE INTO price_history (vin, run_id, run_at, price) VALUES (?,?,?,?)",
            (vin, run_id, run_at, price),
        )


# ── HTML output: NEW badge ────────────────────────────────────────────────────

def test_new_listing_badge_present():
    listing = _listing(vin="NEW001")
    html = _build_html([listing], _no_llm(), [], {}, new_vins={"NEW001"})
    # Legend has one NEW span; a new row should add a second
    assert html.count(">NEW</span>") == 2


def test_new_listing_badge_absent_when_not_new():
    listing = _listing(vin="OLD001")
    html = _build_html([listing], _no_llm(), [], {}, new_vins=set())
    # Only the legend's NEW span — no row badge
    assert html.count(">NEW</span>") == 1


def test_new_listing_vin_mismatch_no_badge():
    """If new_vins contains a different VIN, this row should not get a badge."""
    listing = _listing(vin="MINE001")
    html = _build_html([listing], _no_llm(), [], {}, new_vins={"OTHER999"})
    assert html.count(">NEW</span>") == 1


# ── HTML output: price drop row highlight ────────────────────────────────────

def test_price_drop_row_has_drop_indicator():
    """Price-drop rows show the ▼ percentage indicator (row background was removed)."""
    listing = _listing(vin="DROP001", price=27000.0)
    price_drops = [{**listing, "prev_price": 30000.0, "drop_pct": 10.0}]
    html = _build_html([listing], _no_llm(), price_drops, {})
    assert "10.0% drop" in html
    # Row-level yellow background is intentionally absent
    assert "<tr style='background:#fffde7'>" not in html


def test_normal_row_no_yellow_background():
    listing = _listing(vin="PLAIN001")
    html = _build_html([listing], _no_llm(), [], {})
    assert "<tr style='background:#fffde7'>" not in html


def test_price_drop_pct_displayed():
    listing = _listing(vin="DROP002", price=27000.0)
    price_drops = [{**listing, "prev_price": 30000.0, "drop_pct": 10.0}]
    html = _build_html([listing], _no_llm(), price_drops, {})
    assert "10.0% drop" in html


def test_price_drop_footnote_shown():
    listing = _listing(vin="DROP003", price=27000.0)
    price_drops = [{**listing, "prev_price": 30000.0, "drop_pct": 10.0}]
    html = _build_html([listing], _no_llm(), price_drops, {})
    assert "Price drops are relative to the previous tracker run" in html


def test_price_drop_footnote_absent_when_no_drops():
    html = _build_html([_listing()], _no_llm(), [], {})
    assert "Price drops are relative" not in html


def test_drop_only_shows_indicator_for_matching_vin():
    """Drop indicator appears only for the dropped VIN's row, not unrelated rows."""
    listing_a = _listing(vin="A001", price=27000.0)
    listing_b = _listing(vin="B001", price=30000.0)
    price_drops = [{**listing_a, "prev_price": 30000.0, "drop_pct": 10.0}]
    html = _build_html([listing_a, listing_b], _no_llm(), price_drops, {})
    # Drop indicator text appears exactly once (A001's row)
    assert html.count("10.0% drop") == 1
    # No yellow row backgrounds anywhere
    assert "<tr style='background:#fffde7'>" not in html


def test_new_and_drop_coexist_on_same_row():
    vin = "BOTH001"
    listing = _listing(vin=vin, price=27000.0)
    price_drops = [{**listing, "prev_price": 30000.0, "drop_pct": 10.0}]
    html = _build_html([listing], _no_llm(), price_drops, {}, new_vins={vin})
    # Drop indicator and NEW badge both appear
    assert "10.0% drop" in html
    assert html.count(">NEW</span>") == 2


# ── Star / top-pick logic ─────────────────────────────────────────────────────

def _llm_with_picks(*vins: str) -> LLMResult:
    return LLMResult(
        analysis=None, backend_used="none", model_used="",
        tokens_used=None, latency_ms=0, error=None,
        top_pick_vins=list(vins),
    )


def _count_stars(html: str) -> int:
    """Count how many table rows have the ★ marker.
    Row entries look like <b>★ 3</b>; the legend has <b>★</b> (no space/digit).
    """
    return html.count("<b>★ ")


def test_stars_all_three_llm_picks_in_top10():
    """LLM picks are moved to the top of the table and starred at rows 1, 2, 3."""
    listings = [_listing(vin=f"V{i:03d}", value_score=100 - i) for i in range(10)]
    llm = _llm_with_picks("V000", "V003", "V007")
    html = _build_html(listings, llm, [], {})
    assert _count_stars(html) == 3
    # Picks are pinned to positions 1, 2, 3 in LLM rank order
    assert "<b>★ 1</b>" in html  # V000
    assert "<b>★ 2</b>" in html  # V003 (moved up from original score-order position 4)
    assert "<b>★ 3</b>" in html  # V007 (moved up from original score-order position 8)


def test_stars_partial_llm_overlap_only_stars_present_picks():
    """When some LLM picks don't exist in listings, only present picks are starred."""
    listings = [_listing(vin=f"V{i:03d}", value_score=float(100 - i)) for i in range(10)]
    llm = _llm_with_picks("V002", "OUTSIDE_A", "OUTSIDE_B")
    html = _build_html(listings, llm, [], {})
    # Only V002 is in the listings; OUTSIDE_A/B are not → 1 star
    assert _count_stars(html) == 1
    # V002 is pinned to row 1 as the only present LLM pick
    assert "<b>★ 1</b>" in html


def test_stars_no_llm_overlap_uses_top_score():
    """When no LLM picks appear in the top 10, top-3-by-score are starred."""
    listings = [_listing(vin=f"V{i:03d}", value_score=float(100 - i)) for i in range(10)]
    llm = _llm_with_picks("OUTSIDE_1", "OUTSIDE_2", "OUTSIDE_3")
    html = _build_html(listings, llm, [], {})
    assert _count_stars(html) == 3
    assert "<b>★ 1</b>" in html
    assert "<b>★ 2</b>" in html
    assert "<b>★ 3</b>" in html


def test_stars_no_llm_picks_uses_top_score():
    """When LLM returns no picks at all, top-3-by-score are starred."""
    listings = [_listing(vin=f"V{i:03d}", value_score=float(100 - i)) for i in range(10)]
    html = _build_html(listings, _no_llm(), [], {})
    assert _count_stars(html) == 3
    assert "<b>★ 1</b>" in html
    assert "<b>★ 2</b>" in html
    assert "<b>★ 3</b>" in html


# ── DB: get_new_listings ──────────────────────────────────────────────────────

def test_get_new_listings_all_new_on_empty_db():
    with _TempDB():
        result = history_db.get_new_listings({"VIN1", "VIN2"})
        assert result == {"VIN1", "VIN2"}


def test_get_new_listings_known_vin_excluded():
    with _TempDB() as db_path:
        _seed_known_vin(db_path, "KNOWN")
        result = history_db.get_new_listings({"KNOWN", "FRESH"})
        assert result == {"FRESH"}


def test_get_new_listings_all_known_returns_empty():
    with _TempDB() as db_path:
        _seed_known_vin(db_path, "A")
        _seed_known_vin(db_path, "B")
        result = history_db.get_new_listings({"A", "B"})
        assert result == set()


def test_get_new_listings_profile_scoped():
    """A VIN known for profile A is still new for profile B."""
    with _TempDB() as db_path:
        _seed_known_vin(db_path, "SHARED", profile_id="profile_a")
        result = history_db.get_new_listings({"SHARED"}, profile_id="profile_b")
        assert result == {"SHARED"}


def test_get_new_listings_empty_input():
    with _TempDB():
        assert history_db.get_new_listings(set()) == set()


# ── DB: get_price_drops ───────────────────────────────────────────────────────

def test_get_price_drops_detects_drop():
    with _TempDB() as db_path:
        _seed_price_history(db_path, "DROP1", 30000.0)
        listing = _listing(vin="DROP1", price=27000.0)
        drops = history_db.get_price_drops([listing])
        assert len(drops) == 1
        assert drops[0]["vin"] == "DROP1"
        assert drops[0]["drop_pct"] == 10.0


def test_get_price_drops_price_increase_not_flagged():
    with _TempDB() as db_path:
        _seed_price_history(db_path, "UP1", 25000.0)
        listing = _listing(vin="UP1", price=27000.0)
        drops = history_db.get_price_drops([listing])
        assert drops == []


def test_get_price_drops_small_drop_below_threshold():
    with _TempDB() as db_path:
        _seed_price_history(db_path, "TINY1", 30000.0)
        listing = _listing(vin="TINY1", price=29500.0)   # 1.67% — below 5% threshold
        drops = history_db.get_price_drops([listing])
        assert drops == []


def test_get_price_drops_no_prior_price():
    with _TempDB():
        listing = _listing(vin="UNSEEN1", price=30000.0)
        drops = history_db.get_price_drops([listing])
        assert drops == []


def test_get_price_drops_uses_most_recent_price():
    """Compare against the most recent DB price, not the oldest."""
    with _TempDB() as db_path:
        # Two prior runs: $32k then $30k
        _seed_price_history(db_path, "MULTI1", 32000.0, run_id="run_a", run_at="2026-01-01T00:00:00")
        _seed_price_history(db_path, "MULTI1", 30000.0, run_id="run_b", run_at="2026-02-01T00:00:00")
        # Current price $27k — 10% drop from $30k, not 15.6% from $32k
        listing = _listing(vin="MULTI1", price=27000.0)
        drops = history_db.get_price_drops([listing])
        assert len(drops) == 1
        assert drops[0]["drop_pct"] == 10.0


def test_get_price_drops_exact_threshold_included():
    with _TempDB() as db_path:
        _seed_price_history(db_path, "EXACT1", 30000.0)
        listing = _listing(vin="EXACT1", price=28500.0)  # exactly 5.0%
        drops = history_db.get_price_drops([listing])
        assert len(drops) == 1
