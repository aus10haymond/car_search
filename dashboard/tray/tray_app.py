"""
Carvana Tracker — system tray helper (Phase 1).

Starts the FastAPI backend (uvicorn) and places a tray icon in the system
notification area.  Double-click or select "Open Dashboard" to launch the
browser.  "Quit" terminates the backend and removes the tray icon.

Usage (from the project root):
    python dashboard/tray/tray_app.py

Production (after `cd dashboard/frontend && npm run build`):
    The React app is served by FastAPI at http://localhost:8000 — no Vite
    dev server needed.

Dev (Vite on :5173):
    Set DASHBOARD_URL env var before launching:
        set DASHBOARD_URL=http://localhost:5173 && python dashboard/tray/tray_app.py
"""

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

# ── Configuration ──────────────────────────────────────────────────────────────

_HERE         = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent.parent  # dashboard/tray/../../  = repo root

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
BACKEND_URL  = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

# In dev, point DASHBOARD_URL at the Vite dev server; in prod it's the same
# origin as the backend.
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", BACKEND_URL)

ICON_PATH = _HERE / "icon.png"

# ── Backend process ────────────────────────────────────────────────────────────

_backend_proc: subprocess.Popen | None = None


def _start_backend() -> subprocess.Popen:
    """Spawn uvicorn in a subprocess; stdout/stderr inherited (visible in terminal)."""
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "dashboard.backend.app:app",
            "--host", BACKEND_HOST,
            "--port", str(BACKEND_PORT),
        ],
        cwd=str(_PROJECT_ROOT),
    )


def _wait_for_backend(timeout: float = 10.0) -> bool:
    """Poll /ping until the backend is accepting connections."""
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{BACKEND_URL}/ping", timeout=1)
            return True
        except Exception:
            time.sleep(0.4)
    return False


# ── Tray callbacks ─────────────────────────────────────────────────────────────

def _open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    webbrowser.open(DASHBOARD_URL)


def _quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    global _backend_proc
    if _backend_proc and _backend_proc.poll() is None:
        _backend_proc.terminate()
        try:
            _backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _backend_proc.kill()
    _backend_proc = None
    icon.stop()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    global _backend_proc

    # Graceful Ctrl-C in terminal
    signal.signal(signal.SIGINT, lambda *_: _quit_app(tray, None))

    # Start backend
    print(f"[tray] Starting backend on {BACKEND_URL} …")
    _backend_proc = _start_backend()

    ready = _wait_for_backend()
    if not ready:
        print("[tray] WARNING: backend did not become ready in time — opening browser anyway")
    else:
        print("[tray] Backend ready.")

    # Load icon
    if ICON_PATH.exists():
        icon_image = Image.open(ICON_PATH)
    else:
        # Fallback: plain indigo square
        icon_image = Image.new("RGBA", (64, 64), (99, 102, 241, 255))

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", _open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit_app),
    )

    global tray
    tray = pystray.Icon(
        name="carvana_tracker",
        icon=icon_image,
        title="Carvana Tracker",
        menu=menu,
    )

    # Open the browser automatically on first launch
    webbrowser.open(DASHBOARD_URL)

    print("[tray] Tray icon active. Double-click or use menu to open dashboard.")
    tray.run()


if __name__ == "__main__":
    main()
