"""Gold router — /api/gold/replay (first-computed discipline)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

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
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _insert(repo: Repository, computed_at: datetime, state: str) -> None:
    repo.insert_gold_posture_daily(
        obs_date=date(2026, 5, 10),
        computed_at=computed_at,
        gauge_corr_60d=None,
        gauge_corr_126d=None,
        gauge_corr_252d=None,
        gauge_corr_504d=None,
        gauge_corr_252d_returns=None,
        gauge_state=state,
        structural_state_label=None,
        cb_strategic_12m_sum_t=None,
        cb_tactical_12m_sum_t=None,
        cb_diversifier_12m_sum_t=None,
        gld_holdings_t=None,
        gld_30d_net_flow_t=None,
        comex_registered_oz=None,
        comex_20d_roc_pct=None,
        cot_mm_net_pct=None,
        cyclical_zone_label=None,
        cpi_yoy=None,
        t5yifr=None,
        dfii10=None,
        dfii10_60d_change_bps=None,
        factors_jsonb={},
        valuation_flag="Low",
        real_price_percentile=None,
        gold_m2_ratio_percentile=None,
        gold_spx_ratio_percentile=None,
        structural_posture_text=None,
        cyclical_posture_text=None,
        valuation_posture_text=None,
        inputs_jsonb={},
    )


@pytest.fixture
def app_with_multi_vintage(seeded_db_empty_cards) -> TestClient:
    """Two posture rows for the same obs_date — replay must return the FIRST."""
    settings = _test_settings()
    repo = seeded_db_empty_cards
    _insert(repo, datetime(2026, 5, 11, 21, tzinfo=UTC), "suspended")
    _insert(repo, datetime(2026, 5, 20, 21, tzinfo=UTC), "partial")
    repo.conn.commit()

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


def test_replay_returns_first_computed_posture(
    app_with_multi_vintage: TestClient,
) -> None:
    response = app_with_multi_vintage.get("/api/gold/replay?as_of=2026-05-10")
    assert response.status_code == 200
    assert response.json()["gauge"]["state"] == "suspended"


def test_replay_missing_date_returns_404(
    app_with_multi_vintage: TestClient,
) -> None:
    response = app_with_multi_vintage.get("/api/gold/replay?as_of=1999-01-01")
    assert response.status_code == 404
