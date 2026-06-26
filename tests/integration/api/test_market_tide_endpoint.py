"""GET /api/regime/market-tide — read path over market_tide_snapshots.

Seeds REAL observed UW bars (as-of 2026-06-25 ET) + real SPY 735.45, then
asserts the endpoint groups them into one session with the spot overlay.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.storage.market_tide_snapshot_repository import (
    MarketTideSnapshotRepository,
)

ET = timezone(timedelta(hours=-4))
_D = date(2026, 6, 25)


def _ts(h: int, m: int) -> datetime:
    return datetime(2026, 6, 25, h, m, tzinfo=ET)


_BARS = [
    {
        "data_date": _D,
        "ts": _ts(9, 30),
        "net_call_premium": Decimal("117491737.00"),
        "net_put_premium": Decimal("19962547.00"),
        "net_volume": -58008,
    },
    {
        "data_date": _D,
        "ts": _ts(16, 10),
        "net_call_premium": Decimal("40110157.00"),
        "net_put_premium": Decimal("192437487.00"),
        "net_volume": -1158600,
    },
]


def test_market_tide_endpoint(seeded_db_empty_cards, client):
    repo = seeded_db_empty_cards
    r = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
    r.upsert_bars(_BARS)
    r.set_spot(data_date=_D, ts=_ts(16, 10), spot=Decimal("735.45"), spot_ticker="SPY")

    resp = client.get("/api/regime/market-tide?sessions=5")
    assert resp.status_code == 200
    data = resp.json()

    assert data["spot_ticker"] == "SPY"
    assert len(data["sessions"]) == 1
    pts = data["sessions"][0]["points"]
    assert len(pts) == 2
    assert pts[0]["net_call_premium"] == 117491737.0
    assert pts[-1]["net_put_premium"] == 192437487.0
    assert pts[-1]["spot"] == 735.45
    assert data["as_of"] is not None


def test_market_tide_endpoint_empty(seeded_db_empty_cards, client):
    """Empty `sessions` is a valid response when no rows exist.

    Takes seeded_db_empty_cards purely to reset market_tide_snapshots to the
    empty baseline (the client-only fixture does not reset between tests)."""
    assert (
        MarketTideSnapshotRepository(
            seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
        ).fetch_sessions()
        == []
    )
    resp = client.get("/api/regime/market-tide")
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []
