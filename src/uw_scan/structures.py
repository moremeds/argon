from __future__ import annotations

from uw_scan.models import SignalDirection, StructureIdea


def suggest_structure(*, direction: SignalDirection, setup_types: list[str], iv_rank: float | None) -> StructureIdea:
    if "Earnings IV Crush" in setup_types and iv_rank is not None and iv_rank >= 75:
        return StructureIdea(
            structure_type="Defined-risk iron condor candidate",
            rationale="High IV earnings setup favors defined-risk premium sale candidate.",
            invalidation="Avoid if liquidity is poor or event risk is binary and unpriceable.",
        )
    if direction == SignalDirection.BULLISH and "Deep Conviction Directional" in setup_types:
        return StructureIdea(
            structure_type="Call debit spread candidate",
            rationale="Bullish high-conviction flow with defined-risk directional expression.",
            invalidation="Downgrade if OI follow-through fails or skew warns against calls.",
        )
    if direction == SignalDirection.BEARISH and "Deep Conviction Directional" in setup_types:
        return StructureIdea(
            structure_type="Put debit spread candidate",
            rationale="Bearish high-conviction flow with defined-risk directional expression.",
            invalidation="Downgrade if OI follow-through fails or put skew is already extreme.",
        )
    return StructureIdea(
        structure_type="Watchlist only",
        rationale="Signal is interesting but does not meet a stronger structure rule.",
        invalidation="Wait for stronger flow, OI, IV, or liquidity confirmation.",
    )
