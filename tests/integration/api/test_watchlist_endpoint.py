"""GET /api/watchlist + POST/DELETE/PATCH watchlist CRUD."""

from __future__ import annotations


def test_get_watchlist_returns_placeholders_when_no_cards(
    client, seeded_db_empty_cards
):
    """All active watchlist tickers appear even before they have card rows —
    LEFT JOIN from watchlist so the UI can render 'not scanned yet'
    placeholders instead of an empty grid."""
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tickers"]) >= 1
    for card in body["tickers"]:
        assert "ticker" in card and "sector" in card
        # No scan run → scanned_at is null.
        assert card["scanned_at"] is None


def test_get_watchlist_returns_seeded_cards(client, seeded_db_with_cards):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tickers"]) >= 1
    # At least one ticker is fully scanned.
    scanned = [c for c in body["tickers"] if c["scanned_at"] is not None]
    assert len(scanned) >= 1
    card = scanned[0]
    for key in ("ticker", "sector", "setup", "returns", "gamma", "skew", "positioning"):
        assert key in card


def test_get_watchlist_includes_queue_summary_and_card_status(
    client, seeded_db_with_cards
):
    job = client.post("/api/watchlist/TSLA/rescan").json()

    r = client.get("/api/watchlist")

    assert r.status_code == 200
    body = r.json()
    assert body["queue"]["total"] == 1
    assert body["queue"]["queued"] == 1
    tsla = next(card for card in body["tickers"] if card["ticker"] == "TSLA")
    assert tsla["queue"]["job_id"] == job["job_id"]
    assert tsla["queue"]["status"] == "queued"
    assert tsla["queue"]["queue_position"] == 1


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


def test_get_watchlist_spots_returns_live_projection(client, seeded_db_with_cards):
    """GET /api/watchlist/spots returns the lightweight live-spot rows the
    LiveSpotsProvider poller consumes — only carded tickers, with spot,
    quoted-at, and the feed tag (xenon_ws | massive.com_ws)."""
    r = client.get("/api/watchlist/spots")
    assert r.status_code == 200
    spots = r.json()["spots"]
    assert len(spots) >= 1
    tsla = next(s for s in spots if s["ticker"] == "TSLA")
    from decimal import Decimal

    assert Decimal(tsla["spot"]) == Decimal("445.12")
    assert set(tsla.keys()) == {"ticker", "spot", "spot_quoted_at", "spot_source"}
