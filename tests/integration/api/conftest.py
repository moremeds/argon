"""FastAPI TestClient fixture wired to the isolated test DB.

Without dependency_overrides on get_repo / get_settings, route handlers
would resolve through Settings.from_env() → developer's real DB. The
overrides point every request at the test DB the parent fixtures populate.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to point API client at working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture(autouse=True)
def _clear_stock_report_cache():
    """Isolate the (ticker, run_id) response cache between tests — otherwise a
    prior test's report could satisfy a later test reusing the same key."""
    from uw_scan.api.routers.stock import _report_cache_clear

    _report_cache_clear()
    yield
    _report_cache_clear()


@pytest.fixture
def client() -> TestClient:
    """TestClient with overrides; works without any DB seeding."""
    settings = _test_settings()
    app = create_app()

    def _override_settings() -> Settings:
        return settings

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_repo] = _override_repo
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
