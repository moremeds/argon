"""GET /api/health — ok/unhealthy/reason states."""

from __future__ import annotations

from datetime import UTC, datetime


def test_health_ok_when_recent_scan(client, seeded_db_with_cards):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "up"
    assert body["scheduler_lag_seconds"] is not None
    assert body["last_full_scan_at"] is not None


def test_health_includes_provider_usage_stats(client, seeded_db_empty_cards):
    now = datetime.now(UTC)
    seeded_db_empty_cards.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=25,
        official_daily_count=33,
        official_daily_limit=1000,
    )
    seeded_db_empty_cards.insert_external_api_request(
        provider="massive",
        endpoint_key="daily_ohlc",
        method="GET",
        path="/v2/aggs/ticker/AAPL/range/1/day/2026-05-13/2026-05-14",
        ticker="AAPL",
        params={},
        status_code=503,
        status_family="5xx",
        started_at=now,
        finished_at=now,
        latency_ms=25,
    )
    seeded_db_empty_cards.conn.commit()

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["http_2xx"] == 1
    assert body["http_4xx"] == 0
    assert body["http_5xx"] == 1
    assert body["latency_p95_ms"] == 25
    assert body["uw_today"] == 33


def test_health_unhealthy_when_no_scans(client, seeded_db_empty_cards):
    r = client.get("/api/health")
    body = r.json()
    assert body["ok"] is False
    assert "no successful full scan" in (body.get("reason") or "")


def test_health_unhealthy_when_lag_exceeds_2x_interval(
    client, seeded_db_with_stale_run
):
    r = client.get("/api/health")
    body = r.json()
    assert body["ok"] is False
    assert "exceeds" in (body.get("reason") or "")
