from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import load_settings
from .db import connect
from .migrate import run_migrations
from .routes_me import router as me_router
from .routes_rounds import router as rounds_router
from .routes_chat import router as chat_router
from .routes_course import router as course_router
from .routes_caddie_compat import router as caddie_compat_router
from .routes_caddie_api import router as caddie_api_router
from .repos import ensure_default_user


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="AI Caddie API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        # Auth has been removed; don't use credentialed CORS.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        conn = connect(settings.database_url)
        run_migrations(conn, Path(__file__).resolve().parent / "migrations")
        ensure_default_user(conn)
        conn.close()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(me_router, prefix="/api")
    app.include_router(rounds_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    # Important: caddie-compat endpoints intentionally overlap some legacy course routes
    # (e.g. /api/course/{id}/hole/{n}) but return richer payloads (metrics/weather/features).
    # Register compat first so it takes precedence.
    app.include_router(caddie_compat_router, prefix="/api")
    app.include_router(caddie_api_router, prefix="/api")
    app.include_router(course_router, prefix="/api")

    return app


app = create_app()

