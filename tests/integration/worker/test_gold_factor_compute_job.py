"""Worker job — gold_factor_compute_job: macro_series_daily inputs -> gold_factor_daily."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import numpy as np
import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.gold_factor import fetch_rows
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.gold_factor import gold_factor_compute_job

pytestmark = pytest.mark.integration


@pytest.fixture
def fresh_db(seeded_db_empty_cards) -> Settings:
    _ = seeded_db_empty_cards
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _seed(dsn: str, n: int) -> None:
    from tests.unit.macro.test_gold_factor import _levels

    lv = _levels(n)
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        for sid in lv.columns:
            repo.insert_macro_series_daily_rows(
                ({"series_id": sid, "obs_date": d.date(), "value": float(v)} for d, v in lv[sid].items()),
                as_of=datetime(2026, 10, 10, tzinfo=UTC),
                source="IB" if sid not in ("DFII10", "DGS10") else "FRED",
            )


def test_job_writes_every_grid_row_and_is_idempotent(fresh_db: Settings) -> None:
    dsn = fresh_db.db_dsn()
    _seed(dsn, 300)
    assert gold_factor_compute_job(dsn=dsn) == 299
    assert gold_factor_compute_job(dsn=dsn) == 299
    with psycopg.connect(dsn) as conn:
        rows = fetch_rows(conn)
    assert len(rows) == 299
    last = rows[-1]
    parts = ("own_trailing_drift", "real_yield_part", "dollar_part", "haven_part", "unexplained_1")
    assert np.isclose(sum(last[p] for p in parts), last["gold_change"])
    assert last["b_r_lo95"] <= last["b_r"] <= last["b_r_hi95"]
    assert rows[0]["b_r"] is None and rows[0]["computed_at"] is not None


def test_job_refuses_too_short_a_history(fresh_db: Settings) -> None:
    _seed(fresh_db.db_dsn(), 100)
    with pytest.raises(RuntimeError, match="gold_factor_seed"):
        gold_factor_compute_job(dsn=fresh_db.db_dsn())


def test_api_serves_points_and_years(fresh_db: Settings) -> None:
    from fastapi.testclient import TestClient

    from uw_scan.api.deps import get_repo, get_settings
    from uw_scan.api.server import create_app

    dsn = fresh_db.db_dsn()
    _seed(dsn, 300)
    gold_factor_compute_job(dsn=dsn)

    def _repo():
        with psycopg.connect(dsn) as conn:
            yield Repository(conn, schema="uw_scan")

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: fresh_db
    app.dependency_overrides[get_repo] = _repo
    with TestClient(app) as client:
        assert client.get("/api/gold/factor").status_code == 200
        body = client.get("/api/gold/factor", params={"from": "2020-01-01"}).json()
    assert len(body["points"]) == 299
    yr = body["years"][-1]
    parts = ("own_trailing_drift", "real_yield_part", "dollar_part", "haven_part", "unexplained")
    assert np.isclose(sum(yr[p] for p in parts), yr["gold_change"]) and yr["partial_year"]


def test_job_writes_dxy_and_api_serves_dxy_and_flows(fresh_db: Settings) -> None:
    from fastapi.testclient import TestClient

    from uw_scan.api.deps import get_repo, get_settings
    from uw_scan.api.server import create_app

    dsn = fresh_db.db_dsn()
    _seed(dsn, 300)
    gold_factor_compute_job(dsn=dsn)

    def _repo():
        with psycopg.connect(dsn) as conn:
            yield Repository(conn, schema="uw_scan")

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: fresh_db
    app.dependency_overrides[get_repo] = _repo
    with TestClient(app) as client:
        dxy = client.get("/api/macro/dxy", params={"from": "2020-01-01"}).json()
        flows = client.get("/api/gold/flows").json()
    assert len(dxy["points"]) == 300  # every date with the six pairs, base row included
    last = dxy["points"][-1]
    pairs = ("eurusd", "usdjpy", "gbpusd", "usdcad", "usdsek", "usdchf")
    assert np.isclose(sum(last[f"{p}_part"] for p in pairs), last["change_pct"])
    assert flows == {
        "china_reserves_t": [],
        "cftc_mm_net_pct_oi": [],
        "lbma_vault_t": [],
    }
