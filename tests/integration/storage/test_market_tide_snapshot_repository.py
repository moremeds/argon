"""MarketTideSnapshotRepository roundtrip + the subtle conflict-preserve-spot
behaviour the realtime worker depends on.

Fixtures are REAL observed UW market-tide bars (as-of 2026-06-25 ET) and the
real SPY close 735.45 (apex 5m bar, 2026-06-24) — frozen, not synthetic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.storage.market_tide_snapshot_repository import (
    MarketTideSnapshotRepository,
)

ET = timezone(timedelta(hours=-4))  # EDT, June
_D = date(2026, 6, 25)


def _ts(h: int, m: int) -> datetime:
    return datetime(2026, 6, 25, h, m, tzinfo=ET)


# Real observed bars from GET /api/market/market-tide?date=2026-06-25.
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
        "ts": _ts(9, 35),
        "net_call_premium": Decimal("186599017.00"),
        "net_put_premium": Decimal("26149249.00"),
        "net_volume": -64529,
    },
    {
        "data_date": _D,
        "ts": _ts(16, 10),
        "net_call_premium": Decimal("40110157.00"),
        "net_put_premium": Decimal("192437487.00"),
        "net_volume": -1158600,
    },
]


def test_upsert_and_fetch_sessions(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
    assert r.upsert_bars(_BARS) == 3

    sessions = r.fetch_sessions(sessions=5)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["date"] == _D
    pts = s["points"]
    assert len(pts) == 3
    # ASC by ts.
    assert pts[0]["net_call_premium"] == 117491737.0
    assert pts[-1]["net_put_premium"] == 192437487.0
    assert pts[0]["net_volume"] == -58008
    # No spot captured yet (backfill / pre-stamp).
    assert all(p["spot"] is None for p in pts)


def test_set_spot_survives_reupsert(seeded_db_empty_cards):
    """The worker re-fetches the full day every 5 min; a re-upsert must NOT
    clobber a spot already stamped onto a bar by an earlier tick."""
    repo = seeded_db_empty_cards
    r = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
    r.upsert_bars(_BARS)

    assert r.set_spot(
        data_date=_D, ts=_ts(16, 10), spot=Decimal("735.45"), spot_ticker="SPY"
    )
    # Re-upsert the same bars (idempotent worker tick).
    r.upsert_bars(_BARS)

    sessions = r.fetch_sessions(sessions=5)
    pts = sessions[0]["points"]
    last = next(p for p in pts if p["spot"] is not None)
    assert last["spot"] == 735.45
    assert last["spot_ticker"] == "SPY"
    # Earlier bars stay null.
    assert sum(1 for p in pts if p["spot"] is not None) == 1


def test_fetch_sessions_limit_and_order(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = MarketTideSnapshotRepository(repo.conn, schema=repo._schema)
    r.upsert_bars(_BARS)
    # A second, earlier session.
    prev = date(2026, 6, 24)
    r.upsert_bars(
        [
            {
                "data_date": prev,
                "ts": datetime(2026, 6, 24, 9, 30, tzinfo=ET),
                "net_call_premium": Decimal("90000000.00"),
                "net_put_premium": Decimal("60000000.00"),
                "net_volume": 1000,
            },
        ]
    )
    sessions = r.fetch_sessions(sessions=1)
    assert len(sessions) == 1
    assert sessions[0]["date"] == _D  # most recent only

    both = r.fetch_sessions(sessions=5)
    assert [s["date"] for s in both] == [prev, _D]  # ASC
