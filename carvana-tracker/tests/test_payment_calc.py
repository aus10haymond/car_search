import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.payment_calc import (
    estimate_monthly_payment,
    total_cost_of_ownership,
    price_per_mile,
    depreciation_estimate,
)


# ── estimate_monthly_payment ───────────────────────────────────────────────────

def test_payment_standard():
    """Sanity check against a known amortization value."""
    pmt = estimate_monthly_payment(30000, 3000, 7.5, 60)
    # principal=27000, rate=0.625%/mo — expected ~$540/mo
    assert 530 < pmt < 560


def test_payment_zero_principal():
    """Down payment >= price → 0."""
    assert estimate_monthly_payment(3000, 3000, 7.5, 60) == 0.0
    assert estimate_monthly_payment(1000, 5000, 7.5, 60) == 0.0


def test_payment_zero_apr():
    """Zero APR → simple division."""
    pmt = estimate_monthly_payment(12000, 0, 0.0, 60)
    assert pmt == round(12000 / 60, 2)


def test_payment_returns_float():
    pmt = estimate_monthly_payment(25000, 2000, 6.0, 48)
    assert isinstance(pmt, float)


# ── total_cost_of_ownership ───────────────────────────────────────────────────

def test_tco_with_shipping():
    assert total_cost_of_ownership(30000, 500) == 30500.0


def test_tco_none_shipping():
    assert total_cost_of_ownership(30000, None) == 30000.0


def test_tco_zero_shipping():
    assert total_cost_of_ownership(30000, 0) == 30000.0


# ── price_per_mile ────────────────────────────────────────────────────────────

def test_ppm_normal():
    result = price_per_mile(30000, 50000)
    assert result == round(30000 / 50000, 4)


def test_ppm_zero_mileage():
    assert price_per_mile(30000, 0) is None


def test_ppm_none_mileage():
    assert price_per_mile(30000, None) is None


def test_ppm_returns_float():
    result = price_per_mile(25000, 40000)
    assert isinstance(result, float)


# ── depreciation_estimate ─────────────────────────────────────────────────────

def test_depreciation_new_car():
    """2025 car evaluated in 2025 → 5 years of depreciation applied."""
    val = depreciation_estimate(30000, 2025, current_year=2025)
    expected = round(30000 * (0.85 ** 5), 2)
    assert val == expected


def test_depreciation_4_year_old_car():
    """2021 car in 2025 → 1 year of depreciation remaining (5 - 4 = 1)."""
    val = depreciation_estimate(25000, 2021, current_year=2025)
    expected = round(25000 * (0.85 ** 1), 2)
    assert val == expected


def test_depreciation_fully_depreciated():
    """Car older than 5 years → 0 years remaining → price unchanged."""
    val = depreciation_estimate(20000, 2018, current_year=2025)
    assert val == 20000.0


def test_depreciation_returns_float():
    val = depreciation_estimate(30000, 2023, current_year=2025)
    assert isinstance(val, float)
