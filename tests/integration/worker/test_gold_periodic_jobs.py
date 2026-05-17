"""Worker jobs — gold periodic ingestion (CFTC / LBMA / WGC)."""

from __future__ import annotations

import os
import subprocess
from datetime import date
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


def test_gold_wgc_cb_ingest_writes_reserves(fresh_db: Settings) -> None:
    sample = [
        CbReserveRow(
            country_iso3="CHN",
            obs_month=date(2026, 4, 1),
            reserves_t=Decimal("2235.0"),
            bucket="strategic_accumulator",
            is_reported=True,
            is_estimated=False,
        )
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.WgcCbProvider") as MockProvider:
        MockProvider.return_value.__enter__.return_value.fetch_monthly.return_value = (
            sample
        )
        gold_wgc_cb_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_cb_gold_reserves_monthly(bucket="strategic_accumulator")
    assert any(r["country_iso3"] == "CHN" for r in rows)
