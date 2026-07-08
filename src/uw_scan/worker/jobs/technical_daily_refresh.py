"""Nightly technicals refresh: apex daily bars -> full recomputed series +
latest-day detail/forward-return table per watchlist ticker. Idempotent."""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.cards.technicals import build_technical_series, build_technical_snapshot
from uw_scan.config import Settings
from uw_scan.sources.apex import fetch_daily_bars
from uw_scan.storage.repository import Repository
from uw_scan.storage.technicals_repository import TechnicalsRepository, series_records

log = logging.getLogger(__name__)


def technical_daily_refresh(
    *,
    repo: Repository,
    settings: Settings,
    ticker_filter: list[str] | None = None,
) -> dict[str, Any]:
    trepo = TechnicalsRepository(repo.conn, schema=settings.db_schema)
    if ticker_filter is not None:
        watch = [t.upper() for t in ticker_filter]
    else:
        watch = sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})
    tickers = sorted(set(watch) | {"SPY"})  # SPY = RS benchmark, always refreshed
    spy_bars = fetch_daily_bars("SPY")
    ok = skipped_thin = failed = 0
    for t in tickers:
        try:
            bars = spy_bars if t == "SPY" else fetch_daily_bars(t)
            bench = spy_bars if t != "SPY" else None
            snap = build_technical_snapshot(bars, bench)
            if snap is None:
                skipped_thin += 1
                log.info(
                    "technical_daily_refresh: %s thin history (%d bars), skipped",
                    t,
                    len(bars),
                )
                continue
            series = build_technical_series(bars, bench)
            trepo.upsert_series(t, series_records(series))
            detail = {
                k: snap[k]
                for k in (
                    "bars_n",
                    "dist_pct",
                    "composite",
                    "kinematics",
                    "sigmoid",
                    "distribution",
                    "rsi",
                    "macd",
                    "rs",
                )
            }
            trepo.set_latest_detail(
                t,
                snap["as_of"],
                detail=detail,
                forward_returns=snap["forward_returns"],
            )
            ok += 1
        except Exception as exc:
            failed += 1
            log.warning("technical_daily_refresh failed for %s: %s", t, repr(exc))
    summary = {
        "ok": ok,
        "skipped_thin": skipped_thin,
        "failed": failed,
        "tickers": len(tickers),
    }
    log.info("technical_daily_refresh: %s", summary)
    return summary
