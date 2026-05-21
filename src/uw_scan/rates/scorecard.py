"""Rates scorecard rules derived from available live inputs."""

from __future__ import annotations

from collections.abc import Sequence

from uw_scan.models import (
    RatesScorecard,
    RatesScorecardFactor,
    RatesScorecardGroup,
)


DEFAULT_SCORECARD_GROUPS: list[RatesScorecardGroup] = [
    RatesScorecardGroup(id="policy", label="Monetary Policy", weight=25),
    RatesScorecardGroup(id="macro", label="Macro Fundamentals", weight=25),
    RatesScorecardGroup(id="supply", label="Supply & Technicals", weight=15),
    RatesScorecardGroup(id="positioning", label="Demand & Positioning", weight=15),
    RatesScorecardGroup(id="relative_value", label="Relative Value", weight=10),
    RatesScorecardGroup(id="sentiment", label="Sentiment & Liquidity", weight=10),
]


def score_group(group: RatesScorecardGroup) -> float | None:
    scores: list[float] = []
    for factor in group.factors:
        score = (
            factor.score
            if isinstance(factor, RatesScorecardFactor)
            else factor.get("score")
        )
        if score is not None:
            scores.append(float(score))
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def compute_composite_score(groups: Sequence[RatesScorecardGroup]) -> float | None:
    weighted = 0.0
    total_weight = 0.0
    for group in groups:
        if group.score is None:
            continue
        weighted += float(group.score) * float(group.weight)
        total_weight += float(group.weight)
    if total_weight == 0:
        return None
    return round(weighted / total_weight, 2)


def build_scorecard(
    *,
    ten_year_1m_delta_bps: float | None,
    curve_score: float | None,
    effr: float | None,
    real_10y: float | None,
    breakeven_10y: float | None,
) -> RatesScorecard:
    groups = [group.model_copy(deep=True) for group in DEFAULT_SCORECARD_GROUPS]
    by_id = {group.id: group for group in groups}

    by_id["policy"].factors = [
        RatesScorecardFactor(
            label="Effective fed funds rate",
            value=f"{effr:.2f}%" if effr is not None else None,
            score=_policy_score(effr),
            status="ok" if effr is not None else "missing",
            source="FRED:EFFR",
        )
    ]
    by_id["macro"].factors = [
        RatesScorecardFactor(
            label="Macro inflation/growth feeds",
            value=None,
            score=None,
            status="missing",
            source="Phase 2 official macro feeds",
        )
    ]
    by_id["supply"].factors = [
        RatesScorecardFactor(
            label="Treasury auctions and QRA",
            value=None,
            score=None,
            status="missing",
            source="Phase 2 Treasury FiscalData/QRA",
        )
    ]
    by_id["positioning"].factors = [
        RatesScorecardFactor(
            label="CFTC/TIC positioning",
            value=None,
            score=None,
            status="missing",
            source="Phase 2 CFTC/TIC",
        )
    ]
    by_id["relative_value"].factors = [
        RatesScorecardFactor(
            label="10Y real yield",
            value=f"{real_10y:.2f}%" if real_10y is not None else None,
            score=_relative_value_score(real_10y),
            status="ok" if real_10y is not None else "missing",
            source="FRED:DFII10",
        ),
        RatesScorecardFactor(
            label="10Y breakeven inflation",
            value=f"{breakeven_10y:.2f}%" if breakeven_10y is not None else None,
            score=_breakeven_score(breakeven_10y),
            status="ok" if breakeven_10y is not None else "missing",
            source="FRED:T10YIE",
        ),
    ]
    by_id["sentiment"].factors = [
        RatesScorecardFactor(
            label="10Y one-month rate momentum",
            value=(
                f"{ten_year_1m_delta_bps:+.0f}bp"
                if ten_year_1m_delta_bps is not None
                else None
            ),
            score=_momentum_score(ten_year_1m_delta_bps),
            status="ok" if ten_year_1m_delta_bps is not None else "missing",
            source="FRED:DGS10",
        )
    ]

    for group in groups:
        group.score = score_group(group)
        group.status = "ok" if group.score is not None else "missing"

    composite = compute_composite_score(groups)
    return RatesScorecard(
        composite_score=composite,
        duration_stance=_duration_stance(composite),
        curve_score=curve_score,
        curve_stance=_curve_stance(curve_score),
        groups=groups,
    )


def _policy_score(effr: float | None) -> float | None:
    if effr is None:
        return None
    if effr >= 4.5:
        return -1.0
    if effr <= 3.0:
        return 1.0
    return 0.0


def _relative_value_score(real_10y: float | None) -> float | None:
    if real_10y is None:
        return None
    if real_10y >= 2.0:
        return 1.0
    if real_10y <= 1.0:
        return -1.0
    return 0.0


def _breakeven_score(breakeven_10y: float | None) -> float | None:
    if breakeven_10y is None:
        return None
    if breakeven_10y >= 2.5:
        return -1.0
    if breakeven_10y <= 2.0:
        return 1.0
    return 0.0


def _momentum_score(delta_bps_value: float | None) -> float | None:
    if delta_bps_value is None:
        return None
    if delta_bps_value >= 25:
        return -1.0
    if delta_bps_value <= -25:
        return 1.0
    return 0.0


def _duration_stance(score: float | None):
    if score is None:
        return "NEUTRAL"
    if score <= -0.25:
        return "SELL"
    if score >= 0.25:
        return "BUY"
    return "NEUTRAL"


def _curve_stance(score: float | None):
    if score is None:
        return "NEUTRAL"
    if score >= 0.25:
        return "STEEP"
    if score <= -0.25:
        return "FLAT"
    return "NEUTRAL"

