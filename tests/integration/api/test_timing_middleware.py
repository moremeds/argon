"""The request-timing monitor tags every response with X-Response-Time-ms."""

from __future__ import annotations


def test_response_carries_timing_header(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert "X-Response-Time-ms" in resp.headers
    assert int(resp.headers["X-Response-Time-ms"]) >= 0
