from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationConfig:
    min_abs_oi_change: int = 100
    min_oi_change_pct_of_flow_volume: float = 0.25
    unknown_on_conflict: bool = True


def reconcile_oi_change(
    *,
    flow_volume: int,
    previous_oi: int | None,
    current_oi: int | None,
    side_consistent: bool,
    config: ReconciliationConfig,
) -> str:
    if previous_oi is None or current_oi is None or flow_volume <= 0:
        return "unknown"
    if config.unknown_on_conflict and not side_consistent:
        return "unknown"
    oi_change = current_oi - previous_oi
    threshold = max(config.min_abs_oi_change, int(flow_volume * config.min_oi_change_pct_of_flow_volume))
    if oi_change >= threshold:
        return "likely_opening"
    if oi_change <= -threshold:
        return "likely_closing"
    return "fading"
