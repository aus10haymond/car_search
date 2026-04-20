"""
In-memory job state for dashboard run tracking.

Jobs are not persisted — run history lives in SQLite via history_db. This
module only tracks live job progress and log output while the server is up.
"""

import asyncio
import os
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Literal

# Project root: dashboard/backend/job_manager.py → three parents up = car_search/
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Matches: "15:32:10 [INFO] module_name — message body"
_LOG_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+\S+\s+[—\-]\s+(.+)$")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class RunOptions:
    profile_ids: list[str] = field(default_factory=list)
    dry_run:     bool = False
    no_llm:      bool = False
    backend:     str | None = None   # "ollama" | "api" | None
    force_email: bool = False
    no_email:    bool = False
    debug:       bool = False


@dataclass
class Job:
    job_id:            str
    status:            Literal["pending", "running", "complete", "failed", "cancelled"]
    profile_ids:       list[str]
    options:           RunOptions
    started_at:        str                          # ISO 8601
    finished_at:       str | None = None
    exit_code:         int | None = None
    process:           asyncio.subprocess.Process | None = None
    log_lines:         list[dict] = field(default_factory=list)
    preview_html_path: str | None = None            # set if dry_run=True; path via tempfile.gettempdir()


# ── Module-level job store ────────────────────────────────────────────────────

_jobs: dict[str, Job] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def create_job(profile_ids: list[str], options: RunOptions) -> Job:
    """Create a job record and register it in the store. Does not start it."""
    job_id = str(uuid.uuid4())
    preview_path: str | None = None
    if options.dry_run:
        preview_path = os.path.join(tempfile.gettempdir(), f"preview_{job_id}.html")

    job = Job(
        job_id=job_id,
        status="pending",
        profile_ids=profile_ids,
        options=options,
        started_at=datetime.now(timezone.utc).isoformat(),
        preview_html_path=preview_path,
    )
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    return list(_jobs.values())


async def launch_job(job_id: str) -> None:
    """Spawn main.py as a subprocess, stream its output into job.log_lines."""
    job = _jobs.get(job_id)
    if not job:
        return

    cmd = [sys.executable, "main.py"]

    if job.options.profile_ids:
        cmd += ["--profile"] + job.options.profile_ids
    if job.options.dry_run and job.preview_html_path:
        cmd += ["--dry-run", "--preview-output", job.preview_html_path]
    elif job.options.dry_run:
        cmd += ["--dry-run"]
    if job.options.no_llm:
        cmd += ["--no-llm"]
    if job.options.backend:
        cmd += ["--backend", job.options.backend]
    if job.options.force_email:
        cmd += ["--email"]
    if job.options.no_email:
        cmd += ["--no-email"]
    if job.options.debug:
        cmd += ["--debug"]

    job.status = "running"

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        job.process = process

        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                job.log_lines.append(_parse_log_line(line))

        await process.wait()
        job.exit_code = process.returncode
        job.status = "complete" if process.returncode == 0 else "failed"

    except Exception as exc:
        job.log_lines.append({"ts": "", "level": "ERROR", "msg": str(exc)})
        job.status = "failed"
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()
        job.process = None


async def cancel_job(job_id: str) -> bool:
    """Send terminate signal to the running process. Returns True if terminated."""
    job = _jobs.get(job_id)
    if not job or job.process is None:
        return False
    try:
        job.process.terminate()
    except ProcessLookupError:
        pass  # already exited
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc).isoformat()
    return True


async def iter_logs(job_id: str) -> AsyncGenerator[dict, None]:
    """
    Async generator that yields all buffered log lines for a job, then continues
    yielding new lines as they arrive until the job finishes.

    Yields plain dicts — the router wraps each in an SSE envelope.
    """
    job = _jobs.get(job_id)
    if not job:
        yield {"type": "error", "msg": "Job not found"}
        return

    cursor = 0
    while True:
        # Drain any buffered lines
        while cursor < len(job.log_lines):
            yield job.log_lines[cursor]
            cursor += 1

        # Job finished — emit terminal event and stop
        if job.status in ("complete", "failed", "cancelled"):
            yield {"type": "done", "status": job.status, "exit_code": job.exit_code}
            return

        await asyncio.sleep(0.1)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_log_line(line: str) -> dict:
    m = _LOG_RE.match(line)
    if m:
        return {"ts": m.group(1), "level": m.group(2), "msg": m.group(3)}
    return {"ts": "", "level": "INFO", "msg": line}
