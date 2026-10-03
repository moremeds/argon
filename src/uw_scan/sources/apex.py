"""Apex bars client (+ the xenon-primary intraday close series).

apex REST: GET /v1/{asset_class}/{symbol}/bars (one symbol) and
GET /v1/equity/bars (bulk). xenon: POST /historical/bars (IB historical), used
only as the primary for the intraday SPY close series behind the Market Tide
spot line.

Status contract (I-15/I-17): a 2xx returns the normal shape, and an empty
result means only "the source answered with no data". A transport error, a
non-2xx (apex's typed code such as `adjusted_unavailable` or `unknown_symbol` is
kept in the detail), an undecodable body or a body of the wrong shape raises
`SourceUnavailable`. Nothing else is caught, so a programming error propagates.

URLs and keys come in as arguments (Settings.apex_api_url,
Settings.xenon_query_api_url/_key); this module reads no environment (I-59).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone

import httpx

from uw_scan.sources.source_errors import SourceUnavailable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Apex /v1 route + params
# ---------------------------------------------------------------------------

# apex 0.1.4 moved to /v1/{asset_class}/{symbol}/... . The flat /bars/{ticker}
# alias still answers but emits Deprecation/Sunset: Wed, 31 Dec 2026, and it
# resolves EVERY symbol under asset_class=equity — GET /bars/SPX is a 404
# unknown_symbol, which is why the vol complex was unreachable from here.
_DEFAULT_ASSET_CLASS = "equity"


def _bars_url(base_url: str, symbol: str, asset_class: str) -> str:
    return f"{base_url.rstrip('/')}/v1/{asset_class}/{symbol.upper()}/bars"


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
    """apex's typed error code (`adjusted_unavailable`, `unknown_symbol`, …),
    carried into the SourceUnavailable detail."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    try:
        body = resp.json()
    except ValueError as parse_exc:  # non-JSON body (proxy page, truncated read)
        logger.debug("apex error body is not JSON: %s", repr(parse_exc))
        return None
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    return err.get("code") if isinstance(err, dict) else None


def _unavailable(what: str, exc: Exception) -> SourceUnavailable:
    return SourceUnavailable("apex", f"{what}: {exc!r} (apex code={_err_code(exc)})")


def _json_dict(resp: httpx.Response, what: str) -> dict:
    """raise_for_status + decode + require a JSON object. Only the transport/
    HTTP/decode/shape failures become SourceUnavailable."""
    try:
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _unavailable(what, exc) from exc
    if not isinstance(body, dict):
        raise SourceUnavailable("apex", f"{what}: body is {type(body).__name__}")
    return body


def _bars_list(body: dict, what: str) -> list:
    bars = body.get("bars", [])
    if not isinstance(bars, list):
        raise SourceUnavailable("apex", f"{what}: bars is {type(bars).__name__}")
    return bars


# ---------------------------------------------------------------------------
# Xenon path (intraday closes only)
# ---------------------------------------------------------------------------

_IB_BAR_SIZE = {"5m": "5 mins", "1m": "1 min", "1d": "1 day"}


def _fetch_xenon_closes(
    session_date: date,
    ticker: str,
    *,
    base_url: str,
    api_key: str,
    timeframe: str = "5m",
    timeout: float = 30.0,
) -> dict[datetime, float]:
    bar_size = _IB_BAR_SIZE.get(timeframe, "5 mins")
    end_dt = f"{session_date.strftime('%Y%m%d')} 16:10:00 US/Eastern"
    what = f"xenon bars {ticker} {session_date}"
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/historical/bars",
            headers={"X-API-Key": api_key},
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
            trust_env=False,
        )
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceUnavailable("xenon_query", f"{what}: {exc!r}") from exc
    bars = body.get("bars", []) if isinstance(body, dict) else None
    if not isinstance(bars, list):
        raise SourceUnavailable("xenon_query", f"{what}: malformed body")
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
# Apex intraday path
# ---------------------------------------------------------------------------


