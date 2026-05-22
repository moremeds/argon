"""Assemble persisted FRED observations into the US rates mirror payload."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    RatesCrossMarketPanel,
    RatesPolicyPanel,
    RatesPositioningPanel,
    RatesSnapshotResponse,
    RatesSummaryTile,
    RatesSupplyPanel,
    RatesSynthesisPanel,
)
from uw_scan.rates.calculations import (
    compute_curve,
    compute_decomposition,
    compute_slopes,
    compute_source_freshness,
)
from uw_scan.rates.scorecard import build_scorecard
from uw_scan.rates.series import YIELD_CURVE_SERIES


def build_rates_snapshot(
    observations: dict[str, list[dict[str, Any]]],
    *,
    computed_at: datetime,
    failed_series: set[str] | None = None,
) -> RatesSnapshotResponse:
    as_of = _latest_curve_observation_date(observations)
    if as_of is None:
        raise ValueError("Treasury curve observations are required to build a snapshot")
    missing_curve = _missing_curve_series(observations, as_of=as_of)
    if missing_curve:
        raise ValueError(
            "Treasury curve snapshot is incomplete; missing series: "
            + ", ".join(missing_curve)
        )

    curve_points = compute_curve(observations, as_of=as_of)
    slopes = compute_slopes(curve_points)
    decomposition = compute_decomposition(observations, as_of=as_of)
    source_freshness = compute_source_freshness(
        observations, as_of=as_of, stale_series=failed_series
    )
    curve_score = _curve_score(slopes)
    ten_year = next((point for point in curve_points if point.tenor == "10Y"), None)
    scorecard = build_scorecard(
        ten_year_1m_delta_bps=ten_year.delta_1m_bps if ten_year is not None else None,
        curve_score=curve_score,
        effr=_latest_float(observations, "EFFR", as_of),
        real_10y=decomposition.real_10y,
        breakeven_10y=decomposition.breakeven_10y,
    )

    return RatesSnapshotResponse(
        as_of=as_of,
        computed_at=computed_at,
        summary=_summary_tiles(curve_points, slopes),
        curve={"points": curve_points, "slopes": slopes},
        decomposition=decomposition,
        scorecard=scorecard,
        policy=RatesPolicyPanel(
            effr=_latest_float(observations, "EFFR", as_of),
            sofr=_latest_float(observations, "SOFR", as_of),
            plumbing=_plumbing_tiles(observations, as_of),
            status="partial",
        ),
        supply=RatesSupplyPanel(
            notes=["Treasury auction/QRA feed not wired in Phase 1"],
            status="missing",
        ),
        positioning=RatesPositioningPanel(status="missing"),
        cross_market=RatesCrossMarketPanel(
            rows=[
                RatesSummaryTile(
                    label="10Y real",
                    value=decomposition.real_10y,
                    unit="%",
                    status="ok" if decomposition.real_10y is not None else "missing",
                ),
                RatesSummaryTile(
                    label="10Y BEI",
                    value=decomposition.breakeven_10y,
                    unit="%",
                    status=(
                        "ok" if decomposition.breakeven_10y is not None else "missing"
                    ),
                ),
            ],
            status="partial",
        ),
        events=[],
        synthesis=RatesSynthesisPanel(
            duration_view=_duration_text(scorecard.composite_score),
            curve_view=_curve_text(curve_score),
            risks=[
                "Non-FRED auction, TIC, CFTC, and event feeds are unavailable until Phase 2."
            ],
        ),
        source_freshness=source_freshness,
    )


def _latest_curve_observation_date(
    observations: dict[str, list[dict[str, Any]]],
) -> date | None:
    dates = [
        row["obs_date"]
        for series_id in YIELD_CURVE_SERIES.values()
        for row in observations.get(series_id, [])
        if row.get("obs_date") is not None
    ]
    if dates:
        return max(dates)
    return None


def _missing_curve_series(
    observations: dict[str, list[dict[str, Any]]],
    *,
    as_of: date,
) -> list[str]:
    return [
        series_id
        for series_id in YIELD_CURVE_SERIES.values()
        if _latest_float(observations, series_id, as_of) is None
    ]


def _summary_tiles(curve_points, slopes) -> list[RatesSummaryTile]:
    tiles: list[RatesSummaryTile] = []
    for tenor in ("2Y", "5Y", "10Y", "30Y"):
        point = next((item for item in curve_points if item.tenor == tenor), None)
        tiles.append(
            RatesSummaryTile(
                label=tenor,
                value=point.value if point is not None else None,
                unit="%",
                delta_1d=point.delta_1d_bps if point is not None else None,
                status=point.status if point is not None else "missing",
            )
        )
    for label in ("2s10s", "5s30s"):
        slope = next((item for item in slopes if item.label == label), None)
        tiles.append(
            RatesSummaryTile(
                label=label,
                value=slope.value_bps if slope is not None else None,
                unit="bps",
                status=slope.status if slope is not None else "missing",
            )
        )
    return tiles


def _plumbing_tiles(
    observations: dict[str, list[dict[str, Any]]], as_of: date
) -> list[RatesSummaryTile]:
    fed_assets = _latest_float(observations, "WALCL", as_of, divisor=1000)
    reserves = _latest_float(observations, "WRESBAL", as_of, divisor=1000)
    on_rrp = _latest_float(observations, "RRPONTSYD", as_of)
    tga = _latest_float(observations, "WTREGEN", as_of, divisor=1000)
    return [
        RatesSummaryTile(
            label="Fed assets",
            value=fed_assets,
            unit="$bn",
            status="ok" if fed_assets is not None else "missing",
        ),
        RatesSummaryTile(
            label="Reserves",
            value=reserves,
            unit="$bn",
            status="ok" if reserves is not None else "missing",
        ),
        RatesSummaryTile(
            label="ON RRP",
            value=on_rrp,
            unit="$bn",
            status="ok" if on_rrp is not None else "missing",
        ),
        RatesSummaryTile(
            label="TGA",
            value=tga,
            unit="$bn",
            status="ok" if tga is not None else "missing",
        ),
    ]


def _latest_float(
    observations: dict[str, list[dict[str, Any]]],
    series_id: str,
    as_of: date,
    *,
    divisor: Decimal | int = 1,
) -> float | None:
    rows = [row for row in observations.get(series_id, []) if row["obs_date"] <= as_of]
    if not rows:
        return None
    value = max(rows, key=lambda row: row["obs_date"])["value"]
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    decimal_value = decimal_value / Decimal(str(divisor))
    return float(decimal_value.quantize(Decimal("0.01")))


def _curve_score(slopes) -> float | None:
    spread = next((slope.value_bps for slope in slopes if slope.label == "2s10s"), None)
    if spread is None:
        return None
    if spread >= 25:
        return 1.0
    if spread <= -25:
        return -1.0
    return 0.0


def _duration_text(score: float | None) -> str:
    if score is None:
        return "Duration stance unavailable until enough FRED inputs are persisted."
    if score <= -0.25:
        return "Live FRED inputs lean bearish duration."
    if score >= 0.25:
        return "Live FRED inputs lean constructive duration."
    return "Live FRED inputs are neutral for duration."


def _curve_text(score: float | None) -> str:
    if score is None:
        return "Curve stance unavailable until enough FRED curve points are persisted."
    if score >= 0.25:
        return "Live curve inputs favor a steeper curve."
    if score <= -0.25:
        return "Live curve inputs favor a flatter curve."
    return "Live curve inputs are neutral."
