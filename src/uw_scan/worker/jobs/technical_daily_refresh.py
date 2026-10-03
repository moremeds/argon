"""Nightly technicals refresh: apex daily bars -> full recomputed series +
latest-day detail/forward-return table per watchlist ticker. Idempotent."""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.cards.technicals import (
    build_technical_series,
    build_technical_snapshot,
    overlay_recent_ohlc,
)
from uw_scan.config import Settings
from uw_scan.sources.apex import fetch_daily_bars
from uw_scan.sources.source_errors import SourceUnavailable
from uw_scan.storage.repository import Repository
from uw_scan.storage.technicals_repository import TechnicalsRepository, series_records

log = logging.getLogger(__name__)

# The recent, more-trusted daily-OHLCV overlay window. ohlc_pull stores ~40
# sessions of massive.com daily_ohlc; 60 covers the full stored window with
# slack. Older dates than this fall through to apex's deep history untouched.
_OHLC_OVERLAY_LIMIT = 60


def _recent_ohlc(repo: Repository, ticker: str) -> list:
    """The recent massive daily_ohlc window for `ticker`, [] on any failure.

    Never-raise + rollback so a daily_ohlc read hiccup degrades the ticker to
    apex-only instead of failing (or poisoning) the whole refresh loop."""
    try:
        return repo.list_daily_ohlc(ticker.upper(), limit=_OHLC_OVERLAY_LIMIT)
    except Exception as exc:
        repo.conn.rollback()
        log.debug(
            "technical_daily_refresh: daily_ohlc read failed for %s: %s",
            ticker,
            repr(exc),
        )
        return []


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
    # SPY reconciled once: it is both a displayed ticker and the RS benchmark, so
    # the ratio's two legs share the same corrected close series. Apex down for
    # SPY raises SourceUnavailable out of the job: every other ticker's RS
    # columns would be computed against an empty benchmark.
    apex_url = settings.apex_api_url
    spy_apex = fetch_daily_bars("SPY", base_url=apex_url)
    spy_bars = overlay_recent_ohlc(spy_apex, _recent_ohlc(repo, "SPY"))
    ok = skipped_thin = no_data = source_unavailable = failed = 0
    last_unavailable: SourceUnavailable | None = None
    for t in tickers:
        try:
            if t == "SPY":
                apex_bars, bars = spy_apex, spy_bars
                bench = None
            else:
                apex_bars = fetch_daily_bars(t, base_url=apex_url)
                bars = overlay_recent_ohlc(apex_bars, _recent_ohlc(repo, t))
                bench = spy_bars
            series = build_technical_series(bars, bench)
            snap = build_technical_snapshot(bars, bench, series=series)
            if snap is None:
                if not apex_bars:
                    # apex answered 2xx with no bars. (A refused read -- 503
                    # adjusted_unavailable, 404, transport -- raises
                    # SourceUnavailable and is counted below.) The ~60-session
                    # daily_ohlc overlay alone is under the 210-bar floor, so do
                    # not charge this to thin history either.
                    no_data += 1
                    log.warning(
                        "technical_daily_refresh: %s apex returned no bars — "
                        "series will freeze at its last good date",
                        t,
                    )
                    continue
                skipped_thin += 1
                log.info(
                    "technical_daily_refresh: %s thin history (%d bars), skipped",
                    t,
                    len(bars),
                )
                continue
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
                    "dual_macd",
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
        except SourceUnavailable as exc:
            # A missing livewire artifact (503 adjusted_unavailable) is why MSTR
            # froze at 2026-07-15 for 26 sessions with only an INFO line: a name
            # with 2006 rows of history does not have "thin history", it has no
            # source. One ticker's outage does not fail the run.
            # No rollback: the fetch raised before this ticker wrote anything,
            # and a rollback here would also drop an uncommitted search_path.
            source_unavailable += 1
            last_unavailable = exc
            log.warning(
                "technical_daily_refresh: %s source unavailable — series will "
                "freeze at its last good date: %s",
                t,
                repr(exc),
            )
        except Exception as exc:
            failed += 1
            # Clear any aborted transaction so the next ticker (and, for the
            # on-demand endpoint, the follow-up read on this shared connection)
            # isn't poisoned by "current transaction is aborted".
            repo.conn.rollback()
            log.warning("technical_daily_refresh failed for %s: %s", t, repr(exc))
    summary = {
        "ok": ok,
        "skipped_thin": skipped_thin,
        "no_data": no_data,
        "source_unavailable": source_unavailable,
        "failed": failed,
        "tickers": len(tickers),
    }
    log.info("technical_daily_refresh: %s", summary)
    # Unit = one ticker: an outage on SOME tickers is a partial run; an outage
    # on every attempted ticker (none succeeded) is a failed run (I-15).
    if ok == 0 and last_unavailable is not None:
        raise SourceUnavailable(
            "apex",
            f"technical_daily_refresh: {source_unavailable}/{len(tickers)} tickers "
            f"source-unavailable, none succeeded; last: {last_unavailable.detail}",
        ) from last_unavailable
    return summary
