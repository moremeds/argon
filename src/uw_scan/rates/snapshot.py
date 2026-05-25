"""Assemble persisted FRED observations into the US rates mirror payload."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from uw_scan.models import (
    RatesCrossMarketPanel,
    RatesPositioningPanel,
    RatesSnapshotResponse,
    RatesSourceFreshness,
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
from uw_scan.rates.policy import build_policy_panel
from uw_scan.rates.positioning import build_positioning_panel
from uw_scan.rates.scorecard import build_scorecard
from uw_scan.rates.series import YIELD_CURVE_SERIES
from uw_scan.rates.supply import build_supply_panel
from uw_scan.rates.utils import latest_float


def build_rates_snapshot(
    observations: dict[str, list[dict[str, Any]]],
    *,
    computed_at: datetime,
    failed_series: set[str] | None = None,
    policy_events: list[dict[str, Any]] | None = None,
    policy_path: list[dict[str, Any]] | None = None,
    cftc_tff_rows: list[dict[str, Any]] | None = None,
    supply_auctions: list[dict[str, Any]] | None = None,
    supply_debt: dict[str, Any] | None = None,
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
    failed_sources = failed_series or set()
    source_freshness = compute_source_freshness(
        observations, as_of=as_of, stale_series=failed_series
    )
    curve_score = _curve_score(slopes)
    ten_year = next((point for point in curve_points if point.tenor == "10Y"), None)
    scorecard = build_scorecard(
        ten_year_1m_delta_bps=ten_year.delta_1m_bps if ten_year is not None else None,
        curve_score=curve_score,
        effr=latest_float(observations, "EFFR", as_of),
        real_10y=decomposition.real_10y,
        breakeven_10y=decomposition.breakeven_10y,
    )

    policy_panel = build_policy_panel(
        observations,
        as_of=as_of,
        policy_events=policy_events or [],
        policy_path=policy_path or [],
        failed_sources=failed_sources,
    )
    positioning_panel = build_positioning_panel(
        cftc_tff_rows or [], source_failed="CFTC_TFF" in failed_sources
    )
    supply_panel = build_supply_panel(
        observations,
        as_of=as_of,
        auction_rows=supply_auctions or [],
        debt_row=supply_debt,
        source_failed="TREASURY_SUPPLY" in failed_sources,
    )
    source_freshness.extend(
        _optional_source_freshness(
            failed_sources=failed_sources,
            policy_events=policy_events or [],
            policy_path=policy_path or [],
            cftc_tff_rows=cftc_tff_rows or [],
            supply_auctions=supply_auctions or [],
            supply_debt=supply_debt,
        )
    )

    return RatesSnapshotResponse(
        as_of=as_of,
        computed_at=computed_at,
        summary=_summary_tiles(curve_points, slopes),
        curve={"points": curve_points, "slopes": slopes},
        decomposition=decomposition,
        scorecard=scorecard,
        policy=policy_panel,
        supply=supply_panel,
        positioning=positioning_panel,
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
                _risk_text(positioning_panel, supply_panel),
            ],
        ),
        source_freshness=source_freshness,
    )


def _risk_text(positioning: RatesPositioningPanel, supply: RatesSupplyPanel) -> str:
    live = []
    if supply.status == "ok":
        live.append("Treasury auction/FiscalData supply")
    if positioning.status == "ok":
        live.append("CFTC TFF positioning")
    if live:
        return "; ".join(live) + " live; TIC and event feeds remain unavailable."
    return "Non-FRED auction, TIC, CFTC, and event feeds are unavailable until Phase 2."


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
        if latest_float(observations, series_id, as_of) is None
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



def _optional_source_freshness(
    *,
    failed_sources: set[str],
    policy_events: list[dict[str, Any]],
    policy_path: list[dict[str, Any]],
    cftc_tff_rows: list[dict[str, Any]],
    supply_auctions: list[dict[str, Any]],
    supply_debt: dict[str, Any] | None,
) -> list[RatesSourceFreshness]:
    return [
        _source_freshness(
            "FED_FOMC",
            "Fed FOMC calendar",
            _latest_policy_event_date(policy_events),
            failed_sources=failed_sources,
            has_data=bool(policy_events),
        ),
        _source_freshness(
            "FED_FUNDS_FUTURES_PATH",
            "Fed funds futures path",
            None,
            failed_sources=failed_sources,
            has_data=bool(policy_path),
        ),
        _source_freshness(
            "CFTC_TFF",
            "CFTC TFF Treasury positioning",
            _latest_row_date(cftc_tff_rows, "obs_date"),
            failed_sources=failed_sources,
            has_data=bool(cftc_tff_rows),
            last_seen_at=_latest_row_datetime(cftc_tff_rows, "as_of"),
        ),
        _source_freshness(
            "TREASURY_SUPPLY",
            "Treasury auction/FiscalData supply",
            _latest_supply_date(supply_auctions, supply_debt),
            failed_sources=failed_sources,
            has_data=bool(supply_auctions or supply_debt),
        ),
    ]


def _source_freshness(
    source_id: str,
    label: str,
    latest_obs_date: date | None,
    *,
    failed_sources: set[str],
    has_data: bool,
    last_seen_at: datetime | None = None,
) -> RatesSourceFreshness:
    if source_id in failed_sources:
        status = "stale" if has_data else "missing"
    else:
        status = "ok" if has_data else "missing"
    return RatesSourceFreshness(
        id=source_id,
        label=label,
        latest_obs_date=latest_obs_date,
        last_seen_at=last_seen_at,
        status=status,
    )


def _latest_policy_event_date(rows: list[dict[str, Any]]) -> date | None:
    return max(
        (
            row.get("event_end_date") or row.get("event_date")
            for row in rows
            if row.get("event_end_date") or row.get("event_date")
        ),
        default=None,
    )


def _latest_row_date(rows: list[dict[str, Any]], key: str) -> date | None:
    return max((row[key] for row in rows if row.get(key) is not None), default=None)


def _latest_row_datetime(rows: list[dict[str, Any]], key: str) -> datetime | None:
    return max((row[key] for row in rows if row.get(key) is not None), default=None)


def _latest_supply_date(
    auctions: list[dict[str, Any]], debt_row: dict[str, Any] | None
) -> date | None:
    dates = [row["auction_date"] for row in auctions if row.get("auction_date")]
    if debt_row and debt_row.get("record_date"):
        dates.append(debt_row["record_date"])
    return max(dates, default=None)


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
