"""Integration tests for GET /api/stock/{ticker}/trade-insights."""

from __future__ import annotations


def test_trade_insights_endpoint_returns_404_without_run(client, seeded_db_empty_cards):
    r = client.get("/api/stock/NOPE/trade-insights")
    assert r.status_code == 404
    assert "no runs" in r.text
