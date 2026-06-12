"""Repository methods for etf_holdings_daily and exchange_inventory_daily."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import pytest

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
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


def test_insert_etf_holdings_daily_rows_is_empty_safe_and_idempotent(
    repo: Repository,
) -> None:
    as_of = datetime(2026, 5, 19, 12, tzinfo=UTC)
    rows = [
        {
            "ticker": "GLD",
            "obs_date": date(2026, 5, 14),
            "holdings_oz": Decimal("28047500.12"),
            "shares_out": None,
            "nav_per_share": Decimal("234.50"),
            "premium_pct": None,
        },
        {
            "ticker": "GLD",
            "obs_date": date(2026, 5, 15),
            "holdings_oz": Decimal("28048500.12"),
            "shares_out": None,
            "nav_per_share": Decimal("235.50"),
            "premium_pct": None,
        },
    ]

    assert repo.insert_etf_holdings_daily_rows([], as_of=as_of, source="SPDR") == 0
    assert repo.insert_etf_holdings_daily_rows(rows, as_of=as_of, source="SPDR") == 2
    assert repo.insert_etf_holdings_daily_rows(rows, as_of=as_of, source="SPDR") == 2

    fetched = repo.fetch_etf_holdings_daily("GLD", from_date=date(2026, 5, 1))
    assert [row["obs_date"] for row in fetched] == [
        date(2026, 5, 14),
        date(2026, 5, 15),
    ]
    assert [row["holdings_oz"] for row in fetched] == [
        Decimal("28047500.12"),
        Decimal("28048500.12"),
    ]


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


def test_insert_etf_flows_daily_rows_is_empty_safe_and_idempotent(
    repo: Repository,
) -> None:
    as_of = datetime(2026, 5, 19, 12, tzinfo=UTC)
    rows = [
        {
            "ticker": "gld",
            "obs_date": date(2026, 5, 15),
            "share_change": Decimal("-900000"),
            "premium_change_usd": Decimal("-375300000"),
            "close": Decimal("417.29"),
            "volume": Decimal("8801181"),
        },
        {
            "ticker": "GLD",
            "obs_date": date(2026, 5, 16),
            "share_change": Decimal("100000"),
            "premium_change_usd": Decimal("42100000"),
            "close": Decimal("421.00"),
            "volume": Decimal("7801181"),
        },
    ]

    assert repo.insert_etf_flows_daily_rows([], as_of=as_of, source="UW") == 0
    assert repo.insert_etf_flows_daily_rows(rows, as_of=as_of, source="UW") == 2
    assert repo.insert_etf_flows_daily_rows(rows, as_of=as_of, source="UW") == 2

    fetched = repo.fetch_etf_flows_daily("GLD", from_date=date(2026, 5, 1))
    assert [row["obs_date"] for row in fetched] == [
        date(2026, 5, 15),
        date(2026, 5, 16),
    ]
    assert [row["share_change"] for row in fetched] == [
        Decimal("-900000"),
        Decimal("100000"),
    ]


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


def test_fetch_wgc_etf_monthly_prefers_latest_workbook_revision(repo: Repository) -> None:
    as_of = datetime.now(UTC)
    repo.insert_wgc_etf_monthly(
        ticker="GLD",
        obs_date=date(2026, 3, 31),
        fund_name="SPDR Gold Shares",
        fund_type="ETF",
        region="North America",
        country="US",
        gold_price_usd_oz=Decimal("2983.25"),
        aggregate_ounces=None,
        aggregate_holdings_tonnes=None,
        aggregate_value_usd=None,
        holdings_tonnes=Decimal("1040.0"),
        demand_tonnes=Decimal("-10.0"),
        flow_usd_mn=Decimal("-100.0"),
        source_url="file:///wgc/ETF_Flows_March_2026.xlsx",
        source_label="ETF_Flows_March_2026.xlsx",
        as_of=as_of,
        source="WGC",
    )
    repo.insert_wgc_etf_monthly(
        ticker="GLD",
        obs_date=date(2026, 3, 31),
        fund_name="SPDR Gold Shares",
        fund_type="ETF",
        region="North America",
        country="US",
        gold_price_usd_oz=Decimal("2983.25"),
        aggregate_ounces=None,
        aggregate_holdings_tonnes=None,
        aggregate_value_usd=None,
        holdings_tonnes=Decimal("1042.5"),
        demand_tonnes=Decimal("-7.5"),
        flow_usd_mn=Decimal("-75.0"),
        source_url="file:///wgc/ETF_Flows_April_2026.xlsx",
        source_label="ETF_Flows_April_2026.xlsx",
        as_of=as_of,
        source="WGC",
    )
    repo.insert_wgc_etf_monthly(
        ticker="GLD",
        obs_date=date(2026, 4, 30),
        fund_name="SPDR Gold Shares",
        fund_type="ETF",
        region="North America",
        country="US",
        gold_price_usd_oz=Decimal("3325.10"),
        aggregate_ounces=None,
        aggregate_holdings_tonnes=None,
        aggregate_value_usd=None,
        holdings_tonnes=Decimal("1050.0"),
        demand_tonnes=Decimal("7.5"),
        flow_usd_mn=Decimal("75.0"),
        source_url="file:///wgc/ETF_Flows_April_2026.xlsx",
        source_label="ETF_Flows_April_2026.xlsx",
        as_of=as_of,
        source="WGC",
    )

    rows = repo.fetch_wgc_etf_monthly(
        "GLD",
        from_date=date(2026, 3, 1),
        to_date=date(2026, 3, 31),
    )

    assert len(rows) == 1
    assert rows[0]["holdings_tonnes"] == Decimal("1042.5")
    assert rows[0]["source_url"].endswith("ETF_Flows_April_2026.xlsx")


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
