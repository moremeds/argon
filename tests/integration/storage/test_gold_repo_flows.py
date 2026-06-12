"""Repository methods for cb_gold_reserves, cot_gold_weekly, uw_gold_options."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import pytest

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
def test_cb_reserves_round_trip(repo: Repository) -> None:
    as_of = datetime.now(UTC)
    for obs_month, reserves_t in (
        (date(2025, 3, 31), Decimal("2200.0")),
        (date(2026, 3, 31), Decimal("2235.0")),
    ):
        repo.insert_cb_gold_reserves_monthly(
            country_iso3="CHN",
            obs_month=obs_month,
            reserves_t=reserves_t,
            bucket="strategic_accumulator",
            is_reported=True,
            is_estimated=False,
            as_of=as_of,
            release_date=date(2026, 5, 8),
            source="WGC",
        )
    rows = repo.fetch_cb_gold_reserves_monthly(
        bucket="strategic_accumulator", from_month=date(2026, 1, 1)
    )
    assert any(r["country_iso3"] == "CHN" for r in rows)
    history = repo.fetch_cb_gold_reserves_history(
        country_iso3="CHN", to_month=date(2026, 3, 31), as_of_max=as_of
    )
    assert [r["obs_month"] for r in history] == [
        date(2025, 3, 31),
        date(2026, 3, 31),
    ]


def test_cot_round_trip_pins_release_date(repo: Repository) -> None:
    repo.insert_cot_gold_weekly(
        obs_date=date(2026, 5, 13),
        release_date=date(2026, 5, 16),
        mm_long=Decimal("210500"),
        mm_short=Decimal("85300"),
        mm_net=Decimal("125200"),
        comm_long=Decimal("180100"),
        comm_short=Decimal("295400"),
        comm_net=Decimal("-115300"),
        open_interest=Decimal("512000"),
        as_of=datetime.now(UTC),
        source_url=None,
    )
    rows = repo.fetch_cot_gold_weekly(
        from_release_date=date(2026, 5, 1),
        to_release_date=date(2026, 5, 20),
    )
    assert len(rows) == 1
    assert rows[0]["release_date"] == date(2026, 5, 16)
    assert rows[0]["mm_net"] == Decimal("125200")


def test_uw_gold_options_round_trip(repo: Repository) -> None:
    repo.insert_uw_gold_options_daily(
        ticker="GLD",
        obs_date=date(2026, 5, 16),
        atm_iv_30d=Decimal("0.21"),
        atm_iv_60d=Decimal("0.22"),
        put_25d_iv_30d=Decimal("0.27"),
        call_25d_iv_30d=Decimal("0.18"),
        skew_25d_30d=Decimal("0.09"),
        put_call_oi_ratio=None,
        dealer_gamma_est=None,
        as_of=datetime.now(UTC),
    )
    rows = repo.fetch_uw_gold_options_daily("GLD", from_date=date(2026, 5, 1))
    assert len(rows) == 1
    assert rows[0]["skew_25d_30d"] == Decimal("0.09")
