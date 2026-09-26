"""Daily OHLC pull: for every watchlist ticker, fetch the last N days from the
OHLC provider and upsert into uw_scan.daily_ohlc."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)

# massive returns split-adjusted closes, but only for the window requested. After a
# split, stored closes older than the window stay unadjusted, and the series jumps
# at the window edge (CRWD 402 -> 99.6 on prod, 2026-04). A fetched close that
# disagrees with the stored one for the same date means the provider restated
# history, so the ticker's whole stored range is re-pulled.
_RESTATE_TOLERANCE = 0.01


def _restated(repo, ticker: str, bars) -> bool:
    stored = {
        r.date: r.close for r in repo.list_daily_ohlc(ticker, limit=len(bars) + 10)
    }
    return any(
        stored.get(b.date)
        and abs(float(b.close) / float(stored[b.date]) - 1) > _RESTATE_TOLERANCE
        for b in bars
    )


def ohlc_pull_once(
    repo,
    provider: OhlcProvider,
    lookback_days: int = 40,
    *,
    ticker_filter: Callable[[str], bool] | None = None,
) -> int:
    completed = 0
    end = date.today()
    start = end - timedelta(days=lookback_days * 2)  # weekend/holiday buffer
    for w in repo.list_active_watchlist():
        if ticker_filter is not None and not ticker_filter(w.ticker):
            logger.debug("ohlc_pull skipped %s outside this worker shard", w.ticker)
            continue
        try:
            bars = provider.fetch_daily(w.ticker, start, end)
            if bars and _restated(repo, w.ticker, bars):
                first = min(start, repo.earliest_daily_ohlc_date(w.ticker) or start)
                logger.warning(
                    "ohlc_pull %s: provider restated history (split?), re-pulling from %s",
                    w.ticker,
                    first,
                )
                bars = provider.fetch_daily(w.ticker, first, end)
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
