"""Per-(expiry) derivations on raw greek-exposure rows.

Pure functions: take ``list[GreekExposureRow]`` (already filtered to one expiry by
the caller) and return derived summary values. No DB access — the assembler in
``reports/`` owns the I/O, mirroring the ``cards/gex.py`` pattern.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from uw_scan.models import ExposuresSummaryRow, GreekExposureRow

log = logging.getLogger(__name__)


NEUTRAL_VANNA_THRESHOLD = Decimal("1000")
"""|net_vanna| below this is reported as 'neutral' regime."""

NEUTRAL_CHARM_THRESHOLD = Decimal("1000")
"""|net_charm| below this is reported as 'flat' / 'mixed' signal quality."""

ONE_VOL_POINT = Decimal("0.01")
"""UW vanna is dDelta per 1.0 of IV (decimal). 1pt IV move = 0.01."""


# --- vanna helpers ---------------------------------------------------------


def _per_strike_net_vanna(rows: list[GreekExposureRow]) -> dict[Decimal, Decimal]:
    acc: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in rows:
        if r.call_vanna is not None:
            acc[r.strike] += r.call_vanna
        if r.put_vanna is not None:
            acc[r.strike] += r.put_vanna
    return dict(acc)


def net_vanna(rows: list[GreekExposureRow]) -> Decimal | None:
    """Σ (call_vanna + put_vanna) across every row. None when no inputs."""
    if not rows:
        return None
    total = Decimal("0")
    any_present = False
    for r in rows:
        if r.call_vanna is not None:
            total += r.call_vanna
            any_present = True
        if r.put_vanna is not None:
            total += r.put_vanna
            any_present = True
    return total if any_present else None


def top_vanna_strike(
    rows: list[GreekExposureRow],
) -> tuple[Decimal, Decimal] | None:
    """The (strike, net_vanna) pair with the largest |net_vanna|."""
    per = _per_strike_net_vanna(rows)
    if not per:
        return None
    strike = max(per.items(), key=lambda kv: abs(kv[1]))[0]
    return strike, per[strike]


def delta_shock_1pt_iv(rows: list[GreekExposureRow]) -> Decimal | None:
    """Net Δ dealers must hedge if IV rises 1 vol-point."""
    nv = net_vanna(rows)
    if nv is None:
        return None
    return nv * ONE_VOL_POINT


def vanna_regime(net_vanna_value: Decimal | None) -> str:
    """`procyclical` / `countercyclical` / `neutral`."""
    if net_vanna_value is None:
        return "neutral"
    if abs(net_vanna_value) < NEUTRAL_VANNA_THRESHOLD:
        return "neutral"
    return "procyclical" if net_vanna_value > 0 else "countercyclical"


def vanna_flip(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> Decimal | None:
    """Strike where running cumulative net_vanna changes sign.

    Iterates strikes ascending and collects EVERY sign-flip strike. Spec asks
    for the lowest sign-flip ≥ spot; fall back to the absolute lowest flip
    when no flip is at/above spot (or when spot is unknown).
    """
    if not rows:
        return None
    per = _per_strike_net_vanna(rows)
    if not per:
        return None
    flips: list[Decimal] = []
    cum = Decimal("0")
    prev_sign = 0
    for strike, val in sorted(per.items(), key=lambda kv: kv[0]):
        cum += val
        sign = (cum > 0) - (cum < 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            flips.append(strike)
        if sign != 0:
            prev_sign = sign
    if not flips:
        return None
    if spot is None:
        return flips[0]
    above = [s for s in flips if s >= spot]
    return above[0] if above else flips[0]


def vanna_narrative(
    net_vanna_value: Decimal | None,
    regime: str,
) -> tuple[str, str]:
    """Deterministic headline + subtitle keyed off net sign and regime."""
    if net_vanna_value is None or regime == "neutral":
        return (
            "Neutral Vanna — IV moves have limited dealer-Δ impact",
            "Net vanna positioning is balanced; dealer hedging is not a strong driver.",
        )
    if net_vanna_value > 0:
        return (
            "Long Vanna — IV spikes pressure stock lower via dealer selling",
            "If IV rises, dealers gain delta and will likely sell stock to rehedge — a headwind during vol spikes.",
        )
    return (
        "Short Vanna — IV spikes support stock via dealer buying",
        "If IV rises, dealers lose delta and will likely buy stock to rehedge — a tailwind during vol spikes.",
    )


# --- charm helpers ---------------------------------------------------------


def _per_strike_net_charm(rows: list[GreekExposureRow]) -> dict[Decimal, Decimal]:
    acc: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in rows:
        if r.call_charm is not None:
            acc[r.strike] += r.call_charm
        if r.put_charm is not None:
            acc[r.strike] += r.put_charm
    return dict(acc)


def net_charm(rows: list[GreekExposureRow]) -> Decimal | None:
    if not rows:
        return None
    total = Decimal("0")
    any_present = False
    for r in rows:
        if r.call_charm is not None:
            total += r.call_charm
            any_present = True
        if r.put_charm is not None:
            total += r.put_charm
            any_present = True
    return total if any_present else None


def charm_pin_strike(rows: list[GreekExposureRow]) -> Decimal | None:
    per = _per_strike_net_charm(rows)
    if not per:
        return None
    return max(per.items(), key=lambda kv: abs(kv[1]))[0]


def charm_imbalance(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal | None]:
    """(above_sum, below_sum, imbalance_pct).

    above_sum = Σ net_charm for strikes > spot.
    below_sum = Σ net_charm for strikes < spot.
    imbalance_pct = |above - below| / (|above| + |below|) — 0.0 balanced, 1.0 fully one-sided.
    """
    if spot is None:
        return Decimal("0"), Decimal("0"), None
    above = Decimal("0")
    below = Decimal("0")
    per = _per_strike_net_charm(rows)
    for strike, val in per.items():
        if strike > spot:
            above += val
        elif strike < spot:
            below += val
    denom = abs(above) + abs(below)
    imb = (abs(above - below) / denom) if denom != 0 else None
    return above, below, imb


def charm_signal_quality(live: Decimal | None, positioning: Decimal | None) -> str:
    """`aligned` when same sign + nonzero; `mixed` opposing; `weak` either near 0."""
    if live is None or positioning is None:
        return "weak"
    if (
        abs(live) < NEUTRAL_CHARM_THRESHOLD
        or abs(positioning) < NEUTRAL_CHARM_THRESHOLD
    ):
        return "weak"
    same_sign = (live > 0 and positioning > 0) or (live < 0 and positioning < 0)
    return "aligned" if same_sign else "mixed"


def charm_flip(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> Decimal | None:
    """Same selection rule as vanna_flip: lowest sign-flip ≥ spot, fallback to lowest."""
    if not rows:
        return None
    per = _per_strike_net_charm(rows)
    if not per:
        return None
    flips: list[Decimal] = []
    cum = Decimal("0")
    prev_sign = 0
    for strike, val in sorted(per.items(), key=lambda kv: kv[0]):
        cum += val
        sign = (cum > 0) - (cum < 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            flips.append(strike)
        if sign != 0:
            prev_sign = sign
    if not flips:
        return None
    if spot is None:
        return flips[0]
    above = [s for s in flips if s >= spot]
    return above[0] if above else flips[0]


def charm_narrative(
    net_charm_value: Decimal | None,
    signal_quality: str,
) -> tuple[str, str]:
    if net_charm_value is None or signal_quality == "weak":
        return (
            "Limited charm pressure into the close",
            "Net charm positioning is balanced or thin; mechanical hedging pressure is muted.",
        )
    if net_charm_value < 0:
        return (
            "Mechanical SELL pressure into the close",
            "Dealer sell pressure may cap rallies as theta drives delta unwind.",
        )
    return (
        "Mechanical BUY pressure into the close",
        "Dealer buy pressure may support the tape as theta drives delta accumulation.",
    )


# --- top-level builder -----------------------------------------------------


def build_summary_rows(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> list[ExposuresSummaryRow]:
    """Group rows by expiry; for each expiry, compute the full summary tuple."""
    if not rows:
        return []

    # Group by expiry ONLY — the table PK is (run_id, ticker, expiry) so
    # multiple (expiry, dte) groups would collide on upsert. UW occasionally
    # returns mixed dte values for the same expiry across strikes (rounding,
    # late-day refresh boundaries); take the min non-null dte per expiry.
    by_expiry: dict[date, list[GreekExposureRow]] = defaultdict(list)
    for r in rows:
        by_expiry[r.expiry].append(r)

    out: list[ExposuresSummaryRow] = []
    for expiry, grp in sorted(by_expiry.items(), key=lambda kv: kv[0]):
        dtes = [r.dte for r in grp if r.dte is not None]
        dte = min(dtes) if dtes else None
        nv = net_vanna(grp)
        top = top_vanna_strike(grp)
        v_regime = vanna_regime(nv)
        v_flip = vanna_flip(grp, spot)
        v_head, v_sub = vanna_narrative(nv, v_regime)

        nc = net_charm(grp)
        pin = charm_pin_strike(grp)
        above, below, imb = charm_imbalance(grp, spot)
        c_quality = charm_signal_quality(live=nc, positioning=above - below)
        c_flip = charm_flip(grp, spot)
        c_head, c_sub = charm_narrative(nc, c_quality)

        out.append(
            ExposuresSummaryRow(
                expiry=expiry,
                dte=dte,
                spot=spot,
                net_vanna=nv,
                top_vanna_strike=top[0] if top else None,
                top_vanna_value=top[1] if top else None,
                delta_shock_1pt_iv=delta_shock_1pt_iv(grp),
                vanna_regime=v_regime,
                vanna_flip=v_flip,
                vanna_headline=v_head,
                vanna_subtitle=v_sub,
                net_charm=nc,
                charm_pin_strike=pin,
                charm_above_sum=above,
                charm_below_sum=below,
                charm_imbalance_pct=imb,
                charm_signal_quality=c_quality,
                charm_flip=c_flip,
                charm_headline=c_head,
                charm_subtitle=c_sub,
            )
        )
    return out
