"""Build the rates policy panel."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    RatesPolicyMeeting,
    RatesPolicyPanel,
    RatesPolicyPathPoint,
    RatesPolicyPlumbingMetric,
)
from uw_scan.rates.utils import latest_float


def build_policy_panel(
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
    return float(
        ((current_dec - prior_dec) / Decimal(str(divisor))).quantize(Decimal("0.1"))
    )
