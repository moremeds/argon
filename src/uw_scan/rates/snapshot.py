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

    policy_panel = _policy_panel(
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


def _policy_panel(
    observations: dict[str, list[dict[str, Any]]],
    *,
    as_of: date,
    policy_events: list[dict[str, Any]],
    policy_path: list[dict[str, Any]],
    failed_sources: set[str],
) -> RatesPolicyPanel:
    target_lower = latest_float(observations, "DFEDTARL", as_of)
    target_upper = latest_float(observations, "DFEDTARU", as_of)
    target_range = _format_target_range(target_lower, target_upper)
    path_status = "stale" if "FED_FUNDS_FUTURES_PATH" in failed_sources else None
    path = [
        RatesPolicyPathPoint.model_validate(row).model_copy(
            update={"status": path_status}
        )
        if path_status is not None
        else RatesPolicyPathPoint.model_validate(row)
        for row in policy_path
    ]
    last_meeting = _latest_policy_meeting(policy_events, as_of=as_of)
    if last_meeting is not None and last_meeting.action is None:
        inferred_action = _infer_policy_action_from_targets(
            observations, last_meeting.event_end_date or last_meeting.event_date
        )
        if inferred_action is not None:
            last_meeting = last_meeting.model_copy(update={"action": inferred_action})
    plumbing = _plumbing_tiles(observations, as_of=as_of)
    return RatesPolicyPanel(
        target_lower=target_lower,
        target_upper=target_upper,
        target_range=target_range,
        effr=latest_float(observations, "EFFR", as_of),
        sofr=latest_float(observations, "SOFR", as_of),
        last_meeting=last_meeting,
        implied_path=path,
        plumbing=plumbing,
        policy_read=_policy_read(target_range, last_meeting),
        path_read=_path_read(path),
        plumbing_read=_plumbing_read(plumbing),
        status=_policy_status(target_range, plumbing, failed_sources=failed_sources),
    )


def _policy_status(
    target_range: str | None,
    plumbing: list[RatesPolicyPlumbingMetric],
    *,
    failed_sources: set[str],
) -> str:
    if failed_sources & {"FED_FOMC", "FED_FUNDS_FUTURES_PATH"}:
        return "stale"
    if target_range is None:
        return "partial"
    return "ok" if _has_live_plumbing_tile(plumbing) else "partial"


def _has_live_plumbing_tile(plumbing: list[RatesPolicyPlumbingMetric]) -> bool:
    return any(tile.status == "ok" and tile.value is not None for tile in plumbing)


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
    *,
    as_of: date,
) -> list[RatesPolicyPlumbingMetric]:
    fed_assets = latest_float(observations, "WALCL", as_of, divisor=1_000_000)
    reserves = latest_float(observations, "WRESBAL", as_of, divisor=1_000_000)
    on_rrp = latest_float(
        observations, "RRPONTSYD", as_of, divisor=1000, quantum="0.001"
    )
    tga = latest_float(observations, "WTREGEN", as_of, divisor=1_000_000)
    return [
        RatesPolicyPlumbingMetric(
            label="Fed assets",
            value=fed_assets,
            unit="$T",
            qualifier=_walcl_qualifier(observations, as_of),
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
