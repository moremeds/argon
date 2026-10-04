"""Health endpoint and ops alerting thresholds (D6 concern group: health)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class HealthSettings(BaseModel):
    # Grace period for the health "expected full scans missed" liveness alarm.
    # Decoupled from card freshness on purpose: the budget governor may
    # deliberately throttle/skip full_scan under UW-budget pressure, which ages
    # last_scan without meaning the scheduler is dead. Keep this loose (~1h) so
    # the alarm signals a genuinely stuck worker, not a governed skip.
    health_full_scan_missed_grace_hours: Annotated[
        float, EnvVar("UW_SCAN_HEALTH_FULL_SCAN_MISSED_GRACE_HOURS")
    ] = 1.0
    # Sliding-window for the per-table coverage check on tables that only
    # update once per day (cockpit + nightly vol rollup). Anything below
    # 24h would always alert on those tables; 26h gives a small grace gap.
    record_health_daily_window_hours: int = 26
    # Sliding window the record_health_snapshot job counts over for every other
    # record-health table. Matches web HealthPanel RECORD_WINDOW_HOURS (8); the
    # API's record_window_hours now only gates "were scans expected", the counts
    # come from the snapshot computed with this window.
    record_health_window_hours: Annotated[
        float, EnvVar("RECORD_HEALTH_WINDOW_HOURS")
    ] = 8.0
    # Ops alert sink — one webhook (Discord/Pushover-compatible JSON POST).
    # Empty = no-op (send_alert returns False without a call).
    ops_alert_webhook_url: Annotated[str, EnvVar("UW_SCAN_OPS_ALERT_WEBHOOK_URL")] = ""
