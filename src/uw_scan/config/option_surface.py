"""Option surface capture, IV canary and research cohort (D6 concern group: option_surface)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class OptionSurfaceSettings(BaseModel):
    # Option surface capture (durable full-chain IV/greeks grid) + IB-vs-UW IV canary
    option_surface_capture_enabled: Annotated[
        bool, EnvVar("OPTION_SURFACE_CAPTURE_ENABLED")
    ] = True
    option_surface_backfill_days: Annotated[
        int, EnvVar("OPTION_SURFACE_BACKFILL_DAYS")
    ] = 4
    option_surface_iv_canary_enabled: Annotated[
        bool, EnvVar("OPTION_SURFACE_IV_CANARY_ENABLED")
    ] = True
    option_surface_iv_canary_warn_threshold: Annotated[
        float, EnvVar("OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD")
    ] = 0.02
    # Nightly full-chain capture for a research cohort (uw_scan.research_universe).
    # Default-on is safe: the job self-gates on the cohort being seeded, so an
    # un-seeded deployment spends nothing.
    option_surface_research_capture_enabled: Annotated[
        bool, EnvVar("OPTION_SURFACE_RESEARCH_CAPTURE_ENABLED")
    ] = True
    option_surface_research_cohort: Annotated[
        str, EnvVar("OPTION_SURFACE_RESEARCH_COHORT")
    ] = "liquid_sector_balanced_v1"
    # Nightly catch-up that fills the cohort's *history* (the capture above only
    # writes tonight). Self-terminating: once the ~180-day window is complete it
    # finds no gaps and spends nothing, so it needs no switching off. The cap is
    # per night — ~7,950 calls of work at 1,500/night finishes in ~6 nights while
    # staying well inside the 30k research pool.
    option_surface_research_catchup_enabled: Annotated[
        bool, EnvVar("OPTION_SURFACE_RESEARCH_CATCHUP_ENABLED")
    ] = True
    option_surface_research_catchup_max_calls: Annotated[
        int, EnvVar("OPTION_SURFACE_RESEARCH_CATCHUP_MAX_CALLS")
    ] = 1500
