"""Pydantic-managed environment settings for the UW scanner."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import SecretStr

from uw_scan.config._env import (
    _load_dotenv,
    env_raw,
    read_env_fields,
)
from uw_scan.config.apex import ApexSettings
from uw_scan.config.cockpit import CockpitSettings
from uw_scan.config.data_gap import DataGapSettings
from uw_scan.config.db import DbSettings
from uw_scan.config.db_isolation import _enforce_db_isolation
from uw_scan.config.fundamentals import FundamentalsSettings
from uw_scan.config.health import HealthSettings
from uw_scan.config.lake import LAKE_ROOT_FALLBACK, LakeSettings
from uw_scan.config.macro import MacroSettings
from uw_scan.config.massive import MassiveSettings
from uw_scan.config.option_surface import OptionSurfaceSettings
from uw_scan.config.regime import RegimeSettings
from uw_scan.config.research import ResearchSettings
from uw_scan.config.scanner import ScannerSettings
from uw_scan.config.technicals import TechnicalsSettings
from uw_scan.config.trade_insights_ai import TradeInsightsAiSettings
from uw_scan.config.uw_api import UwApiSettings
from uw_scan.config.uw_budget import UwBudgetSettings
from uw_scan.config.uw_capture import UwCaptureSettings
from uw_scan.config.vrp import VrpSettings
from uw_scan.config.worker import WorkerSettings
from uw_scan.config.xenon import XenonSettings


class Settings(
    UwApiSettings,
    DbSettings,
    WorkerSettings,
    HealthSettings,
    MassiveSettings,
    XenonSettings,
    ApexSettings,
    RegimeSettings,
    LakeSettings,
    MacroSettings,
    TradeInsightsAiSettings,
    CockpitSettings,
    FundamentalsSettings,
    OptionSurfaceSettings,
    TechnicalsSettings,
    ResearchSettings,
    # VrpSettings before ScannerSettings: pydantic runs base after-validators in
    # reverse MRO, so the edge-quality check still fires before _check_vrp.
    VrpSettings,
    ScannerSettings,
    UwCaptureSettings,
    UwBudgetSettings,
    DataGapSettings,
):
    """Strongly-typed configuration. Raises on missing required fields."""

    @property
    def ws_spot_enabled(self) -> bool:
        """True when ANY WS feed owns intraday spot.

        Use this (not ``massive_ws_enabled``) wherever the question is "does
        the WS pipeline own spot writes" — e.g. the scheduler's
        ``preserve_spot`` guard. A xenon-only deployment must still stop UW
        scan jobs from overwriting WS-written spot.
        """
        return self.massive_ws_enabled or self.xenon_ws_enabled

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Settings":
        """Load Settings from process env, auto-loading .env at repo root.

        When called without an explicit env_path, loads .env.local first, then
        .env, both from repo root. .env.local is a gitignored per-machine
        override — used to point the MacBook at the mini's DB host without
        editing the committed .env. Because _load_dotenv only sets keys not
        already present in os.environ, .env.local wins on conflicts.
        """
        if env_path is not None:
            _load_dotenv(env_path)
        else:
            repo_root = Path(__file__).resolve().parents[3]
            _load_dotenv(repo_root / ".env.local")
            _load_dotenv(repo_root / ".env")

        api_key = os.environ.get("UW_SCAN_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "UW_SCAN_API_KEY is not set. Add it to .env or export it before running."
            )

        # Before any field is parsed, as before the env table: a wrong-tier pair is
        # refused even when another value would also fail to parse.
        _enforce_db_isolation(env_raw(cls, "db_host"), env_raw(cls, "db_name"))

        env = read_env_fields(cls)
        # Lake roots without their own env var fall back under the warehouse root
        # (LAKE_ROOT_FALLBACK), resolved here at call time as before the env table.
        mw_lake_root = env.setdefault(
            "market_warehouse_lake_root", Path.home() / "market-warehouse" / "data-lake"
        )
        for field, sub in LAKE_ROOT_FALLBACK.items():
            env.setdefault(field, mw_lake_root / sub)

        return cls(api_key=SecretStr(api_key), **env)
