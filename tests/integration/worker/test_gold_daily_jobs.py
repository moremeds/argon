"""Worker jobs — gold daily ingestion (FRED / GPR / ETF / COMEX)."""

from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from openpyxl import Workbook

from uw_scan.config import Settings
from uw_scan.models import EtfInOutflowRow
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


def _write_wgc_etf_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Holdings by month"
    ws.append(
        [
            "ticker",
            "All units in tonnes unless otherwise specified",
            None,
            None,
            None,
            "gld us equity",
            "iau us equity",
            "gldm us equity",
            "phys us equity",
        ]
    )
    ws.append(["Active", None, None, None, None, "Active", "Active", "Active", "Active"])
    ws.append(
        ["Fund Type", None, None, None, None, "ETF", "ETF", "ETF", "Closed-End Fund"]
    )
    ws.append(
        [
            "Region",
            None,
            None,
            None,
            None,
            "North America",
            "North America",
            "North America",
            "North America",
        ]
    )
    ws.append(["Country", None, None, None, None, "US", "US", "US", "US"])
    ws.append(
        [
            "Date",
            "Gold, US$/oz",
            "Ounces",
            "Tonnes",
            "Value (USD)",
            "SPDR Gold Shares",
            "iShares Gold Trust",
            "SPDR Gold MiniShares Trust",
            "Sprott Physical Gold Trust",
        ]
    )
    ws.append(
        [
            date(2026, 3, 31),
            Decimal("2983.25"),
            None,
            None,
            None,
            Decimal("1046.9009356"),
            Decimal("475.96149609"),
            Decimal("199.89033267"),
            Decimal("114.72237255"),
        ]
    )
    demand = wb.copy_worksheet(ws)
    demand.title = "Demand by month"
    demand["F7"] = Decimal("-54.13175268")
    demand["G7"] = Decimal("-23.26570443")
    demand["H7"] = Decimal("-2.17337528")
    demand["I7"] = Decimal("-2.98578583")
    flows = wb.copy_worksheet(ws)
    flows.title = "Fund flows by month"
    flows["F7"] = Decimal("-8426.7817")
    flows["G7"] = Decimal("-3677.5729")
    flows["H7"] = Decimal("-360.4612")
    flows["I7"] = Decimal("-466.74545549")
    buf = BytesIO()
    wb.save(buf)
    path.write_bytes(buf.getvalue())


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


def test_gold_etf_holdings_ingest_uses_deep_holdings_lookback(
    fresh_db: Settings,
) -> None:
    with patch("uw_scan.worker.jobs.gold_jobs.EtfHoldingsProvider") as MockProvider:
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_gld.return_value = []
        instance.fetch_iau.return_value = []
        instance.fetch_gldm.return_value = []
        instance.fetch_phys.return_value = []

        gold_etf_holdings_ingest_job(dsn=fresh_db.db_dsn())

    assert instance.fetch_gld.call_args.kwargs["start"] <= date.today() - timedelta(
        days=400
    )


def test_gold_etf_holdings_ingest_reads_wgc_monthly_workbook(
    fresh_db: Settings,
    tmp_path: Path,
) -> None:
    workbook_path = tmp_path / "ETF_Flows_March_2026.xlsx"
    _write_wgc_etf_workbook(workbook_path)
    with patch("uw_scan.worker.jobs.gold_jobs.EtfHoldingsProvider") as MockProvider:
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_gld.return_value = []
        instance.fetch_iau.return_value = []
        instance.fetch_gldm.return_value = []
        instance.fetch_phys.return_value = []

        gold_etf_holdings_ingest_job(
            dsn=fresh_db.db_dsn(),
            wgc_workbook_path=str(workbook_path),
        )

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        gld = repo.fetch_etf_holdings_daily("GLD")
        iau = repo.fetch_etf_holdings_daily("IAU")
        phys = repo.fetch_etf_holdings_daily("PHYS")
        wgc_gld = repo.fetch_wgc_etf_monthly("GLD")

    assert gld[0]["obs_date"] == date(2026, 3, 31)
    assert gld[0]["source"] == "WGC"
    assert gld[0]["holdings_oz"] == Decimal("1046.9009356") * Decimal("32150.7466")
    assert iau[0]["source"] == "WGC"
    assert phys[0]["source"] == "WGC"
    assert wgc_gld[0]["holdings_tonnes"] == Decimal("1046.9009356")
    assert wgc_gld[0]["source_url"].startswith("file:")


def test_gold_etf_holdings_ingest_writes_uw_etf_flows(
    fresh_db: Settings,
) -> None:
    sample = [
        EtfInOutflowRow(
            ticker="GLD",
            date=date(2026, 5, 15),
            change=Decimal("-900000"),
            change_prem=Decimal("-375300000"),
            close=Decimal("417.29"),
            volume=Decimal("8801181"),
        )
    ]
    with (
        patch("uw_scan.worker.jobs.gold_jobs.EtfHoldingsProvider") as MockProvider,
        patch("uw_scan.worker.jobs.gold_jobs.UwClient"),
        patch(
            "uw_scan.worker.jobs.gold_jobs.uw_sources.fetch_etf_in_outflow",
            return_value=sample,
        ) as mock_fetch,
    ):
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_gld.return_value = []
        instance.fetch_iau.return_value = []
        instance.fetch_gldm.return_value = []
        instance.fetch_phys.return_value = []

        gold_etf_holdings_ingest_job(
            dsn=fresh_db.db_dsn(), uw_api_key="test-key", lookback_days=45
        )

    assert [call.kwargs["ticker"] for call in mock_fetch.call_args_list] == [
        "GLD",
        "IAU",
        "GLDM",
    ]
    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        rows = repo.fetch_etf_flows_daily("GLD")
    assert len(rows) == 1
    assert rows[0]["share_change"] == Decimal("-900000")
    assert rows[0]["premium_change_usd"] == Decimal("-375300000")


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
