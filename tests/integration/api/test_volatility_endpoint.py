"""Integration tests for GET /api/stock/{ticker}/volatility/series."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.models import RealizedVolRow
from uw_scan.sources.ohlc import OhlcBar


def _seed_history(repo, ticker: str, n: int = 100) -> None:
    today = date.today()
    base = today - timedelta(days=n)
    rv_rows = [
        RealizedVolRow(
            date=base + timedelta(days=i),
            price=Decimal(str(100 + i * 0.1)),
            implied_volatility=Decimal("0.50"),
            realized_volatility=Decimal("0.40"),
        )
        for i in range(n)
    ]
    repo.upsert_realized_vol_rows(ticker, rv_rows)
    spy_bars = [
        OhlcBar(
            ticker="SPY",
            date=base + timedelta(days=i),
            open=None,
            high=None,
            low=None,
            close=Decimal(str(500 + i * 0.5)),
            volume=None,
        )
        for i in range(n)
    ]
    repo.upsert_index_ohlc_rows(spy_bars)
    repo.conn.commit()


def test_volatility_series_endpoint_ready_when_fresh_history_present(
    client, seeded_db_empty_cards
):
    _seed_history(seeded_db_empty_cards, "TSLA", n=100)

    r = client.get("/api/stock/TSLA/volatility/series")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "TSLA"
    assert body["backfill_status"] == "ready"
    assert "header" in body
    assert "hv_iv_history" in body
    # Should have a non-trivial number of bars.
    assert len(body["hv_iv_history"]) >= 90


def test_volatility_series_endpoint_kicks_off_backfill_when_history_thin(
    client, seeded_db_empty_cards
):
    """No history at all → backfill_status == 'running'."""
    r = client.get("/api/stock/UNSEEDED/volatility/series")
    assert r.status_code == 200
    body = r.json()
    assert body["backfill_status"] == "running"


def test_volatility_series_empty_response_shape_is_safe(client, seeded_db_empty_cards):
    """Even with zero history, response defaults are non-None blocks
    (frontend dereferences .points / .bins directly — review I5)."""
    r = client.get("/api/stock/NEWTKR/volatility/series")
    body = r.json()
    # Empty defaults present, not None.
    assert body["regime_quadrant"] == {
        "points": [],
        "latest": None,
        "cutoff_corr": None,
    }
    assert body["iv_percentile_distribution"]["bins"] == []
    assert body["term_structure"] == []
    assert body["smile"] == []
    assert body["hv_iv_history"] == []
