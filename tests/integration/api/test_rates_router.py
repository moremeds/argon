"""Rates router — /api/rates/snapshot."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.routers.rates import _mark_stale_snapshot_sources
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.models import (
    RatesCurvePoint,
    RatesCurveSection,
    RatesScorecard,
    RatesSnapshotResponse,
    RatesSourceFreshness,
    RatesSummaryTile,
    RatesSynthesisPanel,
)
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def rates_client() -> TestClient:
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


def _snapshot() -> RatesSnapshotResponse:
    return RatesSnapshotResponse(
        as_of=date(2026, 5, 20),
        computed_at=datetime(2026, 5, 21, 1, 2, 3, tzinfo=UTC),
        summary=[
            RatesSummaryTile(label="10Y", value=4.52, unit="%"),
            RatesSummaryTile(label="2s10s", value=-44.0, unit="bps"),
        ],
        curve=RatesCurveSection(
            points=[
                RatesCurvePoint(
                    tenor="10Y",
                    series_id="DGS10",
                    value=4.52,
                    delta_1d_bps=3.0,
                    obs_date=date(2026, 5, 20),
                )
            ]
        ),
        scorecard=RatesScorecard(composite_score=-0.15),
        synthesis=RatesSynthesisPanel(
            duration_view="Live FRED curve snapshot.",
            curve_view="Curve data available.",
            risks=[],
        ),
        source_freshness=[
            RatesSourceFreshness(
                id="DGS10",
                label="10Y Treasury",
                latest_obs_date=date(2026, 5, 20),
                last_seen_at=datetime(2026, 5, 21, 1, 2, 3, tzinfo=UTC),
                status="ok",
            )
        ],
    )


def test_rates_snapshot_returns_latest_persisted_payload(
    rates_client: TestClient,
) -> None:
    settings = _test_settings()
    snapshot = _snapshot()
    payload = snapshot.model_dump(mode="json")
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        repo.insert_rates_snapshot(
            snapshot_date=snapshot.as_of,
            computed_at=snapshot.computed_at,
            payload=payload,
            source_freshness=payload["source_freshness"],
        )
        conn.commit()

    response = rates_client.get("/api/rates/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-05-20"
    assert body["summary"][0]["label"] == "10Y"
    assert body["curve"]["points"][0]["series_id"] == "DGS10"
    assert body["source_freshness"][0]["id"] == "DGS10"


def test_rates_snapshot_returns_404_before_first_compute(
    rates_client: TestClient,
) -> None:
    response = rates_client.get("/api/rates/snapshot")

    assert response.status_code == 404
    assert response.json()["detail"] == "rates snapshot not computed"


def test_stale_rates_snapshot_marks_live_sources_stale() -> None:
    snapshot = _snapshot()

    stale = _mark_stale_snapshot_sources(
        snapshot,
        now=datetime(2026, 5, 23, 14, 2, 4, tzinfo=UTC),
    )

    assert stale.source_freshness[0].status == "stale"
    assert "scheduled FRED refresh" in stale.synthesis.risks[-1]
