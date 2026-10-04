"""Daily and live technicals settings (D6 concern group: technicals)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class TechnicalsSettings(BaseModel):
    # Nightly technicals refresh (apex daily bars -> technical_daily, massive-0 18:40 ET).
    technicals_refresh_enabled: Annotated[
        bool, EnvVar("UW_SCAN_TECHNICALS_REFRESH_ENABLED")
    ] = True
    # Live technicals coverage (WS-spot splice -> technical_live cache, massive-0).
    technical_live_enabled: Annotated[
        bool, EnvVar("UW_SCAN_TECHNICAL_LIVE_ENABLED")
    ] = False
    technical_live_scan_interval_minutes: Annotated[
        int, EnvVar("TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES")
    ] = 5
    technical_live_quote_max_age_seconds: Annotated[
        int, EnvVar("TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS")
    ] = 900
