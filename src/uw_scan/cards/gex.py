"""Pure derivations on the per-strike, per-expiry GEX curve."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from uw_scan.models import StrikeGexBucket


def find_flip_strike(curve: list[StrikeGexBucket]) -> Decimal | None:
    """Return the lowest strike at which the per-strike aggregated net_gex
    changes sign relative to the previous (lower) strike. None if the curve
    never crosses zero.

    Per-strike net_gex is summed across expiries first — "GEX Flip" is a single
    price level where dealer hedging direction inverts.
    """
    if not curve:
        return None
    per_strike: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            per_strike[b.strike] += b.net_gex
    items = sorted(per_strike.items(), key=lambda kv: kv[0])
    prev_sign = 0
    for strike, ngex in items:
        sign = (ngex > 0) - (ngex < 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            return strike
        if sign != 0:
            prev_sign = sign
    return None


def max_gex_strike(curve: list[StrikeGexBucket]) -> Decimal | None:
    """The strike with the largest absolute aggregated net_gex (across expiries)."""
    if not curve:
        return None
    per_strike: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            per_strike[b.strike] += b.net_gex
    if not per_strike:
        return None
    return max(per_strike.items(), key=lambda kv: abs(kv[1]))[0]


def gex_expiring_pct(curve: list[StrikeGexBucket]) -> Decimal | None:
    """|net_gex @ nearest_expiry| / sum(|net_gex_by_expiry|).

    None when the curve is empty OR every per-expiry net_gex sums to exactly zero.
    """
    if not curve:
        return None
    by_expiry: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            by_expiry[b.expiry] += b.net_gex
    if not by_expiry:
        return None
    nearest = min(by_expiry.keys())
    denom = sum((abs(v) for v in by_expiry.values()), Decimal("0"))
    if denom == 0:
        return None
    return abs(by_expiry[nearest]) / denom


def nearest_expiry(curve: list[StrikeGexBucket]) -> date | None:
    if not curve:
        return None
    return min(b.expiry for b in curve)
