"""Integration tests for bulk intraday_quote upserts (Phase 1, Task 1.3)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def test_bulk_upsert_intraday_quotes_atomic(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    rows = [
        ("AAPL", Decimal("189.42"), ts, "massive.com_ws"),
        ("MSFT", Decimal("425.10"), ts, "massive.com_ws"),
        ("SPY", Decimal("532.55"), ts, "massive.com_ws"),
    ]
    repo.bulk_upsert_intraday_quotes(rows)
    repo._conn.commit()  # helpers don't self-commit — caller controls txn
    for ticker, price, quoted_at, _source in rows:
        q = repo.get_intraday_quote(ticker)
        assert q is not None
        assert q.price == price
        assert q.quoted_at == quoted_at


def test_bulk_upsert_intraday_quotes_overwrites(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts1 = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 1, tzinfo=timezone.utc)
    repo.bulk_upsert_intraday_quotes(
        [("AAPL", Decimal("189.42"), ts1, "massive.com_ws")]
    )
    repo._conn.commit()
    repo.bulk_upsert_intraday_quotes(
        [("AAPL", Decimal("189.50"), ts2, "massive.com_ws")]
    )
    repo._conn.commit()
    q = repo.get_intraday_quote("AAPL")
    assert q.price == Decimal("189.50")
    assert q.quoted_at == ts2


def test_bulk_upsert_intraday_quotes_empty_is_noop(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.bulk_upsert_intraday_quotes([])
    # Nothing inserted; no exception.


def test_bulk_upsert_intraday_quotes_accepts_orphan_tickers(seeded_db_empty_cards):
    """A3 (adversarial fix): FK from intraday_quote.ticker to watchlist(ticker)
    was dropped in migration 052 so a ticker missing from the watchlist
    (e.g. removed mid-session) does NOT block the entire batch."""
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    # ORPHANXYZ is not in the watchlist seed — must still insert
    repo.bulk_upsert_intraday_quotes(
        [("ORPHANXYZ", Decimal("1.23"), ts, "massive.com_ws")]
    )
    repo._conn.commit()
    q = repo.get_intraday_quote("ORPHANXYZ")
    assert q is not None
    assert q.price == Decimal("1.23")


def test_upsert_intraday_quote_with_source(seeded_db_empty_cards):
    """Non-bulk variant still self-commits + accepts the source kwarg."""
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    repo.upsert_intraday_quote("AAPL", Decimal("189.42"), ts, source="massive.com_ws")
    q = repo.get_intraday_quote("AAPL")
    assert q.price == Decimal("189.42")
