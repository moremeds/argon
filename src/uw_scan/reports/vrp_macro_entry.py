"""Forward entry-capture: resolve the SPX bull-put-spread the Macro Short-Vol
signal would place onto *listed* strikes, then quote each leg.

`resolve_entry_contracts` is pure (no I/O): it maps the BS target strike for the
0.25Δ short and 0.125Δ wing onto the nearest listed strikes that bracket each
target. `quote_leg` (Task 4) quotes a resolved leg IB-primary / UW-fallback with
BS-computed greeks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..sources.xenon_query import fetch_ib_option_quote
from .vrp_structure import bs_delta, bs_gamma, bs_theta, bs_vega, strike_for_delta

_ET = ZoneInfo("America/New_York")

# IB modelGreeks → argon's BS column convention. IB reports vega per 1% (0.01)
# vol move and theta per calendar day; argon stores bs_vega (per 1.00 vol) and
# bs_theta (per year), so scale IB's to match. delta/gamma need no scaling.
_IB_VEGA_TO_BS = 100.0  # per-1% → per-100% vol
_IB_THETA_TO_BS = 365.0  # per-day → per-year


@dataclass(frozen=True)
class EntryContracts:
    short_above: float
    short_below: float
    wing_above: float
    wing_below: float


def _bracket(target: float, strikes_sorted: list[float]) -> tuple[float, float]:
    """Nearest listed strike strictly below and strictly above `target`.
    Raises ValueError if the grid lacks a strike on either side."""
    below: float | None = None
    above: float | None = None
    for k in strikes_sorted:
        if k < target:
            below = k
        elif k > target:
            above = k
            break
    if below is None or above is None:
        raise ValueError(
            f"listed strikes do not bracket target {target:.2f} "
            f"(range {strikes_sorted[0]}..{strikes_sorted[-1]})"
        )
    return below, above


def resolve_entry_contracts(
    *,
    spot: float,
    sigma: float,
    T: float,
    r: float,
    listed_strikes: list[float],
    short_delta: float = 0.25,
    wing_delta: float = 0.125,
) -> EntryContracts:
    """BS target strike per delta, snapped to the listed strikes that bracket it.

    Flat-vol target (skew ignored — the realized leg delta is recorded at quote
    time). Both legs are puts (`is_call=False`). Raises ValueError if the grid
    can't bracket a target."""
    strikes_sorted = sorted(set(listed_strikes))
    short_target = strike_for_delta(spot, T, r, sigma, short_delta, is_call=False)
    wing_target = strike_for_delta(spot, T, r, sigma, wing_delta, is_call=False)
    short_below, short_above = _bracket(short_target, strikes_sorted)
    wing_below, wing_above = _bracket(wing_target, strikes_sorted)
    return EntryContracts(
        short_above=short_above,
        short_below=short_below,
        wing_above=wing_above,
        wing_below=wing_below,
    )


@dataclass(frozen=True)
class LegQuote:
    strike: Any
    nbbo_bid: Any
    nbbo_ask: Any
    iv: Any
    delta: float
    gamma: float
    vega: float
    theta: float
    und_spot: Any
    source: str  # 'xenon_ib' | 'uw'  (always a real NBBO; never synthetic)
    greeks_source: str  # 'ib' | 'bs' | 'none'
    source_asof: Any


