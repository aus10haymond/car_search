"""
FastAPI application factory for the Carvana Tracker dashboard backend.

Dev:
    uvicorn dashboard.backend.app:app --reload --host 127.0.0.1 --port 8000

Prod (after npm run build):
    uvicorn dashboard.backend.app:app --host 127.0.0.1 --port 8000
    (React dist/ is served as static files from the same process)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.backend.routers import (
    docs,
    history,
    profiles,
    runs,
    settings,
    setup,
)

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    application = FastAPI(
        title="Carvana Tracker Dashboard",
        description="Admin dashboard API for the Carvana car search tracker.",
        version="0.1.0",
        # Move built-in Swagger UI away from /docs so the vehicle reference
        # docs router can use that prefix as specified in the plan.
        docs_url="/api-docs",
        redoc_url="/api-redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # In dev the React app runs on :5173 and proxies API calls via vite.config.ts.
    # The broad allow_origins list covers both dev and any local variations.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            # Tauri v2 webview origins (WebView2 on Windows / WKWebView on macOS)
            "http://tauri.localhost",
            "tauri://localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    application.include_router(profiles.router)
    application.include_router(runs.router)
    application.include_router(history.router)
    application.include_router(setup.router)
    application.include_router(settings.router)
    application.include_router(docs.router)

    # ── Health ────────────────────────────────────────────────────────────────
    @application.get("/ping", tags=["health"])
    def ping():
        return {"status": "ok"}

    # ── Static files (production only) ────────────────────────────────────────
    # Only mount when the frontend has been built.  In dev, Vite serves on :5173.
    if _FRONTEND_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles
        application.mount(
            "/",
            StaticFiles(directory=str(_FRONTEND_DIST), html=True),
            name="static",
        )

    return application


app = create_app()
