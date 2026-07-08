"""Intraday spot bar client — xenon (IB) primary, Apex REST fallback.

Used for ONE thing: the historical SPY 5-min close series that overlays as the
spot line on the Market Tide chart. The live worker stamps spot from the WS feed
for bars it captures in real time; this fills the historical gap.

Xenon primary: POST /historical/bars with X-API-Key → IB historical data.
Apex fallback: GET /bars/{ticker} → EOD-synced lake bars.

Never-raise: any failure returns an empty map so a missing/unreachable server
just leaves the spot column NULL (line absent) rather than breaking the page.

XENON_QUERY_API_URL  default http://127.0.0.1:8321
XENON_QUERY_API_KEY  required for xenon path (skip silently if absent)
APEX_API_URL         default http://100.66.147.98:8322 (Tailscale; set to
                     http://127.0.0.1:8322 on the mini)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_XENON_URL = "http://127.0.0.1:8321"
_DEFAULT_APEX_URL = "http://100.66.147.98:8322"


def _xenon_url() -> str:
    return os.environ.get("XENON_QUERY_API_URL", _DEFAULT_XENON_URL).rstrip("/")


def _xenon_key() -> str | None:
    return os.environ.get("XENON_QUERY_API_KEY") or None


def _apex_url() -> str:
    return os.environ.get("APEX_API_URL", _DEFAULT_APEX_URL).rstrip("/")


# ---------------------------------------------------------------------------
# Xenon path
# ---------------------------------------------------------------------------

_IB_BAR_SIZE = {"5m": "5 mins", "1m": "1 min", "1d": "1 day"}


def _fetch_xenon_closes(
    session_date: date,
    ticker: str,
    timeframe: str = "5m",
    timeout: float = 30.0,
) -> dict[datetime, float]:
    key = _xenon_key()
    if not key:
        return {}
    bar_size = _IB_BAR_SIZE.get(timeframe, "5 mins")
    end_dt = f"{session_date.strftime('%Y%m%d')} 16:10:00 US/Eastern"
    try:
        resp = httpx.post(
            f"{_xenon_url()}/historical/bars",
            headers={"X-API-Key": key},
            json={
                "contract": {
                    "symbol": ticker.upper(),
                    "sec_type": "STK",
                    "exchange": "SMART",
                    "currency": "USD",
                },
                "end_date_time": end_dt,
                "duration": "1 D",
                "bar_size": bar_size,
                "use_rth": True,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning(
            "xenon bars fetch failed %s %s: %s", ticker, session_date, repr(exc)
        )
        return {}
    return _parse_xenon_bars(bars)


def _parse_xenon_bars(bars: list[dict]) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for b in bars:
        t = b.get("date")
        c = b.get("close")
        if t is None or c is None:
            continue
        try:
            inst = datetime.fromisoformat(t).astimezone(timezone.utc)
            out[inst] = float(c)
        except (ValueError, TypeError) as exc:
            logger.debug("xenon bar parse skip: %s", repr(exc))
    return out


# ---------------------------------------------------------------------------
# Apex fallback path
# ---------------------------------------------------------------------------


def _fetch_apex_closes(
    session_date: date,
    ticker: str,
    timeframe: str = "5m",
    timeout: float = 10.0,
) -> dict[datetime, float]:
    url = f"{_apex_url()}/bars/{ticker.upper()}"
    params = {
        "timeframe": timeframe,
        "start": session_date.isoformat(),
        "end": (session_date + timedelta(days=1)).isoformat(),
    }
    try:
        resp = httpx.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning(
            "apex bars fetch failed %s %s: %s", ticker, session_date, repr(exc)
        )
        return {}
    return _parse_bars(bars)


def _parse_bars(bars: list[dict]) -> dict[datetime, float]:
    """{bar_instant_utc: close} from Apex bar dicts."""
    out: dict[datetime, float] = {}
    for b in bars:
        t = b.get("time")
        c = b.get("close")
        if t is None or c is None:
            continue
        try:
            inst = datetime.fromisoformat(t).astimezone(timezone.utc)
            out[inst] = float(c)
        except (ValueError, TypeError) as exc:
            logger.debug("apex bar parse skip: %s", repr(exc))
            continue
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_intraday_closes(
    session_date: date,
    ticker: str = "SPY",
    *,
    timeframe: str = "5m",
    timeout: float = 10.0,
) -> dict[datetime, float]:
    """Return {bar_instant_utc: close} for one session's intraday bars.

    Tries xenon (IB historical) first; falls back to Apex if xenon is
    unavailable or returns no bars.
    """
    closes = _fetch_xenon_closes(session_date, ticker, timeframe, timeout=30.0)
    if closes:
        logger.debug(
            "apex.fetch_intraday_closes: xenon hit %s %s (%d bars)",
            ticker,
            session_date,
            len(closes),
        )
        return closes
    closes = _fetch_apex_closes(session_date, ticker, timeframe, timeout=timeout)
    if closes:
        logger.debug(
            "apex.fetch_intraday_closes: apex fallback hit %s %s (%d bars)",
            ticker,
            session_date,
            len(closes),
        )
    return closes


def fetch_daily_bars(ticker: str, *, timeout: float = 20.0) -> list[dict]:
    """Full default daily-bar window from apex (500 today, 2000 once apex's
    cap raise lands). Raw bar dicts; [] on any failure (never-raise)."""
    url = f"{_apex_url()}/bars/{ticker.upper()}"
    try:
        resp = httpx.get(url, params={"timeframe": "1d"}, timeout=timeout)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning("apex daily bars fetch failed %s: %s", ticker, repr(exc))
        return []
    if not isinstance(bars, list):
        logger.warning(
            "apex daily bars malformed for %s: bars is %s", ticker, type(bars).__name__
        )
        return []
    return bars
