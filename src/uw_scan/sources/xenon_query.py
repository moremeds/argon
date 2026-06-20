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
        greeks = (resp.json() or {}).get("greeks")
        if not greeks or greeks.get("impliedVol") is None:
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
