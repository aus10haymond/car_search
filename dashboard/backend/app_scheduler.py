"""
In-process async scheduler for Autospy.

Runs a background asyncio task that polls every 60 s and fires a full
search+email job when the configured interval has elapsed.  State is held in
module-level variables (reset on process restart); persistent config
(enabled, interval, profile_ids) lives in dashboard_settings.json.

Lifecycle is managed by the FastAPI lifespan handler in app.py:
    startup()  → reads persisted config, starts loop if enabled
    shutdown() → cancels the loop task cleanly
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# ── Module-level state (in-memory only) ───────────────────────────────────────
_task: "asyncio.Task | None" = None
_next_run_at: "datetime | None" = None
_last_run_at: "str | None" = None   # ISO-8601, populated from DB on startup
_last_job_id: "str | None" = None
_last_status: "str | None" = None   # "complete" | "failed" | "cancelled"


# ── Public API ─────────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return current scheduler state as a plain dict (safe to serialise to JSON)."""
    from dashboard.backend.job_manager import get_job

    running_job = None
    if _last_job_id:
        job = get_job(_last_job_id)
        if job and job.status in ("pending", "running"):
            running_job = {
                "job_id":     job.job_id,
                "status":     job.status,
                "started_at": job.started_at,
            }

    return {
        "enabled":        _is_enabled(),
        "interval_hours": _get_interval(),
        "profile_ids":    _get_profile_ids(),
        "next_run_at":    _next_run_at.isoformat() if _next_run_at else None,
        "last_run_at":    _last_run_at,
        "last_job_id":    _last_job_id,
        "last_status":    _last_status,
        "running_job":    running_job,
        "task_alive":     _task is not None and not _task.done(),
    }


async def startup() -> None:
    """
    Called by the FastAPI lifespan on backend start.
    Reads last-run time from the DB so the next-run calculation is accurate
    after a restart, then starts the loop if the schedule is enabled.
    """
    global _last_run_at

    try:
        from storage import history_db
        history_db.init_db()
        runs = history_db.get_history_summary()
        if runs:
            _last_run_at = runs[0]["run_at"]
    except Exception as exc:
        log.warning("Scheduler: could not read run history from DB: %s", exc)

    if _is_enabled():
        _schedule_next()
        _spawn_task()
        log.info(
            "Scheduler: auto-started (interval=%dh, next=%s)",
            _get_interval(),
            _next_run_at.isoformat() if _next_run_at else "?",
        )
    else:
        log.debug("Scheduler: disabled — not starting loop")


async def shutdown() -> None:
    """Cancel the background loop and wait for it to exit cleanly."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None


async def apply_settings(enabled: bool, interval_hours: int, profile_ids: list[str]) -> None:
    """
    Persist new schedule settings then restart the loop so changes take effect
    immediately without a backend restart.
    """
    from dashboard.backend import settings_store

    settings_store.save({
        "schedule_enabled":        enabled,
        "schedule_interval_hours": interval_hours,
        "schedule_profile_ids":    profile_ids,
    })

    await shutdown()

    if enabled:
        _schedule_next()
        _spawn_task()
        log.info(
            "Scheduler: (re)started — interval=%dh profiles=%s next=%s",
            interval_hours,
            profile_ids if profile_ids else "all",
            _next_run_at.isoformat() if _next_run_at else "?",
        )
    else:
        log.info("Scheduler: disabled")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    from dashboard.backend import settings_store
    return bool(settings_store.get("schedule_enabled"))


def _get_interval() -> int:
    from dashboard.backend import settings_store
    return int(settings_store.get("schedule_interval_hours") or 24)


def _get_profile_ids() -> list[str]:
    from dashboard.backend import settings_store
    return list(settings_store.get("schedule_profile_ids") or [])


def _schedule_next() -> None:
    """
    Compute and store the next fire time.

    If there is run history, schedules relative to the last run so drift does
    not accumulate across restarts.  Missed intervals are skipped forward.
    A minimum 5-minute delay after startup prevents an immediate fire when the
    backend restarts mid-cycle.
    """
    global _next_run_at
    interval  = timedelta(hours=_get_interval())
    now       = datetime.now(timezone.utc)
    min_delay = timedelta(minutes=5)

    if _last_run_at:
        try:
            last = datetime.fromisoformat(_last_run_at.replace("Z", "+00:00"))
            candidate = last + interval
            while candidate <= now:          # skip any missed intervals
                candidate += interval
            _next_run_at = max(candidate, now + min_delay)
            return
        except Exception:
            pass

    # No history or parse error — just wait one full interval
    _next_run_at = now + interval


def _spawn_task() -> None:
    global _task
    _task = asyncio.ensure_future(_run_loop())


async def _run_loop() -> None:
    """Poll every 60 s; fire a job when next_run_at is reached."""
    global _next_run_at, _last_run_at, _last_job_id, _last_status

    log.info(
        "Scheduler loop started — next run at %s",
        _next_run_at.isoformat() if _next_run_at else "?",
    )

    try:
        while True:
            await asyncio.sleep(60)

            if not _is_enabled():
                log.info("Scheduler: disabled — loop exiting")
                break

            if _next_run_at and datetime.now(timezone.utc) >= _next_run_at:
                log.info("Scheduler: firing scheduled run")
                try:
                    job_id, status = await _fire_and_wait()
                    _last_job_id = job_id
                    _last_run_at = datetime.now(timezone.utc).isoformat()
                    _last_status = status
                    log.info("Scheduler: job %s finished — %s", job_id, status)
                except Exception as exc:
                    log.error("Scheduler: job raised an exception: %s", exc)
                    _last_status = "error"

                _next_run_at = datetime.now(timezone.utc) + timedelta(hours=_get_interval())
                log.info("Scheduler: next run at %s", _next_run_at.isoformat())

    except asyncio.CancelledError:
        log.info("Scheduler loop cancelled")
        raise


async def _fire_and_wait() -> tuple[str, str]:
    """Spawn main.py as a subprocess job and block until it exits."""
    from dashboard.backend.job_manager import create_job, launch_job, get_job, RunOptions

    profile_ids = _get_profile_ids()
    options     = RunOptions(
        profile_ids=profile_ids,
        dry_run=False,
        no_llm=False,
        backend=None,
        force_email=False,
        no_email=False,
        debug=False,
    )
    job = create_job(profile_ids, options)
    await launch_job(job.job_id)    # blocks until subprocess exits
    finished = get_job(job.job_id)
    return job.job_id, (finished.status if finished else "unknown")
