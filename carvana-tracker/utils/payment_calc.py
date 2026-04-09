"""
Pure financial calculation functions.
All functions are stateless and side-effect-free.
"""


def estimate_monthly_payment(
    price: float,
    down: float,
    apr_pct: float,
    months: int,
) -> float:
    """
    Standard amortizing loan formula.
    Returns 0.0 if principal <= 0.
    """
    principal = price - down
    if principal <= 0:
        return 0.0
    monthly_rate = (apr_pct / 100) / 12
    if monthly_rate == 0:
        return round(principal / months, 2)
    payment = (
        principal
        * (monthly_rate * (1 + monthly_rate) ** months)
        / ((1 + monthly_rate) ** months - 1)
    )
    return round(payment, 2)


def total_cost_of_ownership(price: float, shipping: float | None) -> float:
    """Price + shipping. Treats None shipping as 0."""
    return price + (shipping or 0.0)


def price_per_mile(price: float, mileage: int | None) -> float | None:
    """Returns None if mileage is None or 0."""
    if not mileage:
        return None
    return round(price / mileage, 4)


def depreciation_estimate(
    price: float,
    year: int,
    current_year: int = 2025,
) -> float:
    """
    ESTIMATE ONLY — not financial advice.
    Rough remaining value after 5 years using a 15% declining-balance model.
    Applied from `year` forward 5 years, capped at the vehicle's current age.
    """
    age = max(0, current_year - year)
    years_remaining = max(0, 5 - age)
    remaining_value = price * (0.85 ** years_remaining)
    return round(remaining_value, 2)
