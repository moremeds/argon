"""/api/health surfaces WS consumer status (Phase 5, Task 5.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def test_health_includes_ws_consumer_when_healthy(
    client: TestClient, seeded_db_empty_cards
):
    """Recent heartbeat → ws_consumer present, healthy true, counts surface."""
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    repo.record_ws_heartbeat(
        last_tick_at=ts,
        last_flush_at=ts,
        ticks_received_delta=10,
        ticks_flushed_delta=10,
    )
    repo._conn.commit()

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "ws_consumer" in body
    assert body["ws_consumer"] is not None
    assert body["ws_consumer"]["ticks_received"] == 10
    assert body["ws_consumer"]["ticks_flushed"] == 10
    assert body["ws_consumer"]["healthy"] is True
    # last_tick_age_seconds is computed in seconds since last_tick_at; should
    # be near zero immediately after the heartbeat write.
    assert body["ws_consumer"]["last_tick_age_seconds"] is not None
    assert body["ws_consumer"]["last_tick_age_seconds"] < 5


def test_health_ws_consumer_uses_fresh_flush_for_delayed_feed(
    client: TestClient, seeded_db_empty_cards, monkeypatch
):
    """Delayed event time is healthy when the consumer is actively flushing."""
    from uw_scan.worker import market_session

    monkeypatch.setattr(
        market_session, "current_market_date", lambda *_a, **_k: datetime.now().date()
    )
    repo = seeded_db_empty_cards
    now = datetime.now(timezone.utc)
    repo.record_ws_heartbeat(
        last_tick_at=now - timedelta(minutes=15),
        last_flush_at=now,
        ticks_received_delta=10,
        ticks_flushed_delta=10,
    )
    repo._conn.commit()

    body = client.get("/api/health").json()

    assert body["ws_consumer"]["healthy"] is True
    assert body["ws_consumer"]["reason"] is None
    assert body["ws_consumer"]["last_tick_age_seconds"] > 14 * 60


def test_health_ws_consumer_null_state_outside_session(
    client: TestClient, seeded_db_empty_cards, monkeypatch
):
    """No ticks yet + market closed → healthy=True with 'market closed' reason."""
    # Force in_session=False by monkeypatching current_market_date to return None.
    from uw_scan.worker import market_session

    monkeypatch.setattr(market_session, "current_market_date", lambda *_a, **_k: None)

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ws_consumer"]["healthy"] is True
    assert body["ws_consumer"]["reason"] == "market closed"
    assert body["ws_consumer"]["ticks_received"] == 0