def _fetch_apex_closes(
    session_date: date,
    ticker: str,
    *,
    base_url: str,
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
    what = f"apex bars {ticker} {session_date}"
    try:
        resp = httpx.get(
            _bars_url(base_url, ticker, _DEFAULT_ASSET_CLASS),
            params=params,
            timeout=timeout,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise _unavailable(what, exc) from exc
    return _parse_bars(_bars_list(_json_dict(resp, what), what))


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
    apex_base_url: str,
    xenon_base_url: str,
    xenon_api_key: str | None,
    timeframe: str = "5m",
    timeout: float = 10.0,
) -> dict[datetime, float]:
    """Return {bar_instant_utc: close} for one session's intraday bars.

    Tries xenon (IB historical) first when a key is set; a xenon failure or an
    empty xenon answer falls back to apex. An apex failure raises
    SourceUnavailable; {} means apex answered with no bars.
    """
    if xenon_api_key:
        try:
            closes = _fetch_xenon_closes(
                session_date,
                ticker,
                base_url=xenon_base_url,
                api_key=xenon_api_key,
                timeframe=timeframe,
                timeout=30.0,
            )
        except SourceUnavailable as exc:
            logger.warning("%s; falling back to apex", repr(exc))
            closes = {}
        if closes:
            logger.debug(
                "apex.fetch_intraday_closes: xenon hit %s %s (%d bars)",
                ticker,
                session_date,
                len(closes),
            )
            return closes
    return _fetch_apex_closes(
        session_date,
        ticker,
        base_url=apex_base_url,
        timeframe=timeframe,
        timeout=timeout,
    )


def fetch_daily_bars(
    ticker: str,
    *,
    base_url: str,
    asset_class: str = _DEFAULT_ASSET_CLASS,
    timeout: float = 20.0,
) -> list[dict]:
    """Deep daily-bar window from apex for the technicals series. Fetches the
    ~5y display window (1300 sessions) PLUS a warmup buffer so the longest-
    warmup series (z_vs_200dma needs ~324 bars) is populated across the whole
    displayed window — fetch_series returns the last 1300 warm rows. Raw bar
    dicts; [] means apex answered with no bars, SourceUnavailable means it
    could not answer.

    `asset_class` defaults to equity; pass `volatility` for SPX/VIX/VVIX/COR1M.
    """
    params = _with_price_mode({"timeframe": "1d", "limit": 1650}, asset_class)
    what = f"apex daily bars {ticker}"
    try:
        resp = httpx.get(
            _bars_url(base_url, ticker, asset_class),
            params=params,
            timeout=timeout,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise _unavailable(what, exc) from exc
    return _bars_list(_json_dict(resp, what), what)


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
    base_url: str,
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
    [] means apex answered with no bars. A transport error, an unsupported
    timeframe (400), a refused adjusted read (503 adjusted_unavailable), an
    unknown ticker (404) or a malformed body raises SourceUnavailable with the
    apex code in its detail.

    `asset_class` defaults to equity; pass `volatility` for SPX/VIX/VVIX/COR1M
    (the flat alias resolved every symbol as equity, so those 404'd here).
    """
    params = _with_price_mode(
        {"timeframe": timeframe, "start": _iso(start), "limit": limit},
        asset_class,
    )
    if end is not None:
        params["end"] = _iso(end)
    what = f"apex fetch_bars {ticker} {timeframe} from {_iso(start)}"
    own = client is None
    c = client or httpx.Client(timeout=timeout, trust_env=False)
    try:
        try:
            resp = c.get(_bars_url(base_url, ticker, asset_class), params=params)
        except httpx.HTTPError as exc:
            raise _unavailable(what, exc) from exc
        return _bars_list(_json_dict(resp, what), what)
    finally:
        if own:
            c.close()


# ---------------------------------------------------------------------------
# Many-symbol daily closes (sector RS)
# ---------------------------------------------------------------------------

#: apex GET /v1/equity/bars accepts at most 200 symbols per call (400 above).
BULK_MAX_SYMBOLS = 200


def _utc_bound(d: date, *, end: bool) -> str:
    """Explicit-Z day bound. apex answers 400 invalid_parameter for a bare date
    or a naive timestamp ("start must carry a UTC offset"). `end` runs to
    23:59:59, so the end session's bar (stamped at UTC midnight) is included."""
    return f"{d.isoformat()}T23:59:59Z" if end else f"{d.isoformat()}T00:00:00Z"


def _parse_daily_closes(bars: object) -> dict[date, float]:
    """{session_date: close} from apex daily bar dicts (time = UTC midnight)."""
    out: dict[date, float] = {}
    if not isinstance(bars, list):
        return out
    for b in bars:
        if not isinstance(b, dict):
            continue
        t = b.get("time")
        c = b.get("close")
        if t is None or c is None:
            continue
        try:
            out[datetime.fromisoformat(t).astimezone(timezone.utc).date()] = float(c)
        except (ValueError, TypeError) as exc:
            logger.debug("apex daily bar parse skip: %s", repr(exc))
    return out


def fetch_bulk_daily_closes(
    symbols: Iterable[str],
    *,
    base_url: str,
    start: date,
    end: date,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, dict[date, float]]:
    """Adjusted daily closes for many equity symbols over apex's bulk route.

    GET /v1/equity/bars in chunks of BULK_MAX_SYMBOLS. One Silver revision is
    pinned per call. `limit=0` with an explicit start returns every row in the
    window. `listing=any` is sent, but under price_mode=adjusted apex files a
    delisted name under `missing` ("no Silver for delisted names"): livewire
    adjusts only listed names. Such a name is ABSENT from the result. The
    caller counts it as unpriced, never as a zero return, and it is not
    re-fetched raw (spec §4 ruling).

    Any chunk that cannot be fetched raises SourceUnavailable: a silently
    dropped chunk would remove up to 200 symbols from the breadth denominator.
    """
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    out: dict[str, dict[date, float]] = {}
    if not wanted:
        return out
    own = client is None
    c = client or httpx.Client(timeout=timeout, trust_env=False)
    missing_total = 0
    try:
        for i in range(0, len(wanted), BULK_MAX_SYMBOLS):
            chunk = wanted[i : i + BULK_MAX_SYMBOLS]
            what = f"apex bulk bars for {len(chunk)} symbols from {chunk[0]}"
            try:
                resp = c.get(
                    f"{base_url.rstrip('/')}/v1/equity/bars",
                    params={
                        "symbols": ",".join(chunk),
                        "timeframe": "1d",
                        "start": _utc_bound(start, end=False),
                        "end": _utc_bound(end, end=True),
                        "limit": 0,
                        "price_mode": "adjusted",
                        "listing": "any",
                    },
                )
            except httpx.HTTPError as exc:
                raise _unavailable(what, exc) from exc
            body = _json_dict(resp, what)
            series = body.get("symbols")
            if not isinstance(series, dict):
                raise SourceUnavailable("apex", f"{what}: symbols is not an object")
            for sym, entry in series.items():
                closes = _parse_daily_closes(
                    entry.get("bars") if isinstance(entry, dict) else None
                )
                if closes:
                    out[str(sym).upper()] = closes
            missing = body.get("missing")
            if isinstance(missing, dict):
                missing_total += len(missing)
                for sym, reason in missing.items():
                    logger.debug("apex bulk bars missing %s: %s", sym, reason)
    finally:
        if own:
            c.close()
    if missing_total:
        logger.info(
            "apex bulk bars: %d of %d symbols in `missing` (unpriced, not zero)",
            missing_total,
            len(wanted),
        )
    return out
