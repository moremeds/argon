"""Dependency-injection helpers for FastAPI route handlers."""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def get_repo() -> Generator[Repository, None, None]:
    settings = get_settings()
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()
