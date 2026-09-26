"""Volatility tab v2 worker jobs.

Two daily jobs:
- daily_spy_ohlc_refresh: pull yesterday + today SPY rows, upsert.
- nightly_vol_analytics_rollup: re-derive vrp_daily + stock_analytics_daily
  for watchlist tickers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from uw_scan.cards import vol_series
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def daily_spy_ohlc_refresh(
    *,
    repo: Repository,
    api_key: str,
    tz: str = "America/New_York",
    telemetry_recorder: ExternalApiRequestRecorder | None = None,
    lookback_days: int = 2,
) -> None:
    """ET-anchored — host may live in any timezone (e.g. HKT), so date.today()
    would compute the wrong market date around the rollover (review I8).

    ``lookback_days`` defaults to the original hardcoded 2-day window, so the
    scheduler's call is unchanged; the gap healer passes a wider one to reach
    an older hole.
    """
    today = datetime.now(ZoneInfo(tz)).date()
    start = today - timedelta(days=max(2, lookback_days))
    with MassiveOhlcProvider(
        api_key=api_key,
        telemetry_recorder=telemetry_recorder,
        job_name="daily_spy_ohlc_refresh",
    ) as prov:
        bars = prov.fetch_daily("SPY", start=start, end=today)
    repo.upsert_index_ohlc_rows(bars)
    repo.conn.commit()
    log.info("daily_spy_ohlc_refresh: upserted %d rows", len(bars))


def _closes(repo: Repository, ticker: str, days: int) -> list[tuple]:
    # daily_ohlc (massive) is split-adjusted; `days` calendar days > trading rows.
    return [
        (r.date, float(r.close))
        for r in repo.list_daily_ohlc(ticker, limit=days)
        if r.close is not None
    ]


def nightly_vol_analytics_rollup(*, repo: Repository, days: int = 365) -> None:
    cards = repo.list_watchlist_cards()
    tickers = [c.ticker for c in cards]
    spy_history = repo.fetch_index_ohlc_series("SPY")
    # Inline import — avoids circular at module load (worker → reports → worker).
    from uw_scan.reports.volatility_series import (
        persist_stock_analytics,
        persist_vrp_daily,
    )

    for ticker in tickers:
        rv_history = repo.fetch_realized_vol_history(ticker, days=days)
        if not rv_history:
            continue
        # UW's realized_volatility is FORWARD RV (window t..t+20) — lookahead as a
        # time-t value. Replace it with trailing RV from split-adjusted closes.
        closes = vol_series.split_safe_prices(rv_history, _closes(repo, ticker, days))
        rv_history = vol_series.trailing_rv(rv_history, closes)
        vrp_df = vol_series.compute_vrp_series(rv_history)
        iv_of_iv_df = vol_series.compute_iv_of_iv(rv_history)
        # rvol / SPY-corr from the same split-safe closes, not UW's raw `price`.
        prices = [{"market_date": d, "price": c} for d, c in closes]
        rvol_df = vol_series.compute_rvol_and_percentile(prices)
        corr_df = vol_series.compute_stock_spy_corr(prices, spy_history)
        persist_vrp_daily(repo, ticker, vrp_df)
        persist_stock_analytics(repo, ticker, iv_of_iv_df, rvol_df, corr_df)
    repo.conn.commit()
    log.info("nightly_vol_analytics_rollup complete for %d tickers", len(tickers))
