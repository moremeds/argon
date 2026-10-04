"""FRED, MC1-MC3 macro ingest flags, and WGC gold inputs (D6 concern group: macro)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr

from uw_scan.config._env import EnvVar


class MacroSettings(BaseModel):
    # FRED official API. Required by the US rates mirror ingest path.
    fred_api_key: Annotated[
        SecretStr | None, EnvVar("FRED_API_KEY", strip=True, blank_is_default=True)
    ] = None
    # Free/delayed fed funds futures path source used by the rates dashboard.
    rates_policy_path_url: Annotated[
        str, EnvVar("RATES_POLICY_PATH_URL", strip=True, blank_is_default=True)
    ] = "https://www.frenzycap.com/fedwatch"
    # MC1 official macro evidence polling.  Off until the source probe and
    # release migration are explicitly enabled in an environment.
    macro_fomc_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_FOMC_INGEST_ENABLED")
    ] = False
    macro_sep_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_SEP_INGEST_ENABLED")
    ] = False
    macro_sme_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_SME_INGEST_ENABLED")
    ] = False
    macro_market_shadow_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_MARKET_SHADOW_INGEST_ENABLED")
    ] = False
    # MC2 vintage-bearing series evidence + the domain-state engines that read it.
    # Off until an environment has a FRED key and has run the series backfill: a state
    # job with no evidence abstains, which is correct but not worth scheduling.
    macro_series_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_SERIES_INGEST_ENABLED")
    ] = False
    # MC3 rates market layer (supply + positioning) as evidence.  Off until an
    # environment has run the deep backfill: the engine's supply rule needs five new
    # issues per term before it can call a multi-quarter high, so a first scheduled run
    # on an empty store produces sub-states that correctly say UNKNOWN and nothing else.
    macro_market_layer_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_MARKET_LAYER_INGEST_ENABLED")
    ] = False
    # MC3 gold evidence: GLD_CLOSE and GLD_HOLDINGS_OZ promoted from the warm store into
    # macro_observations.  Off by default like its siblings, and load-bearing rather than
    # cosmetic: the gold state's REQUIRED anchor is GLD_CLOSE, so with this off the gold
    # state job abstains every night -- correctly, but silently.
    macro_gold_ingest_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_GOLD_INGEST_ENABLED")
    ] = False
    macro_state_compute_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_STATE_COMPUTE_ENABLED")
    ] = False
    # Dual-read: attach the policy/rates domain state to the legacy rates snapshot.
    # Separate from the compute flag so the state can accrue a history before the
    # surface that reads it changes shape.
    rates_snapshot_state_block_enabled: Annotated[
        bool, EnvVar("UW_SCAN_RATES_SNAPSHOT_STATE_BLOCK_ENABLED")
    ] = False
    # WGC Goldhub authenticated downloads. Keep secrets in environment only.
    wgc_goldhub_cookie: Annotated[
        SecretStr | None,
        EnvVar("WGC_GOLDHUB_COOKIE", strip=True, blank_is_default=True),
    ] = None
    wgc_etf_flows_workbook_path: Annotated[
        str, EnvVar("WGC_ETF_FLOWS_WORKBOOK_PATH", strip=True)
    ] = ""
    wgc_cb_reserves_workbook_path: Annotated[
        str, EnvVar("WGC_CB_RESERVES_WORKBOOK_PATH", strip=True)
    ] = ""
    # Economic-release calendar capture + FRED actual fill (daily, uw-0,
    # 1 UW call/day). See reports/macro_releases.py.
    macro_release_calendar_enabled: Annotated[
        bool, EnvVar("UW_SCAN_MACRO_RELEASE_CALENDAR_ENABLED")
    ] = False
