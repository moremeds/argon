"""Endpoints: /api/stock/{ticker}, /api/ohlc/{ticker}, /api/jobs/{id}, rescan."""

from __future__ import annotations

# ---- /api/stock ----------------------------------------------------------


def test_get_stock_404_for_unknown_ticker(client, seeded_db_empty_cards):
    r = client.get("/api/stock/ZZZZZZ")
    assert r.status_code == 404


def test_get_stock_runs_returns_history(client, seeded_db_with_cards):
    r = client.get("/api/stock/TSLA/runs")
    assert r.status_code == 200
    runs = r.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1
    assert "run_id" in runs[0] and "scanned_at" in runs[0]


def test_get_stock_runs_empty_for_unknown_ticker(client, seeded_db_empty_cards):
    r = client.get("/api/stock/ZZZZZZ/runs")
    assert r.status_code == 200
    assert r.json() == []


# ---- /api/ohlc -----------------------------------------------------------


def test_get_ohlc_returns_recent_bars(client, seeded_db_with_ohlc):
    r = client.get("/api/ohlc/AAPL?days=10")
    assert r.status_code == 200
    bars = r.json()
    assert isinstance(bars, list)
    assert len(bars) <= 10
    assert all("date" in b and "close" in b for b in bars)


def test_get_ohlc_default_30_days(client, seeded_db_with_ohlc):
    r = client.get("/api/ohlc/AAPL")
    assert r.status_code == 200
    assert len(r.json()) <= 30


# ---- /api/jobs + rescan --------------------------------------------------


def test_post_rescan_enqueues_job(client, seeded_db_with_cards):
    r = client.post("/api/watchlist/TSLA/rescan")
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_get_job_status(client, seeded_db_with_cards):
    enqueued = client.post("/api/watchlist/TSLA/rescan").json()
    r = client.get(f"/api/jobs/{enqueued['job_id']}")
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "running", "done")


def test_get_unknown_job_404(client, seeded_db_empty_cards):
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
