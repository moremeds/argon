"""GET /api/health — ok/unhealthy/reason states."""

from __future__ import annotations


def test_health_ok_when_recent_scan(client, seeded_db_with_cards):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "up"
    assert body["scheduler_lag_seconds"] is not None
    assert body["last_full_scan_at"] is not None


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
