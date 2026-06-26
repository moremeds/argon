"""Read-only client for xenon's query API — IB-native option greeks for the surface canary.

See xenon/docs/reference/readonly-query-api.md. Used ONLY for targeted single-contract
lookups (the daily IB-vs-UW IV cross-check); never for bulk chain capture, because the
endpoint is per-contract (one IB snapshot subprocess per call).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import httpx

log = logging.getLogger(__name__)


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

    ``expiry`` is YYYYMMDD. Returns the IV as Decimal, or None when IB computed no greeks
    or the call failed — the canary must never raise into the job.
    """
    headers = {"X-API-Key": api_key} if api_key else {}
    params = {
        "symbol": symbol.upper(),
        "expiry": expiry,
        "strike": strike,
        "right": right.upper(),
    }
    own = client is None
    c = client or httpx.Client(timeout=timeout_s)
    try:
        resp = c.get(f"{base_url}/options/greeks", params=params, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            return None
        greeks = body.get("greeks")
        if not isinstance(greeks, dict) or greeks.get("impliedVol") is None:
            return None
        return Decimal(str(greeks["impliedVol"]))
    except (httpx.HTTPError, ValueError, KeyError, InvalidOperation) as exc:
        log.warning(
            "xenon canary fetch failed for %s %s %s%s: %s",
            symbol,
            expiry,
            strike,
            right,
            repr(exc),
        )
        return None
    finally:
        if own:
            c.close()


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
) -> dict | None:
    """NBBO + marked IV + underlying spot + native greeks for one option via
    GET /options/greeks.

    Returns ``{"bid", "ask", "iv", "und_spot", "delta", "gamma", "vega",
    "theta"}`` — any value ``None`` when IB omitted it (greeks object may itself
    be JSON ``null`` for an illiquid contract, still HTTP 200 → every greek None).
    IB's native delta/gamma/vega/theta are now consumed as the primary greek
    source (BS-from-IV is the downstream backup); the caller rescales IB's
    per-1%-vol vega and per-day theta to argon's BS column convention. Returns
    ``None`` only on transport failure — mirrors ``fetch_ib_option_iv``'s
    never-raise contract so the snapshot job falls back to UW instead of crashing.
    """
    headers = {"X-API-Key": api_key} if api_key else {}
    params = {
        "symbol": symbol.upper(),
        "expiry": expiry,
        "strike": strike,
        "right": right.upper(),
    }
    own = client is None
    c = client or httpx.Client(timeout=timeout_s)
    try:
        resp = c.get(f"{base_url}/options/greeks", params=params, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            return None
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
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning(
            "xenon quote fetch failed for %s %s %s%s: %s",
            symbol,
            expiry,
            strike,
            right,
            repr(exc),
        )
        return None
    finally:
        if own:
            c.close()
