"""GET /api/watchlist/queue — thin queue-summary endpoint for QueueProgress polling."""

from __future__ import annotations


def test_queue_endpoint_returns_summary_shape_empty_db(client, seeded_db_empty_cards):
    """Empty DB returns the QueueSummary shape with all-zero counts."""
    r = client.get("/api/watchlist/queue")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"total", "queued", "running", "oldest_requested_at"}
    assert body["total"] == 0
    assert body["queued"] == 0
    assert body["running"] == 0
    assert body["oldest_requested_at"] is None


def test_queue_endpoint_does_not_return_tickers_or_meta(client, seeded_db_with_cards):
    """The endpoint must not include any of the heavy watchlist fields —
    this is the whole point: cheap polling."""
    r = client.get("/api/watchlist/queue")
    body = r.json()
    assert "tickers" not in body
    assert "scanned_at_min" not in body
    assert "scanned_at_max" not in body
    assert "scheduler_lag_seconds" not in body


def test_queue_endpoint_counts_active_rescan(client, seeded_db_with_cards):
    """After POSTing a rescan, the queue summary reflects it."""
    client.post("/api/watchlist/TSLA/rescan")
    r = client.get("/api/watchlist/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["queued"] == 1
    assert body["oldest_requested_at"] is not None
