"""Dependency-injection helpers for FastAPI route handlers."""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
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
