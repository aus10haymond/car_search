"""
History router — wraps storage.history_db for the dashboard.
"""

from fastapi import APIRouter, HTTPException, Query
from storage import history_db
from profiles import load_profiles

router = APIRouter(prefix="/history", tags=["history"])

_PROFILES_YAML = __import__("pathlib").Path(__file__).parent.parent.parent.parent / "profiles.yaml"


@router.get("/runs")
def get_runs():
    """All runs ordered by date descending."""
    history_db.init_db()
    return history_db.get_history_summary()


@router.get("/stats")
def get_stats():
    """All-time aggregate stats."""
    history_db.init_db()
    return history_db.get_all_time_stats()


@router.get("/trends")
def get_trends(
    days: int = Query(default=60, ge=1, le=365),
    profile_id: str | None = Query(default=None),
):
    """
    Price trend data per make/model over the past N days.

    If profile_id is provided, the results are scoped to the vehicles in that
    profile (same vehicles shown in the profile's email table).
    """
    history_db.init_db()

    vehicles: list[tuple[str, str]] | None = None
    if profile_id:
        try:
            profiles = load_profiles(str(_PROFILES_YAML))
        except Exception as exc:
            raise HTTPException(500, f"Failed to load profiles: {exc}")
        match = next((p for p in profiles if p.profile_id == profile_id), None)
        if not match:
            raise HTTPException(404, f"Profile '{profile_id}' not found")
        vehicles = match.vehicles

    return history_db.get_model_price_trends(days=days, vehicles=vehicles)
