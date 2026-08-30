"""Rates router — /api/rates/snapshot."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.worker._macro_providers import _StatementProvider
from tests.integration.worker.test_macro_state_jobs import POLICY_AS_OF
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.routers.rates import _mark_stale_snapshot_sources
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.macro.rates import RATES_ENGINE_VERSION
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


def _snapshot(
    *,
    as_of: date = date(2026, 5, 20),
    computed_at: datetime = datetime(2026, 5, 21, 1, 2, 3, tzinfo=UTC),
) -> RatesSnapshotResponse:
    return RatesSnapshotResponse(
        as_of=as_of,
        computed_at=computed_at,
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


def _seed(*snapshots: RatesSnapshotResponse) -> None:
    """Persist snapshots on a third, committed connection.

    ``seeded_db_empty_cards`` holds an uncommitted connection and the TestClient's
    ``get_repo`` override opens its own, so a seed the request path can actually see has
    to be committed from outside both.
    """
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        for snapshot in snapshots:
            payload = snapshot.model_dump(mode="json")
            repo.insert_rates_snapshot(
                snapshot_date=snapshot.as_of,
                computed_at=snapshot.computed_at,
                payload=payload,
                source_freshness=payload["source_freshness"],
            )
        conn.commit()


def test_rates_snapshot_returns_latest_persisted_payload(
    rates_client: TestClient,
) -> None:
    _seed(_snapshot())

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
        at=datetime(2026, 5, 23, 14, 2, 4, tzinfo=UTC),
    )

    assert stale.source_freshness[0].status == "stale"
    assert "scheduled FRED refresh" in stale.synthesis.risks[-1]


# --- point-in-time replay ------------------------------------------------------------

#: Two computes, in the order the desk produced them. The EARLIER compute carries the
#: EARLIER market date here, unlike the repository's own ordering test, because what is
#: being pinned is which answer existed when -- not how a tie is broken.
_EARLIER = _snapshot(
    as_of=date(2026, 5, 19), computed_at=datetime(2026, 5, 20, 1, 2, 3, tzinfo=UTC)
)
_LATER = _snapshot()
#: After the earlier compute, before the later one.
_BETWEEN = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)


def _seed_both_snapshots() -> None:
    _seed(_EARLIER, _LATER)


def test_no_parameter_still_returns_the_latest_snapshot(
    rates_client: TestClient,
) -> None:
    """The live path must not change shape because a replay path was added."""
    _seed_both_snapshots()

    response = rates_client.get("/api/rates/snapshot")

    assert response.status_code == 200
    assert response.json()["as_of"] == "2026-05-20"


def test_as_of_returns_the_snapshot_that_was_current_then(
    rates_client: TestClient,
) -> None:
    """The whole point: a past instant sees the answer that EXISTED then."""
    _seed_both_snapshots()

    response = rates_client.get(
        "/api/rates/snapshot", params={"as_of_ts": _BETWEEN.isoformat()}
    )

    assert response.status_code == 200
    assert response.json()["as_of"] == "2026-05-19", (
        "a replay before the later compute must not see it"
    )


def test_an_as_of_date_replays_to_that_day_end(rates_client: TestClient) -> None:
    _seed_both_snapshots()

    response = rates_client.get("/api/rates/snapshot", params={"as_of": "2026-05-20"})

    # Day-end on the 20th is after the 01:02 compute on the 20th and before the
    # 01:02 compute on the 21st.
    assert response.status_code == 200
    assert response.json()["as_of"] == "2026-05-19"


def test_supplying_both_instants_is_refused(rates_client: TestClient) -> None:
    response = rates_client.get(
        "/api/rates/snapshot",
        params={"as_of": "2026-05-20", "as_of_ts": "2026-05-20T12:00:00+00:00"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "supply either as_of or as_of_ts, not both"


def test_a_naive_instant_is_refused(rates_client: TestClient) -> None:
    """Same contract as every /api/macro/* route: a tz-less instant is a guess."""
    response = rates_client.get(
        "/api/rates/snapshot", params={"as_of_ts": "2026-05-20T12:00:00"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "as_of_ts must carry a UTC offset"


def test_a_replayed_snapshot_is_not_force_marked_stale(
    rates_client: TestClient,
) -> None:
    """The trap: staleness measured against ``now()`` condemns all of history.

    A historical snapshot is always old relative to the wall clock, so a replay would
    have rewritten every ``ok`` source to ``stale`` and appended a scheduler-failure
    risk to every past date -- reporting an outage that never happened. Aged against
    the requested instant, this snapshot is 58 minutes old and healthy.
    """
    _seed_both_snapshots()

    response = rates_client.get(
        "/api/rates/snapshot",
        params={"as_of_ts": datetime(2026, 5, 21, 2, 0, 0, tzinfo=UTC).isoformat()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-05-20"
    assert body["source_freshness"][0]["status"] == "ok"
    assert body["synthesis"]["risks"] == []


def test_a_replay_still_reports_the_staleness_the_desk_really_had(
    rates_client: TestClient,
) -> None:
    """The other half: replay must not become blanket amnesty for staleness.

    Fixing the trap by never marking a replayed snapshot stale would hide the real
    outages -- the dates an operator most wants to replay.
    """
    _seed_both_snapshots()

    response = rates_client.get(
        "/api/rates/snapshot",
        params={"as_of_ts": datetime(2026, 5, 25, 2, 0, 0, tzinfo=UTC).isoformat()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_freshness"][0]["status"] == "stale"
    assert "scheduled FRED refresh" in body["synthesis"]["risks"][-1]


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
    assert state["engine_version"] == RATES_ENGINE_VERSION
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
