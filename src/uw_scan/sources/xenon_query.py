"""Read-only client for xenon's query API — IB-native option greeks for the surface canary.

See xenon/docs/reference/readonly-query-api.md. Used ONLY for targeted single-contract
lookups (the daily IB-vs-UW IV cross-check, the VRP entry quotes, the theta quote);
never for bulk chain capture, because the endpoint is per-contract (one IB snapshot
subprocess per call).

Status contract (I-15): a 2xx returns the normal shape, and None / None fields mean
only "IB answered without that value" (an illiquid contract's greeks object is JSON
null on a 200). A transport error, a non-2xx (a missing/wrong X-API-Key is a 401),
an undecodable body or a wrong-shaped body raises `SourceUnavailable`, so a caller can
tell "xenon down" from "IB has no greeks". Nothing else is caught.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import httpx

from uw_scan.sources.source_errors import SourceUnavailable

log = logging.getLogger(__name__)


def _get_greeks_body(
    *,
    base_url: str,
    api_key: str | None,
    symbol: str,
    expiry: str,
    strike: float,
    right: str,
    timeout_s: float,
    client: httpx.Client | None,
) -> dict:
    """GET /options/greeks for one contract and return the JSON object.
    Only transport/HTTP/decode/shape failures become SourceUnavailable."""
    headers = {"X-API-Key": api_key} if api_key else {}
    params = {
        "symbol": symbol.upper(),
        "expiry": expiry,
        "strike": strike,
        "right": right.upper(),
    }
    what = f"xenon greeks {symbol.upper()} {expiry} {strike}{right.upper()}"
    own = client is None
    c = client or httpx.Client(timeout=timeout_s, trust_env=False)
    try:
        try:
            resp = c.get(f"{base_url}/options/greeks", params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceUnavailable("xenon_query", f"{what}: {exc!r}") from exc
    finally:
        if own:
            c.close()
    if not isinstance(body, dict):
        raise SourceUnavailable("xenon_query", f"{what}: body is {type(body).__name__}")
    return body


def fetch_ib_option_iv(
    *,
    base_url: str,
    api_key: str | None,
    symbol: str,
    expiry: str,
    strike: float,
    right: str,
    timeout_s: float = 15.0,
    client: httpx.Client | None = None,
) -> Decimal | None:
    """IB modelGreeks impliedVol for one option contract via GET /options/greeks.

    ``expiry`` is YYYYMMDD. Returns the IV as Decimal, or None when IB answered
    without an implied vol. Raises SourceUnavailable when xenon could not answer.
    """
    body = _get_greeks_body(
        base_url=base_url,
        api_key=api_key,
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        right=right,
        timeout_s=timeout_s,
        client=client,
    )
    greeks = body.get("greeks")
    if not isinstance(greeks, dict) or greeks.get("impliedVol") is None:
        return None
    try:
        return Decimal(str(greeks["impliedVol"]))
    except InvalidOperation as exc:
        raise SourceUnavailable(
            "xenon_query",
            f"xenon greeks {symbol.upper()}: impliedVol not numeric: {exc!r}",
        ) from exc


def fetch_ib_option_quote(
    *,
    base_url: str,
    api_key: str | None,
    symbol: str,
    expiry: str,
    strike: float,
    right: str,
    timeout_s: float = 8.0,
    client: httpx.Client | None = None,
) -> dict:
    """NBBO + marked IV + underlying spot + native greeks for one option via
    GET /options/greeks.

    Returns ``{"bid", "ask", "iv", "und_spot", "delta", "gamma", "vega",
    "theta"}`` — any value ``None`` when IB omitted it (greeks object may itself
    be JSON ``null`` for an illiquid contract, still HTTP 200 → every greek None).
    IB's native delta/gamma/vega/theta are consumed as the primary greek
    source (BS-from-IV is the downstream backup); the caller rescales IB's
    per-1%-vol vega and per-day theta to argon's BS column convention. Raises
    SourceUnavailable when xenon could not answer; callers fall back to UW.
    """
    body = _get_greeks_body(
        base_url=base_url,
        api_key=api_key,
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        right=right,
        timeout_s=timeout_s,
        client=client,
    )
    greeks = body.get("greeks")
    greeks = greeks if isinstance(greeks, dict) else {}
    return {
        "bid": body.get("bid"),
        "ask": body.get("ask"),
        "iv": greeks.get("impliedVol"),
        "und_spot": greeks.get("undPrice"),
        "delta": greeks.get("delta"),
        "gamma": greeks.get("gamma"),
        "vega": greeks.get("vega"),
        "theta": greeks.get("theta"),
    }
