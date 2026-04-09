"""
Rule-based filtering and scoring.

Runs on every listing before any LLM is called — fast, free, deterministic.
"""

import logging
from collections import defaultdict

import config
from utils.payment_calc import (
    estimate_monthly_payment,
    total_cost_of_ownership,
    price_per_mile as calc_price_per_mile,
)

log = logging.getLogger(__name__)

_HYBRID_KEYWORDS = {"hybrid", "hev", "phev", "prime"}

# Year range used for the age score component
_SCORE_MIN_YEAR = 2021
_SCORE_MAX_YEAR = 2025

# Model preference order (best → worst). Used for sorting and score bonus.
MODEL_PREFERENCE_ORDER = ["CR-V", "RAV4", "Forester", "Sportage"]

# Bonus points added to value_score for each model (spread = 6 pts).
_MODEL_PREFERENCE_BONUS: dict[str, float] = {
    "CR-V":     6.0,
    "RAV4":     4.0,
    "Forester": 2.0,
    "Sportage": 0.0,
}


# ── Filtering ─────────────────────────────────────────────────────────────────

def apply_filters(listings: list[dict]) -> list[dict]:
    """
    Remove listings that:
    - have no price
    - exceed MAX_PRICE
    - exceed MAX_MILEAGE
    - are outside MIN_YEAR / MAX_YEAR range
    Logs how many were removed and why.
    """
    removed = defaultdict(int)
    kept = []

    for listing in listings:
        price   = listing.get("price")
        mileage = listing.get("mileage")
        year    = listing.get("year")

        if not price or price <= 0:
            removed["no_price"] += 1
            continue
        if price > config.MAX_PRICE:
            removed["over_price"] += 1
            continue
        if mileage is not None and mileage > config.MAX_MILEAGE:
            removed["over_mileage"] += 1
            continue
        if year is not None and year < config.MIN_YEAR:
            removed["under_year"] += 1
            continue
        if year is not None and year > config.MAX_YEAR:
            removed["over_year"] += 1
            continue

        kept.append(listing)

    total_removed = sum(removed.values())
    if total_removed:
        reasons = ", ".join(f"{k}={v}" for k, v in removed.items())
        log.info(
            "Filtered out %d listings (%s) — %d remain",
            total_removed, reasons, len(kept),
        )
    else:
        log.info("No listings filtered — all %d passed", len(kept))

    return kept


# ── Enrichment ────────────────────────────────────────────────────────────────

def enrich_listings(listings: list[dict]) -> list[dict]:
    """
    Enrich all listings in-place, computing value scores that require
    group averages across the full dataset first.
    Returns the same list (mutated).
    """
    # Compute group average prices first (needed for price score component)
    group_averages = _compute_group_averages(listings)

    current_year = config.MAX_YEAR  # treat config max as 'current' for scoring
    enriched = [
        enrich_listing(listing, group_averages, current_year)
        for listing in listings
    ]
    return enriched


def enrich_listing(
    listing: dict,
    group_averages: dict | None = None,
    current_year: int = _SCORE_MAX_YEAR,
) -> dict:
    """
    Add computed fields to a listing dict:
      - monthly_estimated
      - total_with_shipping
      - price_per_mile
      - is_hybrid
      - age_years
      - value_score
    """
    price    = listing.get("price") or 0.0
    mileage  = listing.get("mileage")
    year     = listing.get("year")
    trim     = listing.get("trim") or ""
    shipping = listing.get("shipping")

    listing["monthly_estimated"] = estimate_monthly_payment(
        price,
        config.DOWN_PAYMENT,
        config.INTEREST_RATE,
        config.LOAN_TERM_MONTHS,
    )
    listing["total_with_shipping"] = total_cost_of_ownership(price, shipping)
    listing["price_per_mile"]      = calc_price_per_mile(price, mileage)
    listing["is_hybrid"]           = _is_hybrid(trim)
    listing["age_years"]           = (current_year - year) if year else None
    listing["value_score"]         = _value_score(
        listing, group_averages or {}, current_year
    )
    return listing


# ── Value score ───────────────────────────────────────────────────────────────

def _value_score(
    listing: dict,
    group_averages: dict,
    current_year: int,
) -> float:
    """
    Produce a 0–100 score. Higher is better.

    Components (base weights sum to 100, plus model preference bonus):
      35 — price vs group average (same make/model/year)
      25 — mileage (inverse linear, 0→25pts, 80k→0pts)
      20 — age (newer = better, MAX_YEAR→20pts, MIN_YEAR→0pts)
      10 — hybrid bonus
      10 — shipping penalty (0/None→10pts, $1500+→0pts)
       6 — model preference bonus (CR-V=6, RAV4=4, Forester=2, Sportage=0)
    """
    price    = listing.get("price") or 0.0
    mileage  = listing.get("mileage")
    year     = listing.get("year")
    shipping = listing.get("shipping")

    # ── Price component (35 pts) ──────────────────────────────────────────────
    group_key = (listing.get("make"), listing.get("model"), year)
    avg_price = group_averages.get(group_key)
    if avg_price and avg_price > 0:
        # Positive pct_diff means this listing is CHEAPER than average
        pct_diff = (avg_price - price) / avg_price * 100
        pct_diff = max(-30.0, min(30.0, pct_diff))   # cap ±30%
        # Map [-30, +30] → [0, 35]
        price_score = ((pct_diff + 30) / 60) * 35
    else:
        price_score = 17.5  # neutral when no group data

    # ── Mileage component (25 pts) ────────────────────────────────────────────
    if mileage is None:
        mileage_score = 12.5  # neutral
    else:
        mileage_score = max(0.0, 25.0 * (1 - mileage / config.MAX_MILEAGE))

    # ── Age component (20 pts) ────────────────────────────────────────────────
    year_range = _SCORE_MAX_YEAR - _SCORE_MIN_YEAR  # 4
    if year is None:
        age_score = 10.0
    else:
        clamped = max(_SCORE_MIN_YEAR, min(_SCORE_MAX_YEAR, year))
        age_score = ((clamped - _SCORE_MIN_YEAR) / year_range) * 20

    # ── Hybrid bonus (10 pts) ─────────────────────────────────────────────────
    hybrid_score = 10.0 if listing.get("is_hybrid") else 0.0

    # ── Shipping penalty (10 pts) ─────────────────────────────────────────────
    if shipping is None or shipping <= 0:
        shipping_score = 10.0
    else:
        shipping_score = max(0.0, 10.0 * (1 - shipping / 1500))

    # ── Model preference bonus (up to 6 pts) ─────────────────────────────────
    model_score = _MODEL_PREFERENCE_BONUS.get(listing.get("model") or "", 0.0)

    total = price_score + mileage_score + age_score + hybrid_score + shipping_score + model_score
    return round(min(100.0, max(0.0, total)), 2)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_hybrid(trim: str) -> bool:
    trim_lower = trim.lower()
    return any(kw in trim_lower for kw in _HYBRID_KEYWORDS)


def _compute_group_averages(listings: list[dict]) -> dict:
    """
    Return a dict mapping (make, model, year) → average price
    across all listings in the dataset.
    """
    groups: dict[tuple, list[float]] = defaultdict(list)
    for listing in listings:
        price = listing.get("price")
        if price:
            key = (listing.get("make"), listing.get("model"), listing.get("year"))
            groups[key].append(price)
    return {key: sum(prices) / len(prices) for key, prices in groups.items()}
