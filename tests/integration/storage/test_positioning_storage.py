"""Integration test for _PositioningMixin (real Postgres via pytest-postgresql)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def test_upsert_and_read_back_round_trip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_uw_positioning(
        ticker="nvda",  # lower-case in → stored upper-case
        snapshot_date=date(2026, 5, 15),
        si_pct_float=Decimal("0.0734"),
        si_short_interest=Decimal("175611155"),
        analyst_buy=12,
        analyst_hold=3,
        analyst_sell=1,
        analyst_target_avg=Decimal("340"),
        inst_holder_count=120,
        inst_total_value=Decimal("1995205923.0"),
        insider_net_flow=Decimal("564386"),
        earn_reactions_positive=3,
        earn_reactions_total=4,
        si_market_date=date(2026, 5, 15),
        raw_jsonb={"short_interest_float": {"si_pct_float": "0.0734"}},
    )

    row = repo.get_uw_positioning("NVDA")
    assert row is not None
    assert row["ticker"] == "NVDA"
    assert row["snapshot_date"] == date(2026, 5, 15)
    assert row["si_pct_float"] == Decimal("0.0734")
    assert row["analyst_buy"] == 12
    assert row["inst_total_value"] == Decimal("1995205923.0")
    assert row["earn_reactions_positive"] == 3
    assert row["raw_jsonb"]["short_interest_float"]["si_pct_float"] == "0.0734"
    assert row["fetched_at"] is not None


def test_on_conflict_overwrites_same_key(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    key = dict(ticker="AAPL", snapshot_date=date(2026, 5, 15))
    repo.upsert_uw_positioning(**key, analyst_buy=5, si_pct_float=Decimal("0.01"))
    repo.upsert_uw_positioning(**key, analyst_buy=9, si_pct_float=Decimal("0.02"))

    row = repo.get_uw_positioning("AAPL")
    assert row is not None
    assert row["analyst_buy"] == 9  # second write wins
    assert row["si_pct_float"] == Decimal("0.02")

    # still a single row for the key
    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.uw_positioning "
            "WHERE ticker = %s AND snapshot_date = %s",
            ("AAPL", date(2026, 5, 15)),
        )
        assert cur.fetchone()[0] == 1


def test_get_returns_none_when_absent(seeded_db_empty_cards):
    assert seeded_db_empty_cards.get_uw_positioning("ZZZZ") is None
