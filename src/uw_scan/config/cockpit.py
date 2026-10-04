"""Index dealer cockpit snapshot settings (D6 concern group: cockpit)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar, _split_int, _split_upper


class CockpitSettings(BaseModel):
    # Cockpit (6-dim matrix) — see docs/research/six-dimension-matrix/
    cockpit_tickers: Annotated[
        list[str],
        EnvVar(
            "COCKPIT_TICKERS", strip=True, blank_is_default=True, parse=_split_upper
        ),
    ] = ["SPX", "SPY", "QQQ", "IWM"]
    cockpit_snapshot_cron: Annotated[str, EnvVar("COCKPIT_SNAPSHOT_CRON")] = (
        "30 16 * * 0-4"
    )
    cockpit_target_dtes: Annotated[
        list[int],
        EnvVar(
            "COCKPIT_TARGET_DTES", strip=True, blank_is_default=True, parse=_split_int
        ),
    ] = [0, 14, 30, 90]
    cockpit_oi_band_pct: Annotated[Decimal, EnvVar("COCKPIT_OI_BAND_PCT")] = Decimal(
        "0.10"
    )
    cockpit_oi_max_dte: Annotated[int, EnvVar("COCKPIT_OI_MAX_DTE")] = 7
