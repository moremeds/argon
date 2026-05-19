"""Worker jobs — gold periodic ingestion (CFTC / LBMA / WGC)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.sources.cftc_cot import CftcCotProvider, CotRow
from uw_scan.sources.lbma import LbmaProvider, LbmaVaultRow
from uw_scan.sources.wgc_cb import CbReserveRow
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.gold_jobs import (
    gold_cftc_cot_ingest_job,
    gold_lbma_vault_ingest_job,
    gold_wgc_cb_ingest_job,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 19, 12, 0, tzinfo=tz or UTC)


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def fresh_db() -> Settings:
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
    return settings


def test_gold_cftc_cot_ingest_writes_rows(fresh_db: Settings) -> None:
    sample = [
        CotRow(
            obs_date=date(2026, 5, 13),
            release_date=date(2026, 5, 16),
            mm_long=Decimal("210500"),
            mm_short=Decimal("85300"),
            mm_net=Decimal("125200"),
            comm_long=Decimal("180100"),
            comm_short=Decimal("295400"),
            comm_net=Decimal("-115300"),
            open_interest=Decimal("512000"),
        )
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.CftcCotProvider") as MockProvider:
        MockProvider.URL = CftcCotProvider.URL
        MockProvider.return_value.__enter__.return_value.fetch_weekly.return_value = (
            sample
        )
        gold_cftc_cot_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_cot_gold_weekly()
    assert len(rows) == 1
    assert rows[0]["mm_net"] == Decimal("125200")


def test_gold_lbma_vault_ingest_writes_inventory(fresh_db: Settings) -> None:
    sample = [
        LbmaVaultRow(obs_date=date(2026, 4, 30), vault_oz=Decimal("274086000")),
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.LbmaProvider") as MockProvider:
        MockProvider.URL = LbmaProvider.URL
        MockProvider.return_value.__enter__.return_value.fetch_monthly.return_value = (
            sample
        )
        gold_lbma_vault_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_exchange_inventory_daily("LBMA")
    assert len(rows) == 1
    assert rows[0]["vault_oz"] == Decimal("274086000")


def test_gold_wgc_cb_ingest_is_noop_without_auth_source(fresh_db: Settings) -> None:
    gold_wgc_cb_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_cb_gold_reserves_monthly(bucket="strategic_accumulator")
    assert rows == []


def test_gold_wgc_cb_ingest_writes_authenticated_workbook_rows(
    fresh_db: Settings,
) -> None:
    sample = [
        CbReserveRow(
            country_iso3="CHN",
            obs_month=date(2026, 3, 31),
            reserves_t=Decimal("2313.458368"),
            bucket="strategic_accumulator",
            is_reported=True,
            is_estimated=False,
        )
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.WgcCbProvider") as MockProvider:
        MockProvider.RESERVES_PAGE_URL = "https://www.gold.org/goldhub/data/gold-reserves-by-country"
        MockProvider.return_value.__enter__.return_value.fetch_monthly.return_value = (
            sample
        )
        with patch("uw_scan.worker.jobs.gold_jobs.datetime", _FixedDatetime):
            gold_wgc_cb_ingest_job(
                dsn=fresh_db.db_dsn(),
                wgc_workbook_path="/tmp/Quarterly_gold_and_FX_Reserves_Q1_2026.xlsx",
            )
            gold_wgc_cb_ingest_job(
                dsn=fresh_db.db_dsn(),
                wgc_workbook_path="/tmp/Quarterly_gold_and_FX_Reserves_Q1_2026.xlsx",
            )

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_cb_gold_reserves_monthly(bucket="strategic_accumulator")
    assert len(rows) == 1
    assert rows[0]["country_iso3"] == "CHN"
    assert rows[0]["obs_month"] == date(2026, 3, 31)
    assert rows[0]["reserves_t"] == Decimal("2313.458368")
