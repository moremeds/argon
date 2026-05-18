"""Ranking - build_candidate, rank_candidates, bias + setup synthesis.

Port of xenon/scanners/uw/ranking.py + confluence.py, with Decimal
arithmetic and a candidate-suppression invariant when a ticker has
ONLY a dark_pool_accumulation hit (spec §5; xenon's `build_candidate`
returns None when non_dp_hits is empty).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from uw_scan.scanner.models import ContextFlag, ScanCandidate, SignalHit

# Tier weights - lower tier number = higher weight (xenon convention).
RANKING_TIER_WEIGHTS: dict[int, Decimal] = {1: Decimal("3.0"), 2: Decimal("1.5")}

# Signals that contribute to confluence but NOT to raw_score. Keeps a
# DP-only ticker from emitting a candidate at all (handled below).
RAW_RANKING_EXCLUDE: frozenset[str] = frozenset({"dark_pool_accumulation"})

# Bias is derived from DCF only — EIC (vol positioning) and GEX (magnet)
# are non-directional, DP is direction-neutral by construction.
DIRECTIONAL_SIGNAL_TYPES: frozenset[str] = frozenset({"deep_conviction_flow"})

Bias = Literal["bullish", "bearish", "neutral", "mixed"]
BiasStrength = Literal["strong", "moderate", "weak"]
SetupStatus = Literal["ready", "caution", "blocked"]


def _confluence(hits: Iterable[SignalHit]) -> Decimal:
    return sum(
        (RANKING_TIER_WEIGHTS.get(h.tier, Decimal("0")) for h in hits),
        Decimal("0"),
    )


def _is_type_f(hits: Iterable[SignalHit]) -> bool:
    non_dp_types = {
        h.signal_type for h in hits if h.signal_type not in RAW_RANKING_EXCLUDE
    }
    return len(non_dp_types) >= 2


def derive_bias(hits: Iterable[SignalHit]) -> tuple[Bias, BiasStrength | None]:
    """Roll directional hits into a single (bias, strength) for the tile header.

    Only DCF votes. Strength is scaled by the strongest DCF score:
    >= 0.9 strong, >= 0.7 moderate, else weak. The DCF score formula
    (signals/deep_conviction_flow.py:111) maps premium directly to
    score, so strength tracks premium magnitude.
    """
    directional = [h for h in hits if h.signal_type in DIRECTIONAL_SIGNAL_TYPES]
    if not directional:
        return ("neutral", None)

    directions: set[Bias] = set()
    max_score = Decimal("0")
    for h in directional:
        d = h.evidence.get("direction")
        if d == "long":
            directions.add("bullish")
        elif d == "short":
            directions.add("bearish")
        if h.score > max_score:
            max_score = h.score

    if not directions:
        return ("neutral", None)
    if len(directions) > 1:
        return ("mixed", None)

    bias = directions.pop()
    if max_score >= Decimal("0.9"):
        strength: BiasStrength = "strong"
    elif max_score >= Decimal("0.7"):
        strength = "moderate"
    else:
        strength = "weak"
    return (bias, strength)


def derive_setup(gates: dict[str, str]) -> tuple[SetupStatus, str | None]:
    """Roll gate pass/block into a single setup-quality chip + reason.

    `ready` when all three gates pass. `blocked` only when regime blocks
    (a hard veto — currently unreachable since regime is a no-op shim).
    Otherwise `caution`, with the first blocking gate reported as reason.
    """
    if gates.get("regime") == "block":
        return ("blocked", "regime")
    blockers = [k for k in ("earnings", "liquidity") if gates.get(k) == "block"]
    if not blockers:
        return ("ready", None)
    return ("caution", blockers[0])


def build_candidate(
    *,
    ticker: str,
    hits: list[SignalHit],
    context_flags: list[ContextFlag],
    gates: dict[str, str],
) -> ScanCandidate | None:
    """Build a candidate or return None if no non-DP hits.

    The None-return guarantees a ticker whose ONLY hit is
    dark_pool_accumulation never appears as a candidate
    (matches xenon ranking.py:18-19).
    """
    non_dp_hits = [h for h in hits if h.signal_type not in RAW_RANKING_EXCLUDE]
    if not non_dp_hits:
        return None

    raw_score = sum(
        (h.score * RANKING_TIER_WEIGHTS.get(h.tier, Decimal("0")) for h in non_dp_hits),
        Decimal("0"),
    )
    confluence = _confluence(hits)
    final_score = raw_score + confluence
    bias, bias_strength = derive_bias(hits)
    setup, setup_reason = derive_setup(gates)
    return ScanCandidate(
        ticker=ticker.upper(),
        hits=list(hits),
        context_flags=list(context_flags),
        raw_score=raw_score,
        confluence_score=confluence,
        final_score=final_score,
        is_type_f=_is_type_f(hits),
        gates=dict(gates),
        bias=bias,
        bias_strength=bias_strength,
        setup=setup,
        setup_reason=setup_reason,
    )


def rank_candidates(candidates: Iterable[ScanCandidate]) -> list[ScanCandidate]:
    """Sort: is_type_f desc, final_score desc, ticker asc (deterministic)."""
    return sorted(
        candidates,
        key=lambda c: (not c.is_type_f, -c.final_score, c.ticker),
    )
