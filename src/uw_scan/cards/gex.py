"""Pure derivations on the per-strike, per-expiry GEX curve."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from uw_scan.models import GexLevel, MarketStructureLevels, StrikeGexBucket


def _aggregate_per_strike(
    curve: list[StrikeGexBucket],
) -> dict[Decimal, tuple[Decimal, Decimal, Decimal]]:
    """Sum each strike's gamma fields across expiries. Returns
    {strike -> (net_gex, call_gex, put_gex)}."""
    net: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    call: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    put: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for b in curve:
        if b.net_gex is not None:
            net[b.strike] += b.net_gex
        if b.call_gex is not None:
            call[b.strike] += b.call_gex
        if b.put_gex is not None:
            put[b.strike] += b.put_gex
    strikes = set(net) | set(call) | set(put)
    return {s: (net[s], call[s], put[s]) for s in strikes}


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


def _make_level(
    strike: Decimal,
    spot: Decimal | None,
    net_gex: Decimal,
) -> GexLevel:
    pct = ((strike - spot) / spot) if spot else None
    return GexLevel(
        strike=strike,
        net_gex=net_gex,
        pct_from_spot=pct,
        gamma_per_dollar=net_gex,
    )


def compute_market_structure_levels(
    curve: list[StrikeGexBucket],
    spot: Decimal | None,
) -> MarketStructureLevels:
    """Derive the 6 reference levels used by the Market Structure tab.

    See MarketStructureLevels docstring for definitions. All None when the curve
    is empty or spot is missing.
    """
    levels = MarketStructureLevels()
    if not curve or spot is None:
        return levels

    agg = _aggregate_per_strike(curve)
    if not agg:
        return levels

    flip_strike = find_flip_strike(curve)
    if flip_strike is not None and flip_strike in agg:
        levels.gex_flip = _make_level(flip_strike, spot, agg[flip_strike][0])

    # CALL WALL: largest call-side gamma — typically above spot, acts as resistance.
    call_candidates = [(s, c) for s, (_, c, _) in agg.items() if c > 0]
    if call_candidates:
        s, _ = max(call_candidates, key=lambda kv: kv[1])
        levels.call_wall = _make_level(s, spot, agg[s][0])

    # PUT WALL: largest put-side gamma magnitude — typically below spot, acts as support.
    # put_gex is stored as a positive magnitude in our data; if it's signed, abs() handles both.
    put_candidates = [(s, p) for s, (_, _, p) in agg.items() if p != 0]
    if put_candidates:
        s, _ = max(put_candidates, key=lambda kv: abs(kv[1]))
        levels.put_wall = _make_level(s, spot, agg[s][0])

    # MAGNETS: positive net_gex strikes ABOVE spot, ranked by net_gex desc.
    above_pos = sorted(
        ((s, n) for s, (n, _, _) in agg.items() if s > spot and n > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if above_pos:
        levels.max_magnet = _make_level(above_pos[0][0], spot, above_pos[0][1])
    if len(above_pos) > 1:
        levels.second_magnet = _make_level(above_pos[1][0], spot, above_pos[1][1])

    # MAX ACCEL: most-negative net_gex below the flip (where moves accelerate).
    # Falls back to "below spot" when there's no flip yet.
    floor = flip_strike if flip_strike is not None else spot
    below_neg = sorted(
        ((s, n) for s, (n, _, _) in agg.items() if s < floor and n < 0),
        key=lambda kv: kv[1],
    )
    if below_neg:
        levels.max_accel = _make_level(below_neg[0][0], spot, below_neg[0][1])

    return levels


def classify_bias(
    spot: Decimal | None,
    gex_flip: Decimal | None,
    net_gex: Decimal | None,
) -> str:
    """Directional regime label from spot relative to flip + net gamma sign.

    BULL = above flip + positive gamma (stabilizing).
    BEAR = below flip + negative gamma (destabilizing).
    CAUTIOUS_BULL / CAUTIOUS_BEAR = direction matches, gamma sign doesn't.
    NEUTRAL = any input missing.
    """
    if spot is None or gex_flip is None or net_gex is None:
        return "NEUTRAL"
    above = spot > gex_flip
    stabilizing = net_gex > 0
    if above and stabilizing:
        return "BULL"
    if not above and not stabilizing:
        return "BEAR"
    if above:
        return "CAUTIOUS_BULL"
    return "CAUTIOUS_BEAR"
