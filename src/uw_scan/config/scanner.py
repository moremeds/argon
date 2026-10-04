"""Flow scanner detectors, discovery and edge-quality weights (D6 concern group: scanner)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, model_validator

from uw_scan.config._env import EnvVar, _true_1_yes


class ScannerSettings(BaseModel):
    # Scanner (spec §10). Keep a wider weekend/overnight window so the page
    # does not go blank when no fresh scans have run in the last market session.
    scanner_freshness_hours: Annotated[int, EnvVar("SCANNER_FRESHNESS_HOURS")] = 72
    scanner_dp_lookback_days: Annotated[int, EnvVar("SCANNER_DP_LOOKBACK_DAYS")] = 5
    scanner_dcf_min_premium_usd: Annotated[
        Decimal, EnvVar("SCANNER_DCF_MIN_PREMIUM_USD")
    ] = Decimal("500000")
    scanner_dcf_min_ask_side: Annotated[Decimal, EnvVar("SCANNER_DCF_MIN_ASK_SIDE")] = (
        Decimal("0.80")
    )
    scanner_dcf_max_moneyness: Annotated[
        Decimal, EnvVar("SCANNER_DCF_MAX_MONEYNESS")
    ] = Decimal("0.12")
    scanner_dcf_min_dte: Annotated[int, EnvVar("SCANNER_DCF_MIN_DTE")] = 6
    # Discovery uses a looser bar than the watchlist DCF — it answers "worth a
    # look?" rather than "high-conviction trade." Moneyness/DTE/earnings stay
    # the same (those are about valid options, not conviction).
    scanner_discover_min_premium_usd: Annotated[
        Decimal, EnvVar("SCANNER_DISCOVER_MIN_PREMIUM_USD")
    ] = Decimal("100000")
    scanner_discover_min_ask_side: Annotated[
        Decimal, EnvVar("SCANNER_DISCOVER_MIN_ASK_SIDE")
    ] = Decimal("0.65")
    # /api/scanner/discover serves a cached re-derivation when a successful
    # _DISCOVER run finished within this many seconds, so concurrent page loads
    # / auto-refresh don't burst the UW rate budget. Set to 0 to disable.
    scanner_discover_freshness_seconds: Annotated[
        int, EnvVar("SCANNER_DISCOVER_FRESHNESS_SECONDS")
    ] = 30
    scanner_dp_min_print_premium_usd: Annotated[
        Decimal, EnvVar("SCANNER_DP_MIN_PRINT_PREMIUM_USD")
    ] = Decimal("1000000")
    scanner_dp_min_cluster_size: Annotated[
        int, EnvVar("SCANNER_DP_MIN_CLUSTER_SIZE")
    ] = 3
    scanner_dp_price_spread_pct: Annotated[
        Decimal, EnvVar("SCANNER_DP_PRICE_SPREAD_PCT")
    ] = Decimal("0.5")
    scanner_eic_min_iv_rank: Annotated[Decimal, EnvVar("SCANNER_EIC_MIN_IV_RANK")] = (
        Decimal("75.0")
    )
    scanner_gex_pin_min_gamma: Annotated[
        Decimal, EnvVar("SCANNER_GEX_PIN_MIN_GAMMA")
    ] = Decimal("1.0")
    scanner_liquidity_min_option_volume: Annotated[
        int, EnvVar("SCANNER_LIQUIDITY_MIN_OPTION_VOLUME")
    ] = 1000
    scanner_earnings_window_days: Annotated[
        int, EnvVar("SCANNER_EARNINGS_WINDOW_DAYS")
    ] = 14
    # Discovery edge-quality scoring (radon parity). Weights must sum to 100.
    scanner_edge_quality_weight_dp_strength: Annotated[
        Decimal, EnvVar("SCANNER_EDGE_QUALITY_WEIGHT_DP_STRENGTH")
    ] = Decimal("30")
    scanner_edge_quality_weight_dp_sustained: Annotated[
        Decimal, EnvVar("SCANNER_EDGE_QUALITY_WEIGHT_DP_SUSTAINED")
    ] = Decimal("20")
    scanner_edge_quality_weight_confluence: Annotated[
        Decimal, EnvVar("SCANNER_EDGE_QUALITY_WEIGHT_CONFLUENCE")
    ] = Decimal("20")
    scanner_edge_quality_weight_vol_oi: Annotated[
        Decimal, EnvVar("SCANNER_EDGE_QUALITY_WEIGHT_VOL_OI")
    ] = Decimal("15")
    scanner_edge_quality_weight_sweeps: Annotated[
        Decimal, EnvVar("SCANNER_EDGE_QUALITY_WEIGHT_SWEEPS")
    ] = Decimal("15")
    scanner_discover_dp_top_n: Annotated[int, EnvVar("SCANNER_DISCOVER_DP_TOP_N")] = 50
    scanner_discover_dp_lookback_days: Annotated[
        int, EnvVar("SCANNER_DISCOVER_DP_LOOKBACK_DAYS")
    ] = 3
    scanner_discover_dp_sleep_ms: Annotated[
        int, EnvVar("SCANNER_DISCOVER_DP_SLEEP_MS")
    ] = 0  # optional inter-DP-fetch throttle (rate guard)
    scanner_discover_alerts_limit: Annotated[
        int, EnvVar("SCANNER_DISCOVER_ALERTS_LIMIT")
    ] = 200
    scanner_discover_scan_enabled: Annotated[
        bool, EnvVar("SCANNER_DISCOVER_SCAN_ENABLED", parse=_true_1_yes)
    ] = True
    # Offset off the top-of-hour so discovery doesn't contend with full_scan
    # (cron `0 5-16`). Covers ~09:15–16:45 ET (RTH + post-close settle).
    scanner_discover_scan_cron: Annotated[str, EnvVar("SCANNER_DISCOVER_SCAN_CRON")] = (
        "15,45 9-16 * * 0-4"
    )

    def scanner_edge_quality_weights(self) -> dict[str, Decimal]:
        return {
            "dp_strength": self.scanner_edge_quality_weight_dp_strength,
            "dp_sustained": self.scanner_edge_quality_weight_dp_sustained,
            "confluence": self.scanner_edge_quality_weight_confluence,
            "vol_oi": self.scanner_edge_quality_weight_vol_oi,
            "sweeps": self.scanner_edge_quality_weight_sweeps,
        }

    @model_validator(mode="after")
    def _check_edge_quality_weights(self) -> Self:
        total = sum(self.scanner_edge_quality_weights().values(), Decimal("0"))
        if total != Decimal("100"):
            raise ValueError(
                f"scanner edge-quality weights must sum to 100, got {total}"
            )
        return self
