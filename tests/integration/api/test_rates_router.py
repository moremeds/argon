"""Rates router — /api/rates/snapshot."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

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
from uw_scan.worker.jobs.macro_policy_jobs import macro_fomc_statement_ingest_job
from uw_scan.worker.jobs.macro_state_jobs import macro_rates_state_job

from tests.integration.worker._macro_providers import _StatementProvider
from tests.integration.worker.test_macro_state_jobs import POLICY_AS_OF


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def rates_client(seeded_db_empty_cards) -> TestClient:
    # seeded_db_empty_cards drives the session migrate + per-test baseline
    # restore. We still need settings to wire the FastAPI dependency overrides.
    _ = seeded_db_empty_cards
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


# --- MC2 dual-read: the policy/rates domain state attached behind a flag -------------


def _client_with(settings: Settings) -> TestClient:
    app = create_app()

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repo] = _override_repo
    return TestClient(app)


def _seed_snapshot(settings: Settings) -> None:
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


def _seed_policy_rates_state(settings: Settings) -> None:
    macro_fomc_statement_ingest_job(
        dsn=settings.db_dsn(),
        provider_factory=_StatementProvider,
        observed_at=POLICY_AS_OF,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        result = macro_rates_state_job(
            Repository(conn, schema=settings.db_schema), as_of=POLICY_AS_OF
        )
    assert result.status == "ok", result.error_message


def test_snapshot_omits_the_domain_state_while_the_flag_is_off(
    seeded_db_empty_cards,
) -> None:
    settings = _test_settings()
    _seed_snapshot(settings)
    _seed_policy_rates_state(settings)

    body = _client_with(settings).get("/api/rates/snapshot").json()

    # A computed state exists; the flag alone decides whether this surface shows it, so
    # the legacy payload stays byte-for-byte what it was during dual-read.
    assert body["state"] is None


def test_the_flagged_state_block_carries_its_confidence_and_a_route_to_its_evidence(
    seeded_db_empty_cards,
) -> None:
    settings = _test_settings().model_copy(
        update={"rates_snapshot_state_block_enabled": True}
    )
    _seed_snapshot(settings)
    _seed_policy_rates_state(settings)

    body = _client_with(settings).get("/api/rates/snapshot").json()

    state = body["state"]
    assert state["domain"] == "policy_rates"
    assert state["state"] == "ON_HOLD"
    assert state["engine_version"] == "rates/1"
    assert state["confidence_reasons"], (
        "a confidence with no terms cannot be argued with"
    )
    assert state["evidence_count"] > 0
    # The compact block must never be the only view of the answer.
    assert state["detail_path"] == "/api/macro/rates"


def test_no_computed_state_reads_as_absent_rather_than_as_a_neutral_one(
    seeded_db_empty_cards,
) -> None:
    settings = _test_settings().model_copy(
        update={"rates_snapshot_state_block_enabled": True}
    )
    _seed_snapshot(settings)

    body = _client_with(settings).get("/api/rates/snapshot").json()

    # The defect this milestone exists to prevent: absence rendered as a confident view.
    assert body["state"] is None
