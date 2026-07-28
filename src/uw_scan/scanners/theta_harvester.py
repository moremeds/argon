"""Theta Harvester — short-strangle candidate finder over the warm store.

Ported from radon's scripts/theta_harvester_scanner.py. The structural
constants are verbatim; the score weights are NOT — radon's 25/25/20/15/10/5
gave 40 of its 100 points to terms that are constant once the critical gates
pass, so only the three discriminating components are scored here. They remain
unvalidated heuristics either way: radon persisted only a JSON blob per scan and
so could never score them. Argon persists per-candidate rows plus forward
markouts, which is what makes recalibration possible — see
docs/research/2026-07-28-radon-scanner-port-backlog.md.

RESEARCH MEASUREMENT ARTIFACT, NOT A TRADE PROPOSAL. A short strangle is
undefined-risk on both sides and violates argon's no-naked-shorts rule.

Pure compute: no DB, no I/O, no network. The repository layer feeds it rows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MIN_DTE = 7
MAX_DTE = 45
TARGET_DELTA = 0.16
NEAR_ZERO_DELTA = 0.10
# ponytail: flat constant, as radon. Wire rates_repository only if a markout
# shows term-structure sensitivity.
RISK_FREE_RATE = 0.045
TRADING_DAYS = 252


@dataclass(frozen=True)
class DealerSupport:
    """Where dealer gamma flips sign, and whether spot sits on the calm side."""

    label: str  # "SUPPORT" | "NO_SUPPORT" | "UNKNOWN"
    net_gex: float | None
    gex_flip: float | None


def realized_vol(closes: Sequence[float], window: int) -> float | None:
    """Annualised realised vol from the last `window` log returns.

    Returns None when there are not enough closes to fill the window — a
    partial window would understate vol and silently loosen the IV-edge gate.
    """
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1) :]
    rets = [
        # strict=False is load-bearing: tail[1:] is one shorter BY DESIGN
        # (n closes -> n-1 returns). strict=True raises on every call.
        math.log(b / a)
        for a, b in zip(tail, tail[1:], strict=False)
        if a > 0 and b > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def range_metrics(closes: Sequence[float], hv20: float) -> tuple[float, float] | None:
    """(21-session pct change, range_score in [0,1]), or None on thin history.

    range_score compares realised drift against the move HV20 implies over the
    SAME 21 sessions. Drift well inside that band -> range-bound -> good
    strangle tape.

    Returns None rather than (0.0, 0.0) when history is short: range_score 0.0
    means "violently trending", and encoding "unknown" as the worst possible
    score would silently fail the range gate on every newly-listed ticker.
    """
    if len(closes) < 22 or closes[-22] <= 0:
        return None
    trend_pct = (closes[-1] / closes[-22] - 1.0) * 100.0
    # 21 sessions, matching the trend window above — not 20. Using 20 here
    # understated the expected move by ~2.5% and silently tightened the gate.
    expected_pct = hv20 * math.sqrt(21.0 / TRADING_DAYS) * 100.0
    if expected_pct <= 0:
        return trend_pct, 0.0
    score = 1.0 - abs(trend_pct) / (expected_pct * 1.25)
    return trend_pct, max(0.0, min(1.0, score))


def dealer_support(
    gex_rows: Sequence[Mapping[str, object]], spot: float
) -> DealerSupport:
    """Locate the gamma flip and decide whether dealers damp or amplify moves.

    Sums call_gex+put_gex per strike, finds the highest strike at or below spot
    where cumulative net GEX crosses negative -> positive, and flags SUPPORT
    when total net GEX is positive AND spot is at or above that flip.
    """
    per_strike: dict[float, float] = {}
    for row in gex_rows:
        try:
            strike = float(row["strike"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            continue
        call = float(row.get("call_gex") or 0.0)  # type: ignore[union-attr]
        put = float(row.get("put_gex") or 0.0)  # type: ignore[union-attr]
        per_strike[strike] = per_strike.get(strike, 0.0) + call + put
    if not per_strike:
        return DealerSupport(label="UNKNOWN", net_gex=None, gex_flip=None)

    total = sum(per_strike.values())
    flip: float | None = None
    cumulative = 0.0
    crossed_negative = False
    for strike in sorted(per_strike):
        prev = cumulative
        cumulative += per_strike[strike]
        if prev < 0:
            crossed_negative = True
        if prev < 0 <= cumulative and strike <= spot:
            flip = strike

    # No crossing at all means cumulative net GEX never went negative, i.e.
    # dealers are long gamma across the whole strike ladder. Radon labelled
    # that NO_SUPPORT because it keyed on `flip is not None` — a false negative
    # on exactly the most unambiguously dealer-long names. Treat "never
    # negative AND total > 0" as SUPPORT with a null flip.
    if total <= 0:
        label = "NO_SUPPORT"
    elif flip is not None:
        label = "SUPPORT" if spot >= flip else "NO_SUPPORT"
    else:
        label = "NO_SUPPORT" if crossed_negative else "SUPPORT"
    return DealerSupport(label=label, net_gex=total, gex_flip=flip)
