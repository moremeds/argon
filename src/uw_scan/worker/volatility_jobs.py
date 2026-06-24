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
) -> None:
    """ET-anchored — host may live in any timezone (e.g. HKT), so date.today()
    would compute the wrong market date around the rollover (review I8)."""
    today = datetime.now(ZoneInfo(tz)).date()
    start = today - timedelta(days=2)
    with MassiveOhlcProvider(
        api_key=api_key,
        telemetry_recorder=telemetry_recorder,
        job_name="daily_spy_ohlc_refresh",
    ) as prov:
        bars = prov.fetch_daily("SPY", start=start, end=today)
    repo.upsert_index_ohlc_rows(bars)
    repo.conn.commit()
    log.info("daily_spy_ohlc_refresh: upserted %d rows", len(bars))


def nightly_vol_analytics_rollup(*, repo: Repository) -> None:
    cards = repo.list_watchlist_cards()
    tickers = [c.ticker for c in cards]
    spy_history = repo.fetch_index_ohlc_series("SPY")
    # Inline import — avoids circular at module load (worker → reports → worker).
    from uw_scan.reports.volatility_series import (
        _fill_rv_from_price,
        persist_stock_analytics,
        persist_vrp_daily,
    )

    for ticker in tickers:
        rv_history = repo.fetch_realized_vol_history(ticker, days=365)
        if not rv_history:
            continue
        # UW's realized_volatility column trails by weeks (null since ~2026-05-22),
        # which made vrp = iv - rv NaN and silently froze vrp_daily for ~90% of the
        # watchlist. Fill RV from the fresh price column — same convention the report
        # read-path (volatility_series) already uses — before deriving VRP.
        rv_history = _fill_rv_from_price(rv_history)
        vrp_df = vol_series.compute_vrp_series(rv_history)
        iv_of_iv_df = vol_series.compute_iv_of_iv(rv_history)
        rvol_df = vol_series.compute_rvol_and_percentile(
            [{"market_date": r["market_date"], "price": r["price"]} for r in rv_history]
        )
        corr_df = vol_series.compute_stock_spy_corr(
            [
                {"market_date": r["market_date"], "price": r["price"]}
                for r in rv_history
            ],
            spy_history,
        )
        persist_vrp_daily(repo, ticker, vrp_df)
        persist_stock_analytics(repo, ticker, iv_of_iv_df, rvol_df, corr_df)
    repo.conn.commit()
    log.info("nightly_vol_analytics_rollup complete for %d tickers", len(tickers))
