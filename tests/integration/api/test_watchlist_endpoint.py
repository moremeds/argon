"""GET /api/watchlist + POST/DELETE/PATCH watchlist CRUD."""

from __future__ import annotations


def test_get_watchlist_returns_empty_when_no_cards(client, seeded_db_empty_cards):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert body["tickers"] == []


def test_get_watchlist_returns_seeded_cards(client, seeded_db_with_cards):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tickers"]) >= 1
    card = body["tickers"][0]
    for key in ("ticker", "sector", "setup", "returns", "gamma", "skew", "positioning"):
        assert key in card
    assert card["scanned_at"] is not None


def test_get_watchlist_filters_by_sector(client, seeded_db_with_cards):
    r = client.get("/api/watchlist?sector=Technology")
    assert r.status_code == 200
    for card in r.json()["tickers"]:
        assert card["sector"] == "Technology"


def test_get_watchlist_freshness_filter_keeps_recent(client, seeded_db_with_cards):
    r = client.get("/api/watchlist?fresh_within_minutes=60")
    assert r.status_code == 200
    # Fixture writes scanned_at = now → fresh within 60min → at least 1.
    assert len(r.json()["tickers"]) >= 1


def test_post_watchlist_adds_ticker(client, seeded_db_empty_cards):
    r = client.post(
        "/api/watchlist",
        json={"ticker": "ZZTEST", "sector": "ETF", "notes": "added via api"},
    )
    assert r.status_code == 201
    assert r.json()["ticker"] == "ZZTEST"


def test_delete_watchlist_soft_deletes(client, seeded_db_with_cards):
    r = client.delete("/api/watchlist/TSLA")
    assert r.status_code == 204
