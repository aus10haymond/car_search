"""
System management — backend log streaming and ngrok process control.

Endpoints:
  GET  /system/status        → running state for backend + ngrok
  POST /system/ngrok/start   → launch ngrok subprocess
  POST /system/ngrok/stop    → terminate ngrok subprocess
  GET  /system/backend/logs  → SSE stream of uvicorn log output
  GET  /system/ngrok/logs    → SSE stream of ngrok output
"""

import asyncio
import json
import logging
import os
import threading
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/system", tags=["system"])

# ── Backend log capture ───────────────────────────────────────────────────────
# A threading.Lock-guarded list of (seq, line) tuples; the handler is installed
# at import time so it captures everything from startup onward.

_blog_lock: threading.Lock = threading.Lock()
_blog_seq: int = 0
_blog_entries: list[tuple[int, str]] = []
_BLOG_MAX = 500


class _BufHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        global _blog_seq
        try:
            line = self.format(record)
            with _blog_lock:
                _blog_seq += 1
                _blog_entries.append((_blog_seq, line))
                if len(_blog_entries) > _BLOG_MAX:
                    del _blog_entries[:-_BLOG_MAX]
        except Exception:
            pass


_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
_bhandler = _BufHandler()
_bhandler.setFormatter(_fmt)
logging.getLogger().addHandler(_bhandler)

# ── ngrok subprocess management ───────────────────────────────────────────────

_nlock: threading.Lock = threading.Lock()
_nseq: int = 0
_nentries: list[tuple[int, str]] = []
_NMAX = 500

_ngrok_proc: Optional[asyncio.subprocess.Process] = None
_ngrok_drain_task: Optional[asyncio.Task] = None


def _nappend(line: str) -> None:
    global _nseq
    with _nlock:
        _nseq += 1
        _nentries.append((_nseq, line))
        if len(_nentries) > _NMAX:
            del _nentries[:-_NMAX]


def _ngrok_alive() -> bool:
    return _ngrok_proc is not None and _ngrok_proc.returncode is None


async def _drain_ngrok_output() -> None:
    if not _ngrok_proc or not _ngrok_proc.stdout:
        return
    try:
        async for raw in _ngrok_proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                _nappend(line)
    except Exception:
        pass
    _nappend("— ngrok process exited —")


def _get_ngrok_domain() -> str:
    try:
        from dashboard.backend import settings_store
        return settings_store.load().get("ngrok_domain", "sympathy-boggle-uncouth.ngrok-free.dev")
    except Exception:
        return "sympathy-boggle-uncouth.ngrok-free.dev"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
def system_status():
    return {
        "backend": {"running": True, "pid": os.getpid()},
        "ngrok":   {"running": _ngrok_alive(), "domain": _get_ngrok_domain()},
    }


@router.post("/ngrok/start")
async def ngrok_start():
    global _ngrok_proc, _ngrok_drain_task
    if _ngrok_alive():
        return {"status": "already_running"}
    domain = _get_ngrok_domain()
    _nappend(f"Starting ngrok → https://{domain} …")
    _ngrok_proc = await asyncio.create_subprocess_exec(
        "ngrok", "http",
        f"--domain={domain}",
        "--log", "stdout",
        "--log-format", "logfmt",
        "8000",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    _ngrok_drain_task = asyncio.create_task(_drain_ngrok_output())
    return {"status": "started", "domain": domain}


@router.post("/ngrok/stop")
async def ngrok_stop():
    global _ngrok_proc, _ngrok_drain_task
    if not _ngrok_alive():
        return {"status": "not_running"}
    _ngrok_proc.terminate()
    try:
        await asyncio.wait_for(_ngrok_proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        _ngrok_proc.kill()
    _ngrok_proc = None
    if _ngrok_drain_task and not _ngrok_drain_task.done():
        _ngrok_drain_task.cancel()
    _ngrok_drain_task = None
    _nappend("ngrok stopped.")
    return {"status": "stopped"}


@router.get("/backend/logs")
async def backend_logs():
    async def _stream():
        # Send the last 50 buffered lines first, then tail
        with _blog_lock:
            snapshot = list(_blog_entries)[-50:]
        for seq, line in snapshot:
            yield f"data: {json.dumps({'msg': line})}\n\n"
        last_seq = snapshot[-1][0] if snapshot else 0
        while True:
            await asyncio.sleep(0.5)
            with _blog_lock:
                new = [(s, l) for s, l in _blog_entries if s > last_seq]
            for seq, line in new:
                yield f"data: {json.dumps({'msg': line})}\n\n"
                last_seq = seq

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/ngrok/logs")
async def ngrok_logs():
    async def _stream():
        with _nlock:
            snapshot = list(_nentries)
        for seq, line in snapshot:
            yield f"data: {json.dumps({'msg': line})}\n\n"
        last_seq = snapshot[-1][0] if snapshot else 0
        while True:
            await asyncio.sleep(0.5)
            with _nlock:
                new = [(s, l) for s, l in _nentries if s > last_seq]
            for seq, line in new:
                yield f"data: {json.dumps({'msg': line})}\n\n"
                last_seq = seq

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
