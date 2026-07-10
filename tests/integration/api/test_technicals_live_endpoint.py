from __future__ import annotations

import datetime as dt

from uw_scan.storage.technical_live_repository import TechnicalLiveRepository


def test_live_endpoint_returns_cached(client, seeded_db_empty_cards):
    live = TechnicalLiveRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    live.upsert(
        "NVDA",
        dt.datetime(2026, 7, 9, 15, 30, tzinfo=dt.timezone.utc),
        123.45,
        "xenon_ws",
        {
            "z": 1.2,
            "z_band": "STRETCHED HIGH",
            "dual_macd": {"trend_state": "BULLISH", "tactical_signal": "NONE"},
            "composite": 0.4,
        },
    )
    resp = client.get("/api/stock/NVDA/technicals/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["spot_source"] == "xenon_ws"
    assert body["dual_macd"]["trend_state"] in {
        "BULLISH",
        "BEARISH",
        "IMPROVING",
        "DETERIORATING",
    }


def test_live_endpoint_absent_is_unavailable(client):
    resp = client.get("/api/stock/ZZZZ/technicals/live")
    assert resp.status_code == 200
    assert resp.json()["available"] is False
