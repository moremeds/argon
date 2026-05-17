"""Gold router — /api/gold/gauge + /api/gold/inputs."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def app_with_seed() -> TestClient:
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        base = date(2025, 1, 1)
        for i in range(400):
            d = base + timedelta(days=i)
            repo.insert_macro_series_daily(
                "DFII10",
                d,
                Decimal(str(2.0 - i * 0.003)),
                datetime.combine(d, datetime.min.time(), tzinfo=UTC),
                None,
                "FRED",
                None,
            )

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


def test_gauge_endpoint_returns_current_corr_history(
    app_with_seed: TestClient,
) -> None:
    response = app_with_seed.get("/api/gold/gauge")
    assert response.status_code == 200
    body = response.json()
    assert "current" in body
    assert "state" in body["current"]
    assert isinstance(body["history_252d"], list)


def test_inputs_endpoint_returns_series_points(app_with_seed: TestClient) -> None:
    response = app_with_seed.get("/api/gold/inputs/DFII10?from=2025-01-01")
    assert response.status_code == 200
    body = response.json()
    assert body["series_id"] == "DFII10"
    assert len(body["points"]) > 100


def test_inputs_endpoint_unknown_series_returns_empty(
    app_with_seed: TestClient,
) -> None:
    response = app_with_seed.get("/api/gold/inputs/NOPE")
    assert response.status_code == 200
    assert response.json()["points"] == []
