"""Dependency-injection helpers for FastAPI route handlers."""

from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache

from psycopg_pool import ConnectionPool

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def get_pool() -> ConnectionPool:
    """Process-wide connection pool, opened once on first request.

    Replaces the old connect-per-request path: TCP + auth + ``SET search_path``
    were paid on every hit (including the 2.5s watchlist-spot poll). Under the
    Docker cutover this matters more — connection setup now crosses the VM
    boundary to host.docker.internal.
    """
    settings = get_settings()
    return ConnectionPool(
        settings.db_dsn(),
        min_size=int(os.getenv("UW_SCAN_DB_POOL_MIN", "2")),
        max_size=int(os.getenv("UW_SCAN_DB_POOL_MAX", "10")),
        open=True,
    )


def get_repo() -> Generator[Repository, None, None]:
    """Borrow a pooled connection for the request; return it on exit.

    ``pool.connection()`` commits on clean exit / rolls back on exception, then
    hands the connection back — Repository's own write commits are unaffected.
    """
    with get_pool().connection() as conn:
        yield Repository(conn, schema=get_settings().db_schema)


def get_uw_client() -> Generator[UwClient, None, None]:
    """Per-request UW client. Cheap to construct (httpx.Client init)."""
    settings = get_settings()
    client = UwClient(api_key=settings.api_key.get_secret_value())
    try:
        yield client
    finally:
        client.close()


def get_external_api_recorder() -> Generator[ExternalApiRequestRecorder, None, None]:
    settings = get_settings()
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    try:
        yield recorder
    finally:
        recorder.close()
