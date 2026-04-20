"""
Runs router — job creation, SSE log streaming, status, email preview, cancel.
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
)

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
    if req.backend and req.backend not in ("ollama", "api"):
        raise HTTPException(422, "backend must be 'ollama', 'api', or null")

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
