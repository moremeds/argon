"""Integration tests for volatility worker jobs (spec 2026-05-13)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from uw_scan.models import RealizedVolRow
from uw_scan.sources.ohlc import OhlcBar
from uw_scan.worker.volatility_jobs import (
    daily_spy_ohlc_refresh,
    nightly_vol_analytics_rollup,
)


def test_daily_spy_ohlc_refresh_writes_today(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    today = date.today()
    fake_prov = MagicMock()
    fake_prov.fetch_daily.return_value = [
        OhlcBar(
            ticker="SPY",
            date=today,
            open=None,
            high=None,
            low=None,
            close=Decimal("500"),
            volume=None,
        ),
    ]
    fake_prov.__enter__ = lambda self: self
    fake_prov.__exit__ = lambda self, *_: None

    monkeypatch.setattr(
        "uw_scan.worker.volatility_jobs.MassiveOhlcProvider",
        lambda **_: fake_prov,
    )
    daily_spy_ohlc_refresh(repo=repo, api_key="dummy")

    rows = repo.fetch_index_ohlc_series("SPY", start=today, end=today)
    assert len(rows) == 1
    assert rows[0]["close"] == Decimal("500")


def test_nightly_vol_analytics_rollup_persists_for_watchlist_tickers(
    seeded_db_with_cards,
):
    """For each watchlist ticker with RV history, vrp_daily and
    stock_analytics_daily rows are written."""
    repo = seeded_db_with_cards

    today = date.today()
    base = today - timedelta(days=60)
    rv_rows = [
        RealizedVolRow(
            date=base + timedelta(days=i),
            price=Decimal(str(100 + i * 0.1)),
            implied_volatility=Decimal("0.50"),
            realized_volatility=Decimal("0.40"),
        )
        for i in range(60)
    ]
    repo.upsert_realized_vol_rows("TSLA", rv_rows)

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
        for i in range(60)
    ]
    repo.upsert_index_ohlc_rows(spy_bars)
    repo.conn.commit()

    nightly_vol_analytics_rollup(repo=repo)

    vrp = repo.fetch_vrp_daily_series("TSLA", limit=100)
    assert len(vrp) > 0
    stock_an = repo.fetch_stock_analytics_series("TSLA", limit=100)
    assert len(stock_an) > 0


def test_nightly_vol_analytics_rollup_fills_rv_when_uw_rv_null(
    seeded_db_with_cards,
):
    """Regression: UW's realized_volatility column trails for weeks (stored
    NULL). That made vrp = iv - rv NaN and silently froze vrp_daily for ~90% of
    the watchlist (2026-05-22 onward). The rollup must fill RV from the fresh
    price column so vrp_daily is still written."""
    repo = seeded_db_with_cards

    today = date.today()
    base = today - timedelta(days=60)
    # IV + price present, but realized_volatility is NULL — the UW gap condition.
    rv_rows = [
        RealizedVolRow(
            date=base + timedelta(days=i),
            price=Decimal(str(100 + i * 0.3)),
            implied_volatility=Decimal("0.50"),
            realized_volatility=None,
        )
        for i in range(60)
    ]
    repo.upsert_realized_vol_rows("TSLA", rv_rows)
    repo.conn.commit()

    nightly_vol_analytics_rollup(repo=repo)

    vrp = repo.fetch_vrp_daily_series("TSLA", limit=100)
    assert len(vrp) > 0, (
        "vrp_daily must populate even when UW realized_volatility is NULL"
    )
