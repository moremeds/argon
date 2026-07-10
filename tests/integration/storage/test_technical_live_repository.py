from __future__ import annotations

import datetime as dt

from uw_scan.storage.technical_live_repository import TechnicalLiveRepository


def test_upsert_and_fetch(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    live = TechnicalLiveRepository(repo.conn, schema=repo._schema)
    ts = dt.datetime(2026, 7, 9, 15, 30, tzinfo=dt.timezone.utc)
    live.upsert(
        "NVDA",
        ts,
        123.45,
        "xenon_ws",
        {"z": 1.2, "dual_macd": {"trend_state": "BULLISH"}},
    )
    got = live.fetch("NVDA")
    assert got["spot"] == 123.45
    assert got["spot_source"] == "xenon_ws"
    assert got["payload"]["dual_macd"]["trend_state"] == "BULLISH"


def test_upsert_replaces(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    live = TechnicalLiveRepository(repo.conn, schema=repo._schema)
    t1 = dt.datetime(2026, 7, 9, 15, 0, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2026, 7, 9, 15, 5, tzinfo=dt.timezone.utc)
    live.upsert("AAPL", t1, 100.0, "xenon_ws", {"z": 0.1})
    live.upsert("AAPL", t2, 101.0, "massive.com_ws", {"z": 0.2})
    got = live.fetch("AAPL")
    assert got["spot"] == 101.0 and got["captured_at"] == t2
