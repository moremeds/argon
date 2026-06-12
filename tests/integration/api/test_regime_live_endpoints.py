"""Live/intraday/history regime endpoints.

The live endpoints check quote staleness against real wall-clock
(`load_live_quotes` defaults `now=datetime.now`), so quotes are seeded
RELATIVE to now — fresh quotes a few seconds old, stale quotes days old.
The fixed-date history seed still works: `run_live` splices today's ET
date onto the 130 seeded bars, and COR1M (no quote) carries forward.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.integration.test_regime_live_compute import _seed


def _seed_quotes(repo, quoted_at: datetime) -> None:
    repo.bulk_upsert_intraday_quotes(
        [
            ("VIX", Decimal("25.5"), quoted_at, "xenon_ws"),
            ("VVIX", Decimal("112.0"), quoted_at, "xenon_ws"),
            ("SPX", Decimal("7300.0"), quoted_at, "xenon_ws"),
            ("HYG", Decimal("78.90"), quoted_at, "xenon_ws"),
        ]
    )
    repo.conn.commit()


def test_cri_live_returns_live_basis(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo.conn)
    _seed_quotes(repo, datetime.now(timezone.utc))  # fresh: well inside 900s
    r = client.get("/api/regime/cri/live")
    assert r.status_code == 200
    body = r.json()
    assert body["basis"] == "live"
    assert body["vix"] == 25.5
    assert "VIX" in body["live_quotes"]
    assert "COR1M" in body["carried_forward"]


def test_cri_live_falls_back_to_eod_when_stale(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo.conn)
    _seed_quotes(repo, datetime.now(timezone.utc) - timedelta(days=2))  # stale
    r = client.get("/api/regime/cri/live")
    assert r.status_code == 200
    assert r.json()["basis"] == "eod"  # graceful degradation, status may be empty


def test_cri_intraday_and_history_shapes(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo.conn)
    _seed_quotes(repo, datetime.now(timezone.utc))
    client.get("/api/regime/cri/live")  # request-time compute does NOT persist
    r = client.get("/api/regime/cri/intraday?sessions=5")
    assert r.status_code == 200
    assert r.json()["sessions"] == []  # only the 5-min job persists live rows
    r2 = client.get("/api/regime/cri/history?days=90")
    assert r2.status_code == 200
    assert "rows" in r2.json()


def test_vcg_live_and_quotes(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo.conn)
    _seed_quotes(repo, datetime.now(timezone.utc))
    r = client.get("/api/regime/vcg/live")
    assert r.status_code == 200
    assert r.json()["basis"] == "live"
    assert r.json()["signal"]["credit_price"] == 78.9
    rq = client.get("/api/regime/quotes")
    assert rq.status_code == 200
    body = rq.json()
    assert body["quotes"]["VIX"]["price"] == 25.5
