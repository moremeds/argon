"""Live technicals coverage: splice the latest WS intraday_quote as today's
provisional daily close, recompute the fast-moving technicals, cache per
ticker. Mirrors regime_live — DB-read only, zero provider spend."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from uw_scan.cards.technicals import live_technical_snapshot
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.storage.technical_live_repository import TechnicalLiveRepository
from uw_scan.storage.technicals_repository import TechnicalsRepository

log = logging.getLogger(__name__)

_MIN_BARS = 210  # same floor as build_technical_snapshot


def technical_live_scan(
    repo: Repository,
    settings: Settings,
    *,
    ticker_filter: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    max_age = settings.technical_live_quote_max_age_seconds
    today_et = now.astimezone(ZoneInfo(settings.rth_tz)).date()
    trepo = TechnicalsRepository(repo.conn, schema=settings.db_schema)
    live = TechnicalLiveRepository(repo.conn, schema=settings.db_schema)

    if ticker_filter is not None:
        tickers = [t.upper() for t in ticker_filter]
    else:
        tickers = sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})

    quotes = {q.ticker: q for q in repo.get_intraday_quotes(tickers)}
    ok = skipped_stale = skipped_thin = failed = 0
    for t in tickers:
        try:
            q = quotes.get(t)
            if q is None or (now - q.quoted_at).total_seconds() > max_age:
                skipped_stale += 1
                continue
            rows = trepo.fetch_series(t)
            # If the nightly already wrote today's EOD row, drop it: the live
            # spot IS today's provisional bar, so keeping both double-counts the
            # session (distorts z / RSI / MACD until the next nightly).
            rows = [r for r in rows if r["as_of"] != today_et]
            if len(rows) < _MIN_BARS:
                skipped_thin += 1
                continue
            # fetch_series returns ascending (oldest->newest) — the shape the
            # live splice needs. Close-only history: no OHLC in technical_daily,
            # so O/H/L reuse close (matching live_technical_snapshot's
            # provisional-bar convention; ATR over close-only slightly
            # understates true range for the live head — documented tradeoff).
            df = pd.DataFrame(
                [
                    {
                        "as_of": r["as_of"],
                        "open": r["close"],
                        "high": r["close"],
                        "low": r["close"],
                        "close": r["close"],
                        "volume": 0.0,
                    }
                    for r in rows
                ]
            )
            payload = live_technical_snapshot(df, float(q.price))
            live.upsert(t, q.quoted_at, float(q.price), q.source, payload)
            ok += 1
        except Exception as exc:
            failed += 1
            repo.conn.rollback()
            log.warning("technical_live_scan failed for %s: %s", t, repr(exc))
    summary = {
        "ok": ok,
        "skipped_stale": skipped_stale,
        "skipped_thin": skipped_thin,
        "failed": failed,
        "tickers": len(tickers),
    }
    log.info("technical_live_scan: %s", summary)
    return summary
