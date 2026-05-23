"""Assemble persisted FRED observations into the US rates mirror payload."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    RatesCrossMarketPanel,
    RatesPolicyMeeting,
    RatesPolicyPanel,
    RatesPolicyPathPoint,
    RatesPolicyPlumbingMetric,
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
    policy_events: list[dict[str, Any]] | None = None,
    policy_path: list[dict[str, Any]] | None = None,
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

    policy_panel = _policy_panel(
        observations,
        as_of=as_of,
        policy_events=policy_events or [],
        policy_path=policy_path or [],
    )

    return RatesSnapshotResponse(
        as_of=as_of,
        computed_at=computed_at,
        summary=_summary_tiles(curve_points, slopes),
        curve={"points": curve_points, "slopes": slopes},
        decomposition=decomposition,
        scorecard=scorecard,
        policy=policy_panel,
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


def _policy_panel(
    observations: dict[str, list[dict[str, Any]]],
    *,
    as_of: date,
    policy_events: list[dict[str, Any]],
    policy_path: list[dict[str, Any]],
) -> RatesPolicyPanel:
    latest_policy_date = date.max
    target_lower = _latest_float(observations, "DFEDTARL", latest_policy_date)
    target_upper = _latest_float(observations, "DFEDTARU", latest_policy_date)
    target_range = _format_target_range(target_lower, target_upper)
    path = [RatesPolicyPathPoint.model_validate(row) for row in policy_path]
    last_meeting = _latest_policy_meeting(policy_events, as_of=as_of)
    if last_meeting is not None and last_meeting.action is None:
        inferred_action = _infer_policy_action_from_targets(
            observations, last_meeting.event_end_date or last_meeting.event_date
        )
        if inferred_action is not None:
            last_meeting = last_meeting.model_copy(update={"action": inferred_action})
    plumbing = _plumbing_tiles(observations)
    return RatesPolicyPanel(
        target_lower=target_lower,
        target_upper=target_upper,
        target_range=target_range,
        effr=_latest_float(observations, "EFFR", latest_policy_date),
        sofr=_latest_float(observations, "SOFR", latest_policy_date),
        last_meeting=last_meeting,
        implied_path=path,
        plumbing=plumbing,
        policy_read=_policy_read(target_range, last_meeting),
        path_read=_path_read(path),
        plumbing_read=_plumbing_read(plumbing),
        status="ok" if target_range and plumbing else "partial",
    )


def _latest_policy_meeting(
    policy_events: list[dict[str, Any]], *, as_of: date
) -> RatesPolicyMeeting | None:
    meetings = []
    for row in policy_events:
        meeting = RatesPolicyMeeting.model_validate(row)
        meeting_date = meeting.event_end_date or meeting.event_date
        if meeting_date is not None and meeting_date <= as_of:
            meetings.append(meeting)
    if not meetings:
        return None
    return max(
        meetings,
        key=lambda item: item.event_end_date or item.event_date or date.min,
    )


def _format_target_range(lower: float | None, upper: float | None) -> str | None:
    if lower is None or upper is None:
        return None
    return f"{lower:.2f}-{upper:.2f}%"


def _infer_policy_action_from_targets(
    observations: dict[str, list[dict[str, Any]]], meeting_date: date | None
) -> str | None:
    if meeting_date is None:
        return None
    lower_current = _latest_decimal_on_or_before(observations, "DFEDTARL", meeting_date)
    upper_current = _latest_decimal_on_or_before(observations, "DFEDTARU", meeting_date)
    lower_prior = _latest_decimal_before(observations, "DFEDTARL", meeting_date)
    upper_prior = _latest_decimal_before(observations, "DFEDTARU", meeting_date)
    if None in (lower_current, upper_current, lower_prior, upper_prior):
        return None
    current_mid = (lower_current + upper_current) / Decimal(2)
    prior_mid = (lower_prior + upper_prior) / Decimal(2)
    if current_mid > prior_mid:
        return "Hike"
    if current_mid < prior_mid:
        return "Cut"
    return "Hold"


def _latest_decimal_on_or_before(
    observations: dict[str, list[dict[str, Any]]], series_id: str, as_of: date
) -> Decimal | None:
    rows = [row for row in observations.get(series_id, []) if row["obs_date"] <= as_of]
    if not rows:
        return None
    value = max(rows, key=lambda row: row["obs_date"])["value"]
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _latest_decimal_before(
    observations: dict[str, list[dict[str, Any]]], series_id: str, as_of: date
) -> Decimal | None:
    rows = [row for row in observations.get(series_id, []) if row["obs_date"] < as_of]
    if not rows:
        return None
    value = max(rows, key=lambda row: row["obs_date"])["value"]
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _policy_read(
    target_range: str | None, last_meeting: RatesPolicyMeeting | None
) -> str | None:
    if target_range is None:
        return "Policy target range is unavailable until DFEDTARL/DFEDTARU are persisted."
    if last_meeting is None:
        return f"Fed target range is {target_range}; official meeting metadata is not yet persisted."
    action = last_meeting.action or "unclassified"
    vote = f" with vote split {last_meeting.vote_split}" if last_meeting.vote_split else ""
    return f"{last_meeting.label} was classified as {action}{vote}; current target range is {target_range}."


def _path_read(path: list[RatesPolicyPathPoint]) -> str:
    if not path:
        return "Fed funds futures-implied path is unavailable until a path source is persisted."
    first = path[0]
    source = first.source or "fed funds futures"
    return (
        f"{source} assigns {first.probability:.1f}% to "
        f"{first.stance.lower()} at the next meeting."
    )


def _plumbing_read(plumbing: list[RatesPolicyPlumbingMetric]) -> str:
    by_label = {item.label: item for item in plumbing}
    parts = []
    if assets := by_label.get("Fed assets"):
        parts.append(assets.qualifier or "QT watch")
    if reserves := by_label.get("Reserves"):
        parts.append(reserves.qualifier or "reserve status unavailable")
    if rrp := by_label.get("ON RRP"):
        parts.append(rrp.qualifier or "ON RRP status unavailable")
    if tga := by_label.get("TGA"):
        parts.append(tga.qualifier or "TGA status unavailable")
    return "; ".join(parts) if parts else "Fed plumbing series are not yet persisted."


def _plumbing_tiles(
    observations: dict[str, list[dict[str, Any]]],
) -> list[RatesPolicyPlumbingMetric]:
    latest_policy_date = date.max
    fed_assets = _latest_float(
        observations, "WALCL", latest_policy_date, divisor=1_000_000
    )
    reserves = _latest_float(
        observations, "WRESBAL", latest_policy_date, divisor=1_000_000
    )
    on_rrp = _latest_float(
        observations, "RRPONTSYD", latest_policy_date, divisor=1000, quantum="0.001"
    )
    tga = _latest_float(
        observations, "WTREGEN", latest_policy_date, divisor=1_000_000
    )
    return [
        RatesPolicyPlumbingMetric(
            label="Fed assets",
            value=fed_assets,
            unit="$T",
            qualifier=_walcl_qualifier(observations, latest_policy_date),
            status="ok" if fed_assets is not None else "missing",
        ),
        RatesPolicyPlumbingMetric(
            label="Reserves",
            value=reserves,
            unit="$T",
            qualifier=_reserve_qualifier(reserves),
            status="ok" if reserves is not None else "missing",
        ),
        RatesPolicyPlumbingMetric(
            label="ON RRP",
            value=on_rrp,
            unit="$T",
            qualifier=_rrp_qualifier(on_rrp),
            status="ok" if on_rrp is not None else "missing",
        ),
        RatesPolicyPlumbingMetric(
            label="TGA",
            value=tga,
            unit="$T",
            qualifier=_tga_qualifier(tga),
            status="ok" if tga is not None else "missing",
        ),
    ]


def _walcl_qualifier(
    observations: dict[str, list[dict[str, Any]]], as_of: date
) -> str | None:
    delta = _window_delta(observations, "WALCL", as_of, divisor=1000)
    if delta is None:
        return "QT watch"
    if delta < -20:
        return "QT draining"
    if delta > 20:
        return "Balance sheet expanding"
    return "QT flat/ended"


def _reserve_qualifier(value: float | None) -> str | None:
    if value is None:
        return None
    return "ample reserves" if value >= 3.0 else "reserve buffer lower"


def _rrp_qualifier(value: float | None) -> str | None:
    if value is None:
        return None
    return "near-zero ON RRP" if value <= 0.05 else "ON RRP still absorbs liquidity"


def _tga_qualifier(value: float | None) -> str | None:
    if value is None:
        return None
    return "high TGA liquidity drag" if value >= 0.7 else "TGA liquidity drag moderate"


def _window_delta(
    observations: dict[str, list[dict[str, Any]]],
    series_id: str,
    as_of: date,
    *,
    divisor: Decimal | int = 1,
) -> float | None:
    rows = sorted(
        [row for row in observations.get(series_id, []) if row["obs_date"] <= as_of],
        key=lambda row: row["obs_date"],
    )
    if len(rows) < 2:
        return None
    current = rows[-1]["value"]
    prior = rows[0]["value"]
    current_dec = current if isinstance(current, Decimal) else Decimal(str(current))
    prior_dec = prior if isinstance(prior, Decimal) else Decimal(str(prior))
    return float(((current_dec - prior_dec) / Decimal(str(divisor))).quantize(Decimal("0.1")))


def _latest_float(
    observations: dict[str, list[dict[str, Any]]],
    series_id: str,
    as_of: date,
    *,
    divisor: Decimal | int = 1,
    quantum: str = "0.01",
) -> float | None:
    rows = [row for row in observations.get(series_id, []) if row["obs_date"] <= as_of]
    if not rows:
        return None
    value = max(rows, key=lambda row: row["obs_date"])["value"]
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    decimal_value = decimal_value / Decimal(str(divisor))
    return float(decimal_value.quantize(Decimal(quantum)))


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
