"""Daily OHLC pull: for every watchlist ticker, fetch the last N days from the
OHLC provider and upsert into uw_scan.daily_ohlc."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def ohlc_pull_once(repo, provider: OhlcProvider, lookback_days: int = 40) -> int:
    completed = 0
    end = date.today()
    start = end - timedelta(days=lookback_days * 2)  # weekend/holiday buffer
    for w in repo.list_active_watchlist():
        try:
            bars = provider.fetch_daily(w.ticker, start, end)
            for bar in bars:
                repo.upsert_daily_ohlc(
                    ticker=bar.ticker,
                    date=bar.date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    source="massive.com",
                )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("ohlc_pull failed for %s: %s", w.ticker, repr(exc))
    return completed
