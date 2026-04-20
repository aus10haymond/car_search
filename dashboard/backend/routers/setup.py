"""
Setup / health-check router.

GET  /setup/status              — structured health check for all components
POST /setup/install-playwright  — run `playwright install chromium`, SSE output
POST /setup/gmail-oauth         — run setup_gmail_oauth.py, SSE output
"""

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from dashboard.backend.setup_checks import run_setup_checks

router = APIRouter(prefix="/setup", tags=["setup"])

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@router.get("/status")
def get_status():
    """Full health check — Ollama, Anthropic, Gmail, Playwright, profiles."""
    return run_setup_checks()


@router.post("/install-playwright")
async def install_playwright():
    """Stream `playwright install chromium` output as SSE."""
    return StreamingResponse(
        _stream_command(
            sys.executable, "-m", "playwright", "install", "chromium"
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/gmail-oauth")
async def gmail_oauth():
    """Stream `python setup_gmail_oauth.py` output as SSE."""
    return StreamingResponse(
        _stream_command(
            sys.executable,
            str(_PROJECT_ROOT / "setup_gmail_oauth.py"),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_command(*args: str):
    """Async generator that spawns a subprocess and yields its output as SSE lines."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT),
        )
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                yield f"data: {json.dumps({'msg': line})}\n\n"

        await process.wait()
        yield f"data: {json.dumps({'type': 'done', 'exit_code': process.returncode})}\n\n"

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'msg': str(exc)})}\n\n"
