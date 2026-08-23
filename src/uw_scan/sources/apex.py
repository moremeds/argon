"""Intraday spot bar client — xenon (IB) primary, Apex REST fallback.

Used for ONE thing: the historical SPY 5-min close series that overlays as the
spot line on the Market Tide chart. The live worker stamps spot from the WS feed
for bars it captures in real time; this fills the historical gap.

Xenon primary: POST /historical/bars with X-API-Key → IB historical data.
Apex fallback: GET /v1/{asset_class}/{symbol}/bars → EOD-synced lake bars.

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
# Apex /v1 route + params
# ---------------------------------------------------------------------------

# apex 0.1.4 moved to /v1/{asset_class}/{symbol}/... . The flat /bars/{ticker}
# alias still answers but emits Deprecation/Sunset: Wed, 31 Dec 2026, and it
# resolves EVERY symbol under asset_class=equity — GET /bars/SPX is a 404
# unknown_symbol, which is why the vol complex was unreachable from here.
_DEFAULT_ASSET_CLASS = "equity"


def _bars_url(symbol: str, asset_class: str) -> str:
    return f"{_apex_url()}/v1/{asset_class}/{symbol.upper()}/bars"


def _with_price_mode(params: dict[str, object], asset_class: str) -> dict[str, object]:
    """Add `price_mode=adjusted` for equity; leave every other class alone.

    Corporate-action adjustment is a REQUEST, not an inherited default: apex
    falls back to its own APEX_LIVEWIRE_PRICE_MODE when the param is absent, so
    a server-side config flip would silently re-base argon's whole price series
    mid-stream. Equity is also the only class with a Silver tree — asking any
    other class for `adjusted` is a 400 adjusted_not_supported.
    """
    if asset_class == _DEFAULT_ASSET_CLASS:
        params["price_mode"] = "adjusted"
    return params


def _err_code(exc: Exception) -> str | None:
    """apex's typed error code (`adjusted_unavailable`, `unknown_symbol`, …).

    Every never-raise path here collapses to [], so the code is the ONLY thing
    that separates "apex refused" from "this symbol genuinely has no bars".
    """
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    try:
        body = resp.json()
    except Exception as parse_exc:  # non-JSON body (proxy page, truncated read)
        logger.debug("apex error body is not JSON: %s", repr(parse_exc))
        return None
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    return err.get("code") if isinstance(err, dict) else None


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
    params = _with_price_mode(
        {
            "timeframe": timeframe,
            "start": _iso(session_date),
            "end": _iso(session_date + timedelta(days=1)),
        },
        _DEFAULT_ASSET_CLASS,
    )
    try:
        resp = httpx.get(
            _bars_url(ticker, _DEFAULT_ASSET_CLASS), params=params, timeout=timeout
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning(
            "apex bars fetch failed %s %s: %s (apex code=%s)",
            ticker,
            session_date,
            repr(exc),
            _err_code(exc),
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


def fetch_daily_bars(
    ticker: str,
    *,
    asset_class: str = _DEFAULT_ASSET_CLASS,
    timeout: float = 20.0,
) -> list[dict]:
    """Deep daily-bar window from apex for the technicals series. Fetches the
    ~5y display window (1300 sessions) PLUS a warmup buffer so the longest-
    warmup series (z_vs_200dma needs ~324 bars) is populated across the whole
    displayed window — fetch_series returns the last 1300 warm rows. Raw bar
    dicts; [] on any failure (never-raise).

    `asset_class` defaults to equity; pass `volatility` for SPX/VIX/VVIX/COR1M.
    """
    params = _with_price_mode({"timeframe": "1d", "limit": 1650}, asset_class)
    try:
        resp = httpx.get(_bars_url(ticker, asset_class), params=params, timeout=timeout)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning(
            "apex daily bars fetch failed %s: %s (apex code=%s)",
            ticker,
            repr(exc),
            _err_code(exc),
        )
        return []
    if not isinstance(bars, list):
        logger.warning(
            "apex daily bars malformed for %s: bars is %s", ticker, type(bars).__name__
        )
        return []
    return bars


def _iso(v: date | datetime) -> str:
    """Offset-aware ISO-8601, always.

    apex /v1 answers 500 internal_error for a bare `YYYY-MM-DD` start and for a
    naive ISO datetime; only an explicit UTC offset parses (measured against
    0.1.4 on 2026-08-23, equity and volatility alike). The deprecated flat alias
    accepted the bare date, so every caller passing a `date` — which is all of
    them — breaks on the /v1 route without this.
    """
    if isinstance(v, datetime):  # datetime is a date subclass; check it first
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return datetime(v.year, v.month, v.day, tzinfo=timezone.utc).isoformat()


def fetch_bars(
    ticker: str,
    timeframe: str,
    start: date | datetime,
    *,
    end: date | datetime | None = None,
    limit: int = 0,
    asset_class: str = _DEFAULT_ASSET_CLASS,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Raw apex bars for one ticker/timeframe from an explicit `start`.

    ALWAYS pass `start` explicitly — apex's default lookback window can return
    count:0 for a valid ticker whose latest bar predates the default (verified,
    phaseb_apex_bars_contract.md §2c). `limit=0` == full history from start.
    Never-raise: returns [] on transport error, unsupported timeframe (400),
    a refused adjusted read (503 adjusted_unavailable), unknown ticker (404),
    or malformed body. An empty list means "no data", never "success with
    zero" — callers must treat [] as skip, and the reason is in the log.

    `asset_class` defaults to equity; pass `volatility` for SPX/VIX/VVIX/COR1M
    (the flat alias resolved every symbol as equity, so those 404'd here).
    """
    params = _with_price_mode(
        {"timeframe": timeframe, "start": _iso(start), "limit": limit},
        asset_class,
    )
    if end is not None:
        params["end"] = _iso(end)
    own = client is None
    c = client or httpx.Client(timeout=timeout)
    try:
        resp = c.get(_bars_url(ticker, asset_class), params=params)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            return []
        bars = body.get("bars", [])
        if not isinstance(bars, list):
            return []
        return bars
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "apex fetch_bars failed %s %s from %s: %s (apex code=%s)",
            ticker,
            timeframe,
            _iso(start),
            repr(exc),
            _err_code(exc),
        )
        return []
    finally:
        if own:
            c.close()
