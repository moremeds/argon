"""Gold router — /api/gold/state + /api/gold/lenses."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
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
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def app_with_posture() -> TestClient:
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
        repo.insert_gold_posture_daily(
            obs_date=date(2026, 5, 16),
            computed_at=datetime(2026, 5, 17, tzinfo=UTC),
            gauge_corr_60d=Decimal("-0.04"),
            gauge_corr_126d=Decimal("-0.05"),
            gauge_corr_252d=Decimal("-0.07"),
            gauge_corr_504d=Decimal("-0.31"),
            gauge_corr_252d_returns=Decimal("-0.06"),
            gauge_state="suspended",
            structural_state_label="structural-bid-intact",
            cb_strategic_12m_sum_t=Decimal("210"),
            cb_tactical_12m_sum_t=Decimal("12"),
            cb_diversifier_12m_sum_t=Decimal("34"),
            gld_holdings_t=Decimal("872.5"),
            gld_30d_net_flow_t=Decimal("-12.4"),
            comex_registered_oz=Decimal("17500100"),
            comex_20d_roc_pct=Decimal("0.14"),
            cot_mm_net_pct=Decimal("0.72"),
            cyclical_zone_label="moderate-trap",
            cpi_yoy=Decimal("2.8"),
            t5yifr=Decimal("2.31"),
            dfii10=Decimal("1.97"),
            dfii10_60d_change_bps=Decimal("12"),
            factors_jsonb={"F5": 1.8},
            valuation_flag="Severe",
            real_price_percentile=Decimal("0.92"),
            gold_m2_ratio_percentile=Decimal("0.78"),
            gold_spx_ratio_percentile=Decimal("0.64"),
            structural_posture_text="Structural bid intact.",
            cyclical_posture_text="Cyclical posture suspended.",
            valuation_posture_text="Mean-reversion risk: SEVERE.",
            inputs_jsonb={
                "DFII10": {
                    "obs_date": "2026-05-16",
                    "as_of": "2026-05-17T00:00:00Z",
                }
            },
            structural_posture_chip="FAVORABLE",
            cyclical_posture_chip="SUSPENDED",
            valuation_posture_chip="STRETCHED",
            spot_jsonb={
                "last": "4561.50",
                "delta_abs": "-157.20",
                "delta_pct": "-0.0332",
                "high": "4615.20",
                "low": "4524.30",
                "open": "4615.20",
            },
            data_freshness_jsonb=[
                {
                    "id": "FRED",
                    "last_as_of": "2026-05-17T00:00:00+00:00",
                    "stale_seconds": 60,
                }
            ],
            decomposition_jsonb=[
                {"lens": "L1", "factor": "CB", "contribution": "1.4"},
            ],
            correlation_history_jsonb={
                "gold_dfii10": [],
                "gold_dxy": [],
                "gold_gpr": [],
                "pre_2022_band": {"mean": "-0.84", "std": "0.04"},
            },
            gld_history_jsonb=[],
            gold_history_jsonb=[],
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


def test_state_endpoint_returns_latest_posture(
    app_with_posture: TestClient,
) -> None:
    response = app_with_posture.get("/api/gold/state")
    assert response.status_code == 200
    body = response.json()
    assert body["obs_date"] == "2026-05-16"
    assert body["gauge"]["state"] == "suspended"
    assert body["valuation"]["flag"] == "Severe"
    assert body["cyclical"]["zone_label"] == "moderate-trap"
    # GOLD COMPASS extensions
    assert body["structural"]["posture_chip"] == "FAVORABLE"
    assert body["valuation"]["posture_chip"] == "STRETCHED"
    assert body["spot"]["last"] == "4561.50"
    assert len(body["decomposition_rows"]) == 1


def test_lenses_endpoint_returns_per_lens_detail(
    app_with_posture: TestClient,
) -> None:
    response = app_with_posture.get("/api/gold/lenses/structural")
    assert response.status_code == 200
    body = response.json()
    assert body["lens_id"] == "structural"
    assert "narrative_text" in body["posture"]


def test_lenses_endpoint_rejects_unknown_lens(
    app_with_posture: TestClient,
) -> None:
    response = app_with_posture.get("/api/gold/lenses/unknown")
    assert response.status_code in (404, 422)
