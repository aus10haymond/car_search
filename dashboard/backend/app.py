"""
FastAPI application factory for the Autospy dashboard backend.

Dev:
    uvicorn dashboard.backend.app:app --reload --host 127.0.0.1 --port 8000

Prod (after npm run build):
    uvicorn dashboard.backend.app:app --host 127.0.0.1 --port 8000
    (React dist/ is served as static files from the same process)
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.backend.routers import (
    docs,
    history,
    profiles,
    runs,
    schedule,
    settings,
    setup,
    system,
    auth,
    portal,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Uvicorn's dictConfig sets propagate=False on its own loggers before the
    # lifespan runs, so root-logger handlers never see uvicorn records.
    # Re-attach our buffer handler directly to each uvicorn logger here,
    # after dictConfig has already done its work.
    import logging
    from dashboard.backend.routers.system import _bhandler
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _lgr = logging.getLogger(_name)
        if _bhandler not in _lgr.handlers:
            _lgr.addHandler(_bhandler)

    from dashboard.backend import app_scheduler
    await app_scheduler.startup()
    yield
    await app_scheduler.shutdown()

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
_PORTAL_DIST   = Path(__file__).parent.parent / "portal-dist"


def create_app() -> FastAPI:
    application = FastAPI(
        title="Autospy Dashboard",
        description="Admin dashboard API for Autospy.",
        version="0.1.0",
        lifespan=_lifespan,
        # Move built-in Swagger UI away from /docs so the vehicle reference
        # docs router can use that prefix as specified in the plan.
        docs_url="/api-docs",
        redoc_url="/api-redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            # Web portal dev server
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            # Tauri v2 webview origins (WebView2 on Windows / WKWebView on macOS)
            "http://tauri.localhost",
            "tauri://localhost",
            # ngrok public tunnel
            "https://sympathy-boggle-uncouth.ngrok-free.dev",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    # Desktop dashboard routes (no auth — localhost only)
    application.include_router(profiles.router)
    application.include_router(runs.router)
    application.include_router(history.router)
    application.include_router(schedule.router)
    application.include_router(setup.router)
    application.include_router(settings.router)
    application.include_router(docs.router)
    application.include_router(system.router)

    # Web portal routes (JWT-gated)
    application.include_router(auth.router)
    application.include_router(portal.router)

    # ── Health ────────────────────────────────────────────────────────────────
    @application.get("/ping", tags=["health"])
    def ping():
        return {"status": "ok"}

    # ── Static files (production only) ────────────────────────────────────────
    # Starlette routing conflict: an APIRouter at prefix /portal and a
    # StaticFiles mount at /portal fight for the same path — the router wins
    # and index.html never gets served.  Work-around: serve portal/index.html
    # explicitly for every SPA route and mount only /portal/assets separately.
    if _PORTAL_DIST.is_dir():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        _portal_index = str(_PORTAL_DIST / "index.html")

        _portal_dist_resolved = _PORTAL_DIST.resolve()

        @application.get("/portal", include_in_schema=False)
        @application.get("/portal/", include_in_schema=False)
        @application.get("/portal/{path:path}", include_in_schema=False)
        def _portal_spa(path: str = ""):
            # Resolve and guard against path traversal before serving any file.
            candidate = (_PORTAL_DIST / path).resolve()
            if str(candidate).startswith(str(_portal_dist_resolved)) and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(_portal_index)

        application.mount(
            "/portal/assets",
            StaticFiles(directory=str(_PORTAL_DIST / "assets")),
            name="portal-assets",
        )

    if _FRONTEND_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles
        application.mount(
            "/",
            StaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="static",
        )

    return application


app = create_app()
