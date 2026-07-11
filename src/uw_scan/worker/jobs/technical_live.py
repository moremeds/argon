"""Live technicals coverage: splice the latest WS intraday_quote as today's
provisional daily close, recompute the fast-moving technicals, and accumulate
today's forming candle, cached per ticker. Mostly DB-read only; the one provider
touch is a periodic (~15-min) massive cross-check of the forming candle in case
the primary xenon feed is unstable (see reconcile_forming_with_massive)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from uw_scan.cards.technicals import (
    accumulate_forming_ohlc,
    live_technical_snapshot,
    reconcile_forming_with_massive,
)
from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider, OhlcProvider
from uw_scan.storage.repository import Repository
from uw_scan.storage.technical_live_repository import TechnicalLiveRepository
from uw_scan.storage.technicals_repository import TechnicalsRepository

log = logging.getLogger(__name__)

_MIN_BARS = 210  # same floor as build_technical_snapshot
# Massive cross-check cadence (user-specified) — aligned with massive's ~15-min
# delay so a delayed close is old enough to sit inside a healthy live range.
_MASSIVE_CHECK_INTERVAL = timedelta(minutes=15)
# Range-containment tolerance: absorbs timing/rounding + a loop restarted
# mid-session before the live range grew to include the delayed price.
_MASSIVE_RANGE_TOL_BPS = 50.0


def _make_massive(settings: Settings) -> MassiveOhlcProvider | None:
    """Massive REST client for the forming-candle cross-check, None if no key."""
    if settings.massive_api_key is None:
        return None
    return MassiveOhlcProvider(
        api_key=settings.massive_api_key.get_secret_value(),
        base_url=settings.massive_base_url,
        timeout=settings.request_timeout_seconds,
        job_name="technical_live_scan",
    )


def _due_for_massive(prior_val: dict | None, now: datetime) -> bool:
    """True when ≥ the check interval has elapsed since the last massive
    cross-check (or there is no prior check). Decouples the massive cadence from
    the job's own (faster) run interval."""
    checked = (prior_val or {}).get("checked_at")
    if not checked:
        return True
    try:
        last = datetime.fromisoformat(checked)
    except (TypeError, ValueError) as exc:
        log.debug("massive check clock parse failed (%r): %s", checked, repr(exc))
        return True
    return (now - last) >= _MASSIVE_CHECK_INTERVAL


def _massive_today_ohlc(
    provider: OhlcProvider, ticker: str, session_date: Any
) -> dict | None:
    """massive's delayed today bar as {open,high,low,close} floats, None on any
    failure (never-raise — a massive hiccup must not fail the live update)."""
    try:
        bars = provider.fetch_daily(ticker, session_date, session_date)
    except Exception as exc:  # noqa: BLE001
        log.debug("massive today fetch failed %s: %s", ticker, repr(exc))
        return None
    # Strict date match only — never fall back to bars[-1]: cross-checking (and
    # potentially healing) today's candle against a stale prior-session bar would
    # be worse than skipping the check.
    bar = next((b for b in bars if b.date == session_date), None)
    if bar is None:
        return None

    def _f(v: Any) -> float | None:
        return float(v) if v is not None else None

    return {
        "open": _f(bar.open),
        "high": _f(bar.high),
        "low": _f(bar.low),
        "close": _f(bar.close),
    }


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
    massive = _make_massive(settings)  # None if no MASSIVE_API_KEY
    ok = skipped_stale = skipped_thin = failed = healed = 0
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
            # live splice needs. Use the real stored OHLCV now that technical_daily
            # carries it (migration 105) so live ATR / ATR-normalized MACD /
            # kinematics match the settled daily series; fall back to close for
            # any pre-migration row that hasn't been recomputed yet.
            df = pd.DataFrame(
                [
                    {
                        "as_of": r["as_of"],
                        "open": r["open"] if r["open"] is not None else r["close"],
                        "high": r["high"] if r["high"] is not None else r["close"],
                        "low": r["low"] if r["low"] is not None else r["close"],
                        "close": r["close"],
                        "volume": float(r["volume"])
                        if r["volume"] is not None
                        else 0.0,
                    }
                    for r in rows
                ]
            )
            payload = live_technical_snapshot(df, float(q.price))
            # Accumulate today's provisional session candle from the live spot
            # so the chart draws a real forming bar (open/high/low/close), not a
            # zero-range doji. Read the prior candle back so open + running
            # extremes survive across job runs (and worker restarts).
            prior_payload = (live.fetch(t) or {}).get("payload") or {}
            forming = accumulate_forming_ohlc(
                prior_payload.get("forming_ohlc"), float(q.price), today_et, q.source
            )
            # Every ~15 min, cross-check the live candle against massive's
            # delayed today bar and heal an unstable xenon read to massive
            # (range-containment — see reconcile_forming_with_massive).
            prior_val = prior_payload.get("forming_validation")
            if massive is not None and _due_for_massive(prior_val, now):
                forming, verdict = reconcile_forming_with_massive(
                    forming,
                    _massive_today_ohlc(massive, t, today_et),
                    now.isoformat(),
                    _MASSIVE_RANGE_TOL_BPS,
                )
                payload["forming_validation"] = verdict
                if verdict["healed"]:
                    healed += 1
                    log.warning(
                        "technical_live forming HEALED to massive for %s: "
                        "massive_close=%s out_of_range_bps=%s",
                        t,
                        verdict["massive_close"],
                        verdict["out_of_range_bps"],
                    )
            elif prior_val:
                payload["forming_validation"] = prior_val  # keep the gate clock
            payload["forming_ohlc"] = forming
            live.upsert(t, q.quoted_at, float(q.price), q.source, payload)
            ok += 1
        except Exception as exc:
            failed += 1
            repo.conn.rollback()
            log.warning("technical_live_scan failed for %s: %s", t, repr(exc))
    # ponytail: the per-ticker try/except above always completes the loop, so a
    # plain close here (no outer finally) is enough to release the HTTP client.
    if massive is not None:
        massive.close()
    summary = {
        "ok": ok,
        "skipped_stale": skipped_stale,
        "skipped_thin": skipped_thin,
        "failed": failed,
        "healed": healed,
        "tickers": len(tickers),
    }
    log.info("technical_live_scan: %s", summary)
    return summary
