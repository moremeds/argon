"""Repository methods for etf_holdings_daily and exchange_inventory_daily."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set; refusing to write into the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def repo() -> Repository:
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


def test_insert_and_fetch_etf_holdings_daily(repo: Repository) -> None:
    repo.insert_etf_holdings_daily(
        ticker="GLD",
        obs_date=date(2026, 5, 14),
        holdings_oz=Decimal("28047500.12"),
        shares_out=None,
        nav_per_share=Decimal("234.50"),
        premium_pct=None,
        as_of=datetime.now(UTC),
        source="SPDR",
    )
    rows = repo.fetch_etf_holdings_daily("GLD", from_date=date(2026, 5, 1))
    assert len(rows) == 1
    assert rows[0]["holdings_oz"] == Decimal("28047500.12")


def test_insert_and_fetch_etf_flows_daily(repo: Repository) -> None:
    as_of = datetime.now(UTC)
    repo.insert_etf_flows_daily(
        ticker="GLD",
        obs_date=date(2026, 5, 15),
        share_change=Decimal("-900000"),
        premium_change_usd=Decimal("-375300000"),
        close=Decimal("417.29"),
        volume=Decimal("8801181"),
        as_of=as_of,
        source="UW",
    )

    rows = repo.fetch_etf_flows_daily("GLD", from_date=date(2026, 5, 1))

    assert len(rows) == 1
    assert rows[0]["obs_date"] == date(2026, 5, 15)
    assert rows[0]["share_change"] == Decimal("-900000")
    assert rows[0]["premium_change_usd"] == Decimal("-375300000")
    assert rows[0]["source"] == "UW"


def test_insert_and_fetch_wgc_etf_monthly(repo: Repository) -> None:
    as_of = datetime.now(UTC)
    repo.insert_wgc_etf_monthly(
        ticker="GLD",
        obs_date=date(2026, 3, 31),
        fund_name="SPDR Gold Shares",
        fund_type="ETF",
        region="North America",
        country="US",
        gold_price_usd_oz=Decimal("2983.25"),
        aggregate_ounces=Decimal("131428333.123"),
        aggregate_holdings_tonnes=Decimal("4087.79194987"),
        aggregate_value_usd=Decimal("606500000000"),
        holdings_tonnes=Decimal("1046.9009356"),
        demand_tonnes=Decimal("-54.13175268"),
        flow_usd_mn=Decimal("-8426.7817"),
        source_url="https://www.gold.org/download/file/20717/ETF_Flows_March_2026.xlsx",
        source_label="ETF_Flows_March_2026.xlsx",
        as_of=as_of,
        source="WGC",
    )

    rows = repo.fetch_wgc_etf_monthly("GLD", from_date=date(2026, 1, 1))

    assert len(rows) == 1
    assert rows[0]["fund_name"] == "SPDR Gold Shares"
    assert rows[0]["holdings_tonnes"] == Decimal("1046.9009356")
    assert rows[0]["demand_tonnes"] == Decimal("-54.13175268")
    assert rows[0]["flow_usd_mn"] == Decimal("-8426.7817")
    assert rows[0]["source_url"].endswith("ETF_Flows_March_2026.xlsx")


def test_insert_and_fetch_exchange_inventory_daily(repo: Repository) -> None:
    repo.insert_exchange_inventory_daily(
        exchange="COMEX",
        obs_date=date(2026, 5, 15),
        registered_oz=Decimal("17500100"),
        eligible_oz=Decimal("10820200"),
        vault_oz=None,
        as_of=datetime.now(UTC),
        source_url=None,
    )
    rows = repo.fetch_exchange_inventory_daily("COMEX", from_date=date(2026, 5, 1))
    assert len(rows) == 1
    assert rows[0]["registered_oz"] == Decimal("17500100")
