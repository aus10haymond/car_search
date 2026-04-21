"""
Schedule router — read and update the in-process async scheduler.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/schedule", tags=["schedule"])


class ScheduleRequest(BaseModel):
    enabled:        bool
    interval_hours: int       = Field(default=24, ge=1, le=8760)
    profile_ids:    list[str] = []   # empty list = run all profiles


@router.get("")
def get_schedule():
    """Return current scheduler status."""
    from dashboard.backend import app_scheduler
    return app_scheduler.get_status()


@router.post("")
async def update_schedule(req: ScheduleRequest):
    """Enable/disable or reconfigure the scheduler. Takes effect immediately."""
    from dashboard.backend import app_scheduler
    await app_scheduler.apply_settings(req.enabled, req.interval_hours, req.profile_ids)
    return app_scheduler.get_status()
