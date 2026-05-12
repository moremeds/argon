"""MarketAggregates round-trip through set_aggregates / get_aggregates.

The plan calls for invoking run_single_stock end-to-end against a live UW
client; that requires a real API key and is covered by the existing
tests/integration/test_pipeline_e2e.py-style harness. Here we exercise just
the persistence layer so the round-trip is verified without live API costs.
"""

from __future__ import annotations

import os
import subprocess
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.models import MarketAggregates
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[2]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set; refusing to commit to working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    base = Settings.from_env()
    return base.model_copy(update={"db_name": test_db})


@pytest.fixture
def repo():
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
        yield Repository(conn, schema=settings.db_schema)


def test_aggregates_round_trip(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    run_id = repo.insert_scan_run("ZZTEST", notes="t")
    agg = MarketAggregates(
        call_oi_total=1_200_000,
        put_oi_total=2_100_000,
        call_volume_total=500_000,
        put_volume_total=800_000,
        pcr_oi=Decimal("1.75"),
        pcr_vol=Decimal("1.60"),
        iv30d=Decimal("0.42"),
    )
    repo.set_aggregates(run_id, agg)
    got = repo.get_aggregates(run_id)
    assert got is not None
    assert got.call_oi_total == 1_200_000
    assert got.put_oi_total == 2_100_000
    assert got.pcr_oi == Decimal("1.75")
    assert got.iv30d == Decimal("0.42")


def test_aggregates_get_returns_none_when_unset(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    run_id = repo.insert_scan_run("ZZTEST", notes="t")
    assert repo.get_aggregates(run_id) is None
