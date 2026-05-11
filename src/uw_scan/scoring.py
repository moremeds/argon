from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreResult:
    score: int
    confirmations: list[str]
    warnings: list[str]


def score_flow_candidate(
    *,
    volume: int,
    open_interest: int | None,
    ask_side_pct: float,
    premium: float,
    is_single_leg: bool,
    moneyness_pct: float,
    dte: int,
) -> ScoreResult:
    score = 0
    confirmations: list[str] = []
    warnings: list[str] = []
    if open_interest is not None and volume > open_interest:
        score += 1
        confirmations.append("Volume > OI")
    if ask_side_pct >= 0.80:
        score += 1
        confirmations.append("Ask-side aggression")
    if premium >= 500_000:
        score += 1
        confirmations.append("Premium >= $500K")
    if is_single_leg:
        score += 1
        confirmations.append("Single-leg flow")
    if moneyness_pct <= 0.12:
        score += 1
        confirmations.append("Near the money")
    if dte < 6:
        score = max(0, score - 1)
        warnings.append("DTE below minimum")
    return ScoreResult(score=score, confirmations=confirmations, warnings=warnings)
