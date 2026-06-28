"""Apex signal-server read-only client (intraday price bars).

Apex (sibling project) serves EOD-synced intraday OHLC from the market-warehouse
lake over REST. We use it for ONE thing: the historical SPY 5-min close series
that overlays as the spot line on the Market Tide chart — UW's market-tide feed
carries premium + volume but no price, and the live worker only stamps spot for
the bars it captures in real time, leaving backfilled/historical sessions blank.

Live/today spot still comes from the WS feed (`intraday_quote`, stamped by the
market_tide scanner). Apex has no live bars — it fills the *historical* gap.

Never-raise: any failure returns an empty map so a missing/unreachable Apex
just leaves the spot column NULL (line absent) rather than breaking the page.

APEX_API_URL default targets the mini over Tailscale (right for MacBook dev);
on the mini set APEX_API_URL=http://127.0.0.1:8322.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://100.66.147.98:8322"


def _base_url() -> str:
    return os.environ.get("APEX_API_URL", _DEFAULT_URL).rstrip("/")


def fetch_intraday_closes(
    session_date: date,
    ticker: str = "SPY",
    *,
    timeframe: str = "5m",
    timeout: float = 10.0,
) -> dict[datetime, float]:
    """Return {bar_instant_utc: close} for one session's intraday bars.

    Keys are timezone-aware UTC datetimes at the bar timestamp, so a caller can
    match them against market_tide ts (also a UTC instant) with an exact lookup.
    Empty map on any error or no data.
    """
    url = f"{_base_url()}/bars/{ticker.upper()}"
    params = {
        "timeframe": timeframe,
        "start": session_date.isoformat(),
        "end": (session_date + timedelta(days=1)).isoformat(),
    }
    try:
        resp = httpx.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:  # never-raise — fall back to NULL spot
        logger.warning(
            "apex bars fetch failed %s %s: %s", ticker, session_date, repr(exc)
        )
        return {}
    return _parse_bars(bars)


def _parse_bars(bars: list[dict]) -> dict[datetime, float]:
    """{bar_instant_utc: close} from Apex bar dicts — UTC-normalized so the key
    matches a market_tide ts at the same wall-clock instant (e.g. an Apex bar at
    13:30Z and a UW bar at 09:30-04:00 collapse to the same key). Pure (no I/O)."""
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
