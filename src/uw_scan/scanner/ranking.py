"""Ranking - build_candidate, rank_candidates.

Port of xenon/scanners/uw/ranking.py + confluence.py, with Decimal
arithmetic and a candidate-suppression invariant when a ticker has
ONLY a dark_pool_accumulation hit (spec §5; xenon's `build_candidate`
returns None when non_dp_hits is empty).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from uw_scan.scanner.models import ContextFlag, ScanCandidate, SignalHit

# Tier weights - lower tier number = higher weight (xenon convention).
RANKING_TIER_WEIGHTS: dict[int, Decimal] = {1: Decimal("3.0"), 2: Decimal("1.5")}

# Signals that contribute to confluence but NOT to raw_score. Keeps a
# DP-only ticker from emitting a candidate at all (handled below).
RAW_RANKING_EXCLUDE: frozenset[str] = frozenset({"dark_pool_accumulation"})


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
        (
            h.score * RANKING_TIER_WEIGHTS.get(h.tier, Decimal("0"))
            for h in non_dp_hits
        ),
        Decimal("0"),
    )
    confluence = _confluence(hits)
    final_score = raw_score + confluence
    return ScanCandidate(
        ticker=ticker.upper(),
        hits=list(hits),
        context_flags=list(context_flags),
        raw_score=raw_score,
        confluence_score=confluence,
        final_score=final_score,
        is_type_f=_is_type_f(hits),
        gates=dict(gates),
    )


def rank_candidates(candidates: Iterable[ScanCandidate]) -> list[ScanCandidate]:
    """Sort: is_type_f desc, final_score desc, ticker asc (deterministic)."""
    return sorted(
        candidates,
        key=lambda c: (not c.is_type_f, -c.final_score, c.ticker),
    )
