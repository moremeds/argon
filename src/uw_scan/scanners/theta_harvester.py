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
from datetime import date

from uw_scan.reports.vrp_structure import bs_price

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


@dataclass(frozen=True)
class OptionLeg:
    expiry: date
    strike: float
    right: str  # "C" | "P"
    iv: float
    delta: float
    theta: float
    gamma: float
    vega: float


@dataclass(frozen=True)
class Strangle:
    """A SHORT strangle. Greeks are POSITION-signed, not contract-signed.

    OptionLeg carries argon's stored convention (long contract: theta <= 0,
    gamma >= 0, vega >= 0 — verified against option_surface_grid_daily). Being
    short flips all of them, so for a healthy candidate:
        theta > 0  (decay accrues to us)
        gamma < 0  (we are short convexity)
        vega  < 0  (we are short vol)
    Radon's gates are written against these position signs; passing the raw
    long-contract greeks through would make `theta > 0` unsatisfiable and
    render the THETA_HARVEST verdict unreachable.
    """

    expiry: date
    dte: int
    put: OptionLeg
    call: OptionLeg
    net_delta: float
    theta: float
    gamma: float
    vega: float


def select_short_strangle(
    legs: Sequence[OptionLeg],
    spot: float,
    as_of: date,
    *,
    min_dte: int = MIN_DTE,
    max_dte: int = MAX_DTE,
) -> Strangle | None:
    """Cheapest-scoring OTM short strangle within the DTE window.

    Radon's selection score, verbatim: delta neutrality dominates, each leg is
    pulled toward TARGET_DELTA, ~30 DTE is mildly preferred, and a
    non-positive-theta pair is heavily penalised. Lower is better.

    `legs` carry argon's stored LONG-contract greeks; the returned Strangle
    carries SHORT-position greeks. The negation happens here, at the single
    boundary between storage convention and radon's gate convention.
    """
    calls: list[OptionLeg] = []
    puts: list[OptionLeg] = []
    for leg in legs:
        dte = (leg.expiry - as_of).days
        if not (min_dte <= dte <= max_dte):
            continue
        mag = abs(leg.delta)
        if not (0.05 <= mag <= 0.35):
            continue
        if leg.right == "C" and leg.strike > spot:
            calls.append(leg)
        elif leg.right == "P" and leg.strike < spot:
            puts.append(leg)

    best: Strangle | None = None
    best_key: tuple[float, date, float, float] | None = None
    for call in calls:
        for put in puts:
            if call.expiry != put.expiry:
                continue
            dte = (call.expiry - as_of).days
            # Negate: legs are long-contract, the position is short.
            net_delta = -(call.delta + put.delta)
            theta = -(call.theta + put.theta)
            gamma = -(call.gamma + put.gamma)
            vega = -(call.vega + put.vega)
            score = (
                abs(net_delta) * 100
                + abs(abs(call.delta) - TARGET_DELTA) * 20
                + abs(abs(put.delta) - TARGET_DELTA) * 20
                + abs(dte - 30) / 10
                + (0 if theta > 0 else 20)
            )
            # Strict `<` alone leaves ties resolved by row arrival order, which
            # Postgres does not guarantee — the same session could pick a
            # different structure on a rescan and invalidate its own markouts.
            # Break ties deterministically on the contract identity itself.
            key = (score, call.expiry, put.strike, call.strike)
            if best_key is None or key < best_key:
                best_key = key
                best = Strangle(
                    expiry=call.expiry,
                    dte=dte,
                    put=put,
                    call=call,
                    net_delta=net_delta,
                    theta=theta,
                    gamma=gamma,
                    vega=vega,
                )
    return best


@dataclass(frozen=True)
class ScoreWeights:
    """The entire tunable surface. Every field is swept by the weight sweep.

    Radon's 100-point score was 25 delta / 25 vol / 20 dealer / 15 theta /
    10 range / 5 gamma. Three of those six are CONSTANT once the critical
    gates pass: `dealer_support` is itself a critical gate, `theta > 0` is a
    critical gate, and `gamma < 0` is implied by a delta-balanced short
    strangle. 40 of 100 points therefore never discriminate between eligible
    candidates. We score only the three components that actually vary and
    keep the rest as gates -- gates gate, scores score.

    `edge_saturation_pts` matters more than the weight. Radon's
    `min(25, edge * 2.5)` maxes out at 10 vol points of IV-RV. Measured on
    the mini 2026-07-29 over the 1 090 (ticker, session) pairs that have both
    a grid capture and an `iv_rank_history` reading, `(IV - HV20) * 100` is
    distributed p50 2.14 / p75 6.53 / p90 14.34 / p95 19.16 / p99 36.13, and
    32.7% clear the `edge >= 5` gate. Radon's cap therefore sat at ~p85 and
    pinned the term for the whole top decile. The default saturates at 15 --
    p90 rounded -- so "full vol credit" means top-decile richness.

    `dealer_gate_critical` defaults False. Radon had it True, but the
    strike-level GEX feed (`exposures_by_expiry_strike`) only starts
    2026-05, while the IV grid starts 2025-12-26. Requiring it collapses
    the backtestable entry universe from 116 sessions to 24 -- and the dealer-
    gamma-support premise has no peer-reviewed support to justify that cost.
    It is swept as a parameter rather than decided by assertion.
    """

    vol_edge: float = 55.0
    delta_neutrality: float = 25.0
    range_bound: float = 20.0
    edge_saturation_pts: float = 15.0
    threshold: float = 70.0
    dealer_gate_critical: bool = False

    @property
    def version(self) -> str:
        """Stable provenance tag persisted on every candidate row."""
        return (
            f"v{self.vol_edge:g}/{self.delta_neutrality:g}/{self.range_bound:g}"
            f"@{self.edge_saturation_pts:g}t{self.threshold:g}"
            f"{'d' if self.dealer_gate_critical else ''}"
        )