def quote_leg(
    *,
    strike: float,
    expiry: str,
    as_of: datetime,
    underlying_spot: float,
    r: float,
    settings: Any,
    xenon_client: Any = None,
    uw_row: dict[str, Any] | None = None,
    try_xenon: bool = True,
) -> LegQuote:
    """Quote one resolved put leg: xenon/IB primary (true NBBO + IV + und_spot +
    native greeks), UW fallback (delayed NBBO + IV). Greeks: IB-native primary,
    BS-from-IV backup, then nulls.

    ``expiry`` is YYYYMMDD; ``as_of`` is tz-aware. T is computed from expiry vs the
    **as_of ET date** (never wall-clock) so replays/late marks are deterministic.
    IB greeks are rescaled to argon's BS column convention — vega ×100 (IB per-1%
    vol → bs_vega per-100%) and theta ×365 (IB per-day → bs_theta per-year); delta
    and gamma already share BS conventions. ``greeks_source`` is ``'ib'`` when IB
    returns a full greek set, ``'bs'`` when only a real IV is present (UW legs, or
    IB without greeks), else ``'none'`` (greeks 0.0). ``source`` tags the
    NBBO+IV+und_spot provenance independently of ``greeks_source``.
    """
    exp_date = datetime.strptime(expiry, "%Y%m%d").date()
    as_of_date = as_of.astimezone(_ET).date()
    T = max((exp_date - as_of_date).days, 0) / 365.0

    key = settings.xenon_query_api_key
    api_key = key.get_secret_value() if key else None
    timeout_s = getattr(settings, "vrp_macro_entry_quote_timeout_s", 8.0)

    # try_xenon=False is the per-mark-budget escape: once a mark overruns its
    # wall-clock budget, remaining legs quote UW-only (skip the slow IB snapshot).
    xq = (
        fetch_ib_option_quote(
            base_url=settings.xenon_query_api_url,
            api_key=api_key,
            symbol="SPX",
            expiry=expiry,
            strike=float(strike),
            right="P",
            timeout_s=timeout_s,
            client=xenon_client,
        )
        if try_xenon
        else None
    )
    if xq is not None and (xq.get("bid") is not None or xq.get("ask") is not None):
        source = "xenon_ib"
        nbbo_bid, nbbo_ask = xq.get("bid"), xq.get("ask")
        iv = xq.get("iv")
        und = xq.get("und_spot") if xq.get("und_spot") is not None else underlying_spot
        source_asof = None
    elif uw_row is not None:
        source = "uw"
        nbbo_bid, nbbo_ask = uw_row.get("nbbo_bid"), uw_row.get("nbbo_ask")
        iv = uw_row.get("implied_volatility")
        und = underlying_spot
        source_asof = uw_row.get("source_asof")
    else:
        # no source at all — record nulls under the fallback tier, never crash
        source = "uw"
        nbbo_bid = nbbo_ask = iv = None
        und = underlying_spot
        source_asof = None

    # Greeks: IB-native primary (reflects IB's live surface), BS-from-IV backup,
    # then nulls. IB reports vega per-1% vol and theta per-day; rescale to argon's
    # bs_vega (per-100%) / bs_theta (per-year) column convention so IB and BS legs
    # share one unit. delta/gamma already match BS conventions (put delta -1..0).
    ib = (
        xq
        if source == "xenon_ib"
        and xq is not None
        and all(xq.get(g) is not None for g in ("delta", "gamma", "vega", "theta"))
        else None
    )
    if ib is not None:
        delta = float(ib["delta"])
        gamma = float(ib["gamma"])
        vega = float(ib["vega"]) * _IB_VEGA_TO_BS
        theta = float(ib["theta"]) * _IB_THETA_TO_BS
        greeks_source = "ib"
    elif iv is not None and float(iv) > 0:
        sig = float(iv)
        s = float(und) if und is not None else float(underlying_spot)
        k = float(strike)
        delta = bs_delta(s, k, T, r, sig, is_call=False)
        gamma = bs_gamma(s, k, T, r, sig)
        vega = bs_vega(s, k, T, r, sig)
        theta = bs_theta(s, k, T, r, sig, is_call=False)
        greeks_source = "bs"
    else:
        delta = gamma = vega = theta = 0.0
        greeks_source = "none"

    return LegQuote(
        strike=strike,
        nbbo_bid=nbbo_bid,
        nbbo_ask=nbbo_ask,
        iv=iv,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        und_spot=und,
        source=source,
        greeks_source=greeks_source,
        source_asof=source_asof,
    )
