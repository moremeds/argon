"""Worker jobs — gold daily ingestion (FRED / GPR / ETF / COMEX)."""

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
from uw_scan.sources.comex import ComexProvider, ComexVaultRow
from uw_scan.sources.etf_holdings import EtfHoldingRow
from uw_scan.sources.fred import FredObservation
from uw_scan.sources.gpr import GprObservation
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.gold_jobs import (
    gold_comex_vault_ingest_job,
    gold_etf_holdings_ingest_job,
    gold_fred_ingest_job,
    gold_gpr_ingest_job,
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


def test_gold_fred_ingest_writes_macro_series_daily(fresh_db: Settings) -> None:
    sample = [
        FredObservation("DFII10", date(2026, 5, 14), Decimal("1.97")),
        FredObservation("DFII10", date(2026, 5, 15), Decimal("2.01")),
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.FredProvider") as MockProvider:
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_series.return_value = sample
        gold_fred_ingest_job(dsn=fresh_db.db_dsn(), series_ids=["DFII10"])

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_macro_series_daily("DFII10")
    assert len(rows) == 2


def test_gold_gpr_ingest_writes_macro_series_daily(fresh_db: Settings) -> None:
    sample = [GprObservation(date(2026, 5, 13), Decimal("118.4"))]
    with patch("uw_scan.worker.jobs.gold_jobs.GprProvider") as MockProvider:
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_daily.return_value = sample
        gold_gpr_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_macro_series_daily("GPRD")
    assert len(rows) == 1
    assert rows[0]["value"] == Decimal("118.4")


def test_gold_etf_holdings_ingest_writes_all_four_funds(
    fresh_db: Settings,
) -> None:
    one = lambda ticker: [  # noqa: E731
        EtfHoldingRow(
            ticker=ticker,
            obs_date=date(2026, 5, 14),
            holdings_oz=Decimal("100"),
            shares_out=None,
            nav_per_share=None,
            premium_pct=None,
        )
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.EtfHoldingsProvider") as MockProvider:
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_gld.return_value = one("GLD")
        instance.fetch_iau.return_value = one("IAU")
        instance.fetch_gldm.return_value = one("GLDM")
        instance.fetch_phys.return_value = one("PHYS")
        gold_etf_holdings_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        for t in ("GLD", "IAU", "GLDM", "PHYS"):
            assert len(repo.fetch_etf_holdings_daily(t)) == 1


def test_gold_comex_vault_ingest_writes_inventory(fresh_db: Settings) -> None:
    sample = [
        ComexVaultRow(
            obs_date=date(2026, 5, 15),
            registered_oz=Decimal("17500100"),
            eligible_oz=Decimal("10820200"),
            total_oz=Decimal("28320300"),
        )
    ]
    with patch("uw_scan.worker.jobs.gold_jobs.ComexProvider") as MockProvider:
        MockProvider.URL = ComexProvider.URL
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_vault.return_value = sample
        gold_comex_vault_ingest_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_exchange_inventory_daily("COMEX")
    assert len(rows) == 1
    assert rows[0]["registered_oz"] == Decimal("17500100")
