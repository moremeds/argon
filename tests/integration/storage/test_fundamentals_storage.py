"""Integration test for _FundamentalsMixin (real Postgres via pytest-postgresql)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def test_upsert_and_read_back_latest(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    # two quarters; get_massive_fundamentals returns the most recent period_end
    repo.upsert_massive_fundamentals(
        ticker="nvda",
        period_end=date(2025, 12, 28),
        fiscal_period="Q4",
        revenue=Decimal("400"),
        gross_margin=Decimal("0.60"),
        fcf=Decimal("110"),
    )
    repo.upsert_massive_fundamentals(
        ticker="NVDA",
        period_end=date(2026, 3, 28),
        fiscal_period="Q1",
        revenue=Decimal("500"),
        gross_margin=Decimal("0.62"),
        net_margin=Decimal("0.18"),
        total_debt=Decimal("200"),
        share_count_delta=Decimal("0.01"),
        latest_dividend_amount=Decimal("0.26"),
        latest_dividend_ex_date=date(2026, 5, 11),
        raw_jsonb={"fiscal_period": "Q1"},
    )

    row = repo.get_massive_fundamentals("nvda")
    assert row is not None
    assert row["ticker"] == "NVDA"
    assert row["period_end"] == date(2026, 3, 28)  # latest
    assert row["revenue"] == Decimal("500")
    assert row["gross_margin"] == Decimal("0.62")
    assert row["net_margin"] == Decimal("0.18")
    assert row["share_count_delta"] == Decimal("0.01")
    assert row["latest_dividend_amount"] == Decimal("0.26")
    assert row["raw_jsonb"]["fiscal_period"] == "Q1"
    assert row["fetched_at"] is not None


def test_on_conflict_overwrites_same_period(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    key = dict(ticker="AAPL", period_end=date(2026, 3, 28))
    repo.upsert_massive_fundamentals(**key, revenue=Decimal("100"))
    repo.upsert_massive_fundamentals(**key, revenue=Decimal("200"))

    row = repo.get_massive_fundamentals("AAPL")
    assert row is not None
    assert row["revenue"] == Decimal("200")
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.massive_fundamentals "
            "WHERE ticker = %s AND period_end = %s",
            ("AAPL", date(2026, 3, 28)),
        )
        assert cur.fetchone()[0] == 1


def test_get_returns_none_when_absent(seeded_db_empty_cards):
    assert seeded_db_empty_cards.get_massive_fundamentals("ZZZZ") is None
