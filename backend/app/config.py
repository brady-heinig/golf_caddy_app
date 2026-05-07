from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_api_key: str | None
    cors_allow_origins: list[str]


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required (Supabase Postgres). "
            "Example: postgresql://USER:PASSWORD@HOST:5432/postgres"
        )

    cors = os.environ.get(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    cors_allow_origins = [o.strip() for o in cors.split(",") if o.strip()]

    return Settings(
        database_url=database_url,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        cors_allow_origins=cors_allow_origins,
    )