DEFAULT_WEIGHTS = ScoreWeights()

# Radon's original, kept as a named sweep point so "did the reweight help?"
# is a question the sweep answers rather than one this module asserts.
#
# Threshold is 30, not radon's 70, and that is not a change in strictness:
# radon's 70 was measured on a scale carrying a constant +40 (dealer 20 +
# theta 15 + gamma 5, all implied once the critical gates pass). Dropping the
# constant shifts every score down by exactly 40, so 70 - 40 = 30 is the
# SAME cut. `test_radon_weights_reproduce_the_original_score` pins the
# identity on the real IWM fixture: 54.192171 + 40 == 94.192171, which is the
# number radon's formula produces for that row.
RADON_WEIGHTS = ScoreWeights(
    vol_edge=25.0,
    delta_neutrality=25.0,
    range_bound=10.0,
    edge_saturation_pts=10.0,
    threshold=30.0,
    dealer_gate_critical=True,
)


def score_from_components(
    *,
    iv_rv_edge: float,
    net_delta: float,
    range_score: float,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> float:
    """Pure function of three persisted columns -- that is the whole point.

    `theta_harvester_candidates` stores `iv_rv_edge`, `net_delta` and
    `range_score` raw, so any weight vector can be re-scored over the full
    backfill with a single pass and NO rescan. The stored `score` column is
    a display convenience; this function is the truth.
    """
    vol_c = min(1.0, max(0.0, iv_rv_edge / weights.edge_saturation_pts))
    delta_c = max(0.0, 1.0 - abs(net_delta) / NEAR_ZERO_DELTA)
    range_c = min(1.0, max(0.0, range_score))
    return (
        weights.vol_edge * vol_c
        + weights.delta_neutrality * delta_c
        + weights.range_bound * range_c
    )


@dataclass(frozen=True)
class ThetaCandidate:
    ticker: str
    as_of: date
    structure: Strangle
    spot: float
    iv: float
    hv20: float
    hv60: float | None
    iv_rv_edge: float
    iv_rv_ratio: float
    trend_20d_pct: float
    range_score: float
    dealer: DealerSupport
    score: float
    weights_version: str
    verdict: str
    gates: dict[str, bool]
    put_mark: float
    call_mark: float
    entry_credit_theo: float
    risk_free_rate: float  # the rate the marks were priced at, carried so the
    # markout re-prices at the SAME rate it entered at


def build_candidate(
    *,
    ticker: str,
    as_of: date,
    structure: Strangle,
    spot: float,
    iv: float,
    hv20: float,
    hv60: float | None,
    trend_20d_pct: float,
    range_score: float,
    dealer: DealerSupport,
    r: float = RISK_FREE_RATE,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> ThetaCandidate:
    """Apply the gates and score, and mark the entry.

    entry_credit_theo prices BOTH legs off the same grid IV the markout job
    will re-read. Mixing an IB NBBO entry with grid-IV marks would bake a
    constant bid-ask bias into every forward P&L.
    """
    iv_rv_edge = (iv - hv20) * 100.0
    iv_rv_ratio = (iv / hv20) if hv20 > 0 else 0.0

    gates = {
        "delta_near_zero": abs(structure.net_delta) <= NEAR_ZERO_DELTA,
        "iv_rich_vs_rv": iv_rv_edge >= 5.0 or iv_rv_ratio >= 1.10,
        "dealer_support": dealer.label == "SUPPORT",
        "theta_positive": structure.theta > 0,
        "gamma_controlled": structure.gamma < 0 and abs(structure.net_delta) <= 0.20,
        "range_bound": range_score >= 0.35,
    }

    score = score_from_components(
        iv_rv_edge=iv_rv_edge,
        net_delta=structure.net_delta,
        range_score=range_score,
        weights=weights,
    )

    critical = (
        gates["delta_near_zero"]
        and gates["iv_rich_vs_rv"]
        and gates["theta_positive"]
        and (gates["dealer_support"] or not weights.dealer_gate_critical)
    )
    if critical and score >= weights.threshold:
        verdict = "THETA_HARVEST"
    elif abs(structure.net_delta) > 0.20 or not gates["iv_rich_vs_rv"]:
        verdict = "DIRECTIONAL_DISGUISE"
    else:
        verdict = "WATCHLIST"

    t_years = max(structure.dte, 0) / 365.0
    put_mark = bs_price(
        spot, structure.put.strike, t_years, r, structure.put.iv, is_call=False
    )
    call_mark = bs_price(
        spot, structure.call.strike, t_years, r, structure.call.iv, is_call=True
    )

    return ThetaCandidate(
        ticker=ticker,
        as_of=as_of,
        structure=structure,
        spot=spot,
        iv=iv,
        hv20=hv20,
        hv60=hv60,
        iv_rv_edge=iv_rv_edge,
        iv_rv_ratio=iv_rv_ratio,
        trend_20d_pct=trend_20d_pct,
        range_score=range_score,
        dealer=dealer,
        score=score,
        weights_version=weights.version,
        verdict=verdict,
        gates=gates,
        put_mark=put_mark,
        call_mark=call_mark,
        entry_credit_theo=put_mark + call_mark,
        risk_free_rate=r,
    )
