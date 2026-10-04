"""VRP iron-condor backtest and macro entry-capture (D6 concern group: vrp)."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, model_validator

from uw_scan.config._env import EnvVar


class VrpSettings(BaseModel):
    # --- VRP tradable iron-condor + backtest (plan 2026-06-22) ----------------
    # hold is in TRADING days to stay unit-consistent with the harvest measurement
    # (HORIZON=20). t_years = hold_days / 252 feeds Black-Scholes.
    vrp_hold_days: Annotated[int, EnvVar("UW_SCAN_VRP_HOLD_DAYS")] = 20
    vrp_short_delta: Annotated[float, EnvVar("UW_SCAN_VRP_SHORT_DELTA")] = (
        0.16  # short put/call strike target |delta|
    )
    vrp_wing_delta: Annotated[float, EnvVar("UW_SCAN_VRP_WING_DELTA")] = (
        0.08  # long wing strike target |delta|
    )
    vrp_risk_free_rate: Annotated[float, EnvVar("UW_SCAN_VRP_RISK_FREE_RATE")] = (
        0.04  # flat r for BS; tiny effect at short DTE
    )
    vrp_cost_per_contract: Annotated[float, EnvVar("UW_SCAN_VRP_COST_PER_CONTRACT")] = (
        0.65  # commission per leg per side
    )
    vrp_slippage_frac: Annotated[float, EnvVar("UW_SCAN_VRP_SLIPPAGE_FRAC")] = (
        0.01  # half-spread as fraction of leg mid
    )
    vrp_slippage_min: Annotated[float, EnvVar("UW_SCAN_VRP_SLIPPAGE_MIN")] = (
        0.05  # half-spread floor per leg (price points)
    )
    vrp_cost_round_trip: Annotated[bool, EnvVar("UW_SCAN_VRP_COST_ROUND_TRIP")] = (
        True  # charge open + close (conservative)
    )
    # --- VRP macro forward entry-capture (plan 2026-06-24) --------------------
    vrp_macro_entry_capture_enabled: Annotated[
        bool, EnvVar("UW_SCAN_VRP_MACRO_ENTRY_CAPTURE_ENABLED")
    ] = True
    vrp_macro_entry_taper_calendar_days: Annotated[
        int, EnvVar("UW_SCAN_VRP_MACRO_ENTRY_TAPER_CALENDAR_DAYS")
    ] = 30  # > this → EOD-only marks
    vrp_macro_entry_quote_timeout_s: Annotated[
        float, EnvVar("UW_SCAN_VRP_MACRO_ENTRY_QUOTE_TIMEOUT_S")
    ] = 8.0  # per-leg xenon/IB snapshot timeout
    vrp_macro_entry_mark_budget_s: Annotated[
        float, EnvVar("UW_SCAN_VRP_MACRO_ENTRY_MARK_BUDGET_S")
    ] = 600.0  # per-mark wall-clock; overrun → UW-only

    @model_validator(mode="after")
    def _check_vrp(self) -> Self:
        if not (0.0 < self.vrp_wing_delta < self.vrp_short_delta < 0.5):
            raise ValueError("require 0 < vrp_wing_delta < vrp_short_delta < 0.5")
        if self.vrp_hold_days <= 0:
            raise ValueError("vrp_hold_days must be positive")
        return self
