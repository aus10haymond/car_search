import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from analysis.rules import (
    apply_filters,
    enrich_listing,
    enrich_listings,
    _is_hybrid,
    _compute_group_averages,
    _value_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _listing(**kwargs) -> dict:
    """Return a minimal valid listing, overriding with kwargs."""
    base = {
        "make": "Toyota", "model": "RAV4", "year": 2023,
        "price": 30000.0, "mileage": 40000,
        "trim": "XLE", "shipping": None, "vin": "ABC123",
    }
    base.update(kwargs)
    return base


# ── apply_filters ─────────────────────────────────────────────────────────────

def test_filter_passes_valid():
    listings = [_listing()]
    assert len(apply_filters(listings)) == 1


def test_filter_removes_no_price():
    listings = [_listing(price=None), _listing(price=0)]
    assert apply_filters(listings) == []


def test_filter_removes_over_price():
    listings = [_listing(price=config.MAX_PRICE + 1)]
    assert apply_filters(listings) == []


def test_filter_keeps_at_max_price():
    listings = [_listing(price=config.MAX_PRICE)]
    assert len(apply_filters(listings)) == 1


def test_filter_removes_over_mileage():
    listings = [_listing(mileage=config.MAX_MILEAGE + 1)]
    assert apply_filters(listings) == []


def test_filter_keeps_at_max_mileage():
    listings = [_listing(mileage=config.MAX_MILEAGE)]
    assert len(apply_filters(listings)) == 1


def test_filter_removes_under_year():
    listings = [_listing(year=config.MIN_YEAR - 1)]
    assert apply_filters(listings) == []


def test_filter_removes_over_year():
    listings = [_listing(year=config.MAX_YEAR + 1)]
    assert apply_filters(listings) == []


def test_filter_keeps_none_mileage():
    """None mileage should not be filtered — we don't have enough info."""
    listings = [_listing(mileage=None)]
    assert len(apply_filters(listings)) == 1


def test_filter_keeps_none_year():
    listings = [_listing(year=None)]
    assert len(apply_filters(listings)) == 1


def test_filter_mixed_batch():
    listings = [
        _listing(),                                  # keep
        _listing(price=config.MAX_PRICE + 1),        # remove
        _listing(mileage=config.MAX_MILEAGE + 1),    # remove
        _listing(year=2019),                         # remove
    ]
    assert len(apply_filters(listings)) == 1


# ── Hybrid detection ──────────────────────────────────────────────────────────

def test_is_hybrid_keyword_hybrid():
    assert _is_hybrid("XLE Hybrid") is True

def test_is_hybrid_keyword_phev():
    assert _is_hybrid("Prime PHEV") is True

def test_is_hybrid_keyword_hev():
    assert _is_hybrid("HEV Sport") is True

def test_is_hybrid_keyword_prime():
    assert _is_hybrid("RAV4 Prime") is True

def test_is_hybrid_false():
    assert _is_hybrid("XLE Premium") is False

def test_is_hybrid_case_insensitive():
    assert _is_hybrid("HYBRID Limited") is True

def test_enrich_sets_is_hybrid_true():
    listing = _listing(trim="XLE Hybrid")
    enrich_listing(listing)
    assert listing["is_hybrid"] is True

def test_enrich_sets_is_hybrid_false():
    listing = _listing(trim="XLE Premium")
    enrich_listing(listing)
    assert listing["is_hybrid"] is False


# ── Value score boundaries ────────────────────────────────────────────────────

def test_score_is_between_0_and_100():
    listing = _listing()
    enriched = enrich_listing(listing)
    assert 0 <= enriched["value_score"] <= 100


def test_score_higher_for_lower_price():
    """Cheaper listing in same group should score higher."""
    group = [_listing(price=25000), _listing(price=35000)]
    avgs  = _compute_group_averages(group)
    cheap = _listing(price=25000)
    pricey = _listing(price=35000)
    enrich_listing(cheap,  avgs)
    enrich_listing(pricey, avgs)
    assert cheap["value_score"] > pricey["value_score"]


def test_score_higher_for_lower_mileage():
    low  = enrich_listing(_listing(mileage=5000))
    high = enrich_listing(_listing(mileage=75000))
    assert low["value_score"] > high["value_score"]


def test_score_higher_for_newer_year():
    newer = enrich_listing(_listing(year=2025))
    older = enrich_listing(_listing(year=2021))
    assert newer["value_score"] > older["value_score"]


def test_score_hybrid_bonus():
    gas    = enrich_listing(_listing(trim="XLE"))
    hybrid = enrich_listing(_listing(trim="XLE Hybrid"))
    assert hybrid["value_score"] - gas["value_score"] == 10.0


def test_score_shipping_penalty_none():
    no_ship = enrich_listing(_listing(shipping=None))
    with_ship = enrich_listing(_listing(shipping=1500))
    assert no_ship["value_score"] > with_ship["value_score"]


def test_score_shipping_penalty_zero():
    """Zero shipping should give full shipping points."""
    no_ship   = enrich_listing(_listing(shipping=None))
    zero_ship = enrich_listing(_listing(shipping=0))
    assert no_ship["value_score"] == zero_ship["value_score"]


def test_score_shipping_at_1500_gives_zero_points():
    """At $1500 shipping, shipping component should be 0."""
    listing = _listing(shipping=1500)
    avgs = _compute_group_averages([listing])
    score_at_1500 = _value_score(listing, avgs, current_year=2025)
    listing_no_ship = _listing(shipping=None)
    score_no_ship = _value_score(listing_no_ship, avgs, current_year=2025)
    assert score_no_ship - score_at_1500 == 10.0


def test_score_zero_mileage_full_points():
    """0 miles should give full mileage component (25 pts)."""
    low  = enrich_listing(_listing(mileage=0))
    high = enrich_listing(_listing(mileage=config.MAX_MILEAGE))
    assert low["value_score"] - high["value_score"] == 25.0


# ── Group averages ────────────────────────────────────────────────────────────

def test_group_averages_single_group():
    listings = [_listing(price=30000), _listing(price=40000)]
    avgs = _compute_group_averages(listings)
    key = ("Toyota", "RAV4", 2023)
    assert avgs[key] == 35000.0


def test_group_averages_multiple_groups():
    listings = [
        _listing(make="Toyota", model="RAV4",  year=2023, price=30000),
        _listing(make="Honda",  model="CR-V",  year=2022, price=28000),
    ]
    avgs = _compute_group_averages(listings)
    assert avgs[("Toyota", "RAV4", 2023)] == 30000.0
    assert avgs[("Honda",  "CR-V", 2022)] == 28000.0


def test_enrich_listings_computes_group_averages():
    """enrich_listings() should compute group averages before scoring."""
    listings = [_listing(price=25000), _listing(price=35000)]
    result = enrich_listings(listings)
    # Both should be scored; cheaper one should have higher score
    scores = [r["value_score"] for r in result]
    assert scores[0] > scores[1]
