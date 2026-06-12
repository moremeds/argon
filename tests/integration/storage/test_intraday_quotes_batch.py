"""get_intraday_quotes — batch read for the regime live compute."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def test_get_intraday_quotes_returns_only_requested(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = datetime.now(timezone.utc)
    repo.bulk_upsert_intraday_quotes(
        [
            ("VIX", Decimal("22.22"), now, "xenon_ws"),
            ("HYG", Decimal("79.75"), now, "xenon_ws"),
            ("AAPL", Decimal("212.10"), now, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    rows = repo.get_intraday_quotes(["VIX", "HYG", "COR1M"])
    by_ticker = {r.ticker: r for r in rows}
    assert set(by_ticker) == {"VIX", "HYG"}  # COR1M has no quote; AAPL not asked
    assert by_ticker["VIX"].price == Decimal("22.22")
    assert by_ticker["VIX"].source == "xenon_ws"


def test_get_intraday_quotes_empty_input(seeded_db_empty_cards):
    assert seeded_db_empty_cards.get_intraday_quotes([]) == []
