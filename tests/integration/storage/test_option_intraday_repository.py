"""Integration tests for OptionIntradayBucketRepository against a real Postgres.

Verifies the PK contract (option_symbol, trade_date, start_time), the upsert
overwrite semantics on conflict, and the lookup-by-(option_symbol, trade_date)
read path used by the report assembler.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.models import OptionContractIntradayBucket
from uw_scan.storage.option_intraday_repository import OptionIntradayBucketRepository


def _bucket(minute: int, *, ask: int = 100) -> OptionContractIntradayBucket:
    return OptionContractIntradayBucket(
        start_time=datetime(2026, 5, 14, 13, minute, 0, tzinfo=UTC),
        open=Decimal("1.20"),
        high=Decimal("1.35"),
        low=Decimal("1.18"),
        close=Decimal("1.30"),
        avg_price=Decimal("1.27"),
        iv_high=Decimal("0.42"),
        iv_low=Decimal("0.39"),
        volume_ask_side=ask,
        volume_bid_side=40,
        volume_mid_side=5,
        volume_multi=0,
        premium_ask_side=Decimal("12700.00"),
        premium_bid_side=Decimal("5080.00"),
        premium_mid_side=Decimal("635.00"),
        premium_no_side=Decimal("0.00"),
    )


def test_upsert_then_fetch_round_trip(seeded_db_empty_cards) -> None:
    repo = OptionIntradayBucketRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    written = repo.upsert_buckets(
        "TSLA260515C00450000",
        date(2026, 5, 14),
        [_bucket(30), _bucket(31), _bucket(32)],
    )
    assert written == 3

    rows = repo.fetch_buckets("TSLA260515C00450000", date(2026, 5, 14))
    assert len(rows) == 3
    # Ordered ascending by start_time.
    assert rows[0]["start_time"].minute == 30
    assert rows[2]["start_time"].minute == 32
    assert rows[0]["volume_ask_side"] == 100
    assert rows[0]["close"] == Decimal("1.30")


def test_upsert_overwrites_on_conflict(seeded_db_empty_cards) -> None:
    """Re-running the worker job for the same (symbol, date, minute) must
    overwrite fields, not double-insert. UW restates minute bars when late
    prints clear and the freshest call should win."""
    repo = OptionIntradayBucketRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    sym, day = "AAPL260619P00180000", date(2026, 5, 14)

    repo.upsert_buckets(sym, day, [_bucket(30, ask=100)])
    repo.upsert_buckets(sym, day, [_bucket(30, ask=500)])

    rows = repo.fetch_buckets(sym, day)
    assert len(rows) == 1, "PK should collapse the two calls to one row"
    assert rows[0]["volume_ask_side"] == 500


def test_empty_iterable_returns_zero_and_writes_nothing(seeded_db_empty_cards) -> None:
    repo = OptionIntradayBucketRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    n = repo.upsert_buckets("NVDA260619C00200000", date(2026, 5, 14), [])
    assert n == 0
    assert repo.fetch_buckets("NVDA260619C00200000", date(2026, 5, 14)) == []


def test_fetch_scoped_by_symbol_and_date(seeded_db_empty_cards) -> None:
    repo = OptionIntradayBucketRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    sym_a, sym_b = "AAPL260619P00180000", "NVDA260619C00200000"
    day = date(2026, 5, 14)
    other_day = date(2026, 5, 15)

    repo.upsert_buckets(sym_a, day, [_bucket(30), _bucket(31)])
    repo.upsert_buckets(sym_b, day, [_bucket(30)])
    repo.upsert_buckets(sym_a, other_day, [_bucket(30)])

    rows = repo.fetch_buckets(sym_a, day)
    assert len(rows) == 2
    assert all(r["option_symbol"] == sym_a for r in rows)
    assert all(r["trade_date"] == day for r in rows)
