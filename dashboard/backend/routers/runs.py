"""
Runs router — job creation, SSE log streaming, status, email preview, cancel,
and resend-last-email.
"""

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.backend.job_manager import (
    RunOptions,
    create_job,
    get_job,
    launch_job,
    cancel_job,
    iter_logs,
    list_jobs,
)

_PROFILES_YAML = Path(__file__).parent.parent.parent.parent / "profiles.yaml"

router = APIRouter(prefix="/runs", tags=["runs"])


# ── Request / response models ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    profile_ids:  list[str] = []
    dry_run:      bool = False
    no_llm:       bool = False
    backend:      Optional[str] = None   # "ollama" | "api" | None
    force_email:  bool = False
    no_email:     bool = False
    debug:        bool = False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("")
async def start_run(req: RunRequest, background_tasks: BackgroundTasks):
    """Create and start a run job. Returns immediately with a job_id."""
    if req.backend and req.backend not in ("ollama", "api", "cerebras"):
        raise HTTPException(422, "backend must be 'ollama', 'api', 'cerebras', or null")

    active = [j for j in list_jobs() if j.status in ("pending", "running")]
    if active:
        raise HTTPException(409, f"A run is already in progress (job_id={active[0].job_id})")

    options = RunOptions(
        profile_ids=req.profile_ids,
        dry_run=req.dry_run,
        no_llm=req.no_llm,
        backend=req.backend,
        force_email=req.force_email,
        no_email=req.no_email,
        debug=req.debug,
    )
    job = create_job(req.profile_ids, options)
    background_tasks.add_task(launch_job, job.job_id)
    return {"job_id": job.job_id}


@router.get("/{job_id}/stream")
async def stream_logs(job_id: str):
    """
    SSE stream of log lines for a job.

    Each event: `data: <JSON>\n\n`
    Log line:   {"ts": "HH:MM:SS", "level": "INFO", "msg": "..."}
    Terminal:   {"type": "done", "status": "complete"|"failed"|"cancelled", "exit_code": N}
    Error:      {"type": "error", "msg": "..."}
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    async def event_stream():
        async for event in iter_logs(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{job_id}/status")
def get_status(job_id: str):
    """Current job status and metadata."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "job_id":       job.job_id,
        "status":       job.status,
        "started_at":   job.started_at,
        "finished_at":  job.finished_at,
        "profile_ids":  job.profile_ids,
        "exit_code":    job.exit_code,
    }


@router.get("/{job_id}/email-preview")
def email_preview(job_id: str):
    """
    Return the generated email HTML for a completed dry-run job.

    Only available after a `dry_run: true` run finishes successfully.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.preview_html_path:
        raise HTTPException(400, "This job was not a dry run — no preview available")
    if job.status not in ("complete", "failed"):
        raise HTTPException(400, f"Job has not finished yet (status: {job.status})")

    path = Path(job.preview_html_path)
    if not path.exists():
        raise HTTPException(
            404,
            "Preview file not found. The run may have failed before reaching "
            "the email build phase — check the job logs.",
        )
    return {"html": path.read_text(encoding="utf-8")}


class ResendRequest(BaseModel):
    profile_ids: list[str] = []  # empty = all profiles


@router.post("/resend-email")
def resend_last_email(req: ResendRequest):
    """
    Rebuild and resend the email from the most recently stored run for each
    requested profile. No scraping or LLM analysis is performed — uses the
    listings saved in the database from the last run.
    """
    from profiles import load_profiles
    from storage import history_db
    from analysis.llm import LLMResult
    from notifications.email_alert import build_email_html, send_summary

    try:
        all_profiles = load_profiles(str(_PROFILES_YAML))
    except Exception as exc:
        raise HTTPException(500, f"Failed to load profiles: {exc}")

    profiles = (
        [p for p in all_profiles if p.profile_id in req.profile_ids]
        if req.profile_ids else all_profiles
    )
    if not profiles:
        raise HTTPException(404, "No matching profiles found")

    history_db.init_db()
    results = []

    for profile in profiles:
        run_id = history_db.get_last_run_id_for_profile(profile.profile_id)
        if not run_id:
            results.append({
                "profile_id":    profile.profile_id,
                "profile_label": profile.label,
                "sent":          False,
                "error":         "No previous run found for this profile",
            })
            continue

        listings = history_db.get_listings_for_run(run_id, profile.profile_id)
        if not listings:
            results.append({
                "profile_id":    profile.profile_id,
                "profile_label": profile.label,
                "sent":          False,
                "error":         "No listings stored for the last run",
            })
            continue

        # Restore the stored LLM analysis for this profile (if any)
        stored_llm = history_db.get_profile_llm_analysis(profile.profile_id)
        if stored_llm:
            llm_result = LLMResult(
                analysis=stored_llm["analysis"],
                backend_used=stored_llm["backend_used"] or "none",
                model_used=stored_llm["model_used"] or "",
                tokens_used=None,
                latency_ms=0,
                error=None,
                top_pick_vins=stored_llm["top_pick_vins"],
            )
        else:
            llm_result = LLMResult(
                analysis=None,
                backend_used="none",
                model_used="",
                tokens_used=None,
                latency_ms=0,
                error="no stored analysis",
            )

        trends = history_db.get_model_price_trends(days=180, vehicles=profile.vehicles)

        email_html = build_email_html(
            listings, llm_result, [],
            trends=trends, new_vins=set(),
            profile_label=profile.label,
            show_financing=profile.show_financing,
            down_payment=profile.down_payment,
            num_vehicles=len(profile.vehicles),
        )

        sent = send_summary(
            listings, llm_result, [],
            trends=trends, csv_path=None, force=True,
            new_vins=set(),
            email_to=profile.email_to,
            profile_label=profile.label,
            show_financing=profile.show_financing,
            down_payment=profile.down_payment,
            num_vehicles=len(profile.vehicles),
            pre_built_html=email_html,
        )

        results.append({
            "profile_id":    profile.profile_id,
            "profile_label": profile.label,
            "sent":          sent,
            "error":         None if sent else "Failed to send — check Gmail OAuth credentials",
        })

    return {"results": results}


@router.delete("/{job_id}")
async def cancel(job_id: str):
    """Send a terminate signal to a running job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(400, f"Cannot cancel a job with status '{job.status}'")
    ok = await cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "Process not running or already finished")
    return {"job_id": job_id, "status": "cancelled"}
