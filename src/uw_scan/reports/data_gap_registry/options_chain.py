"""Options-chain datasets (UW-budgeted heal adapters).

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


OPTIONS_CHAIN: list[DatasetRegistryEntry] = [
    # --- options chain (UW-budgeted) ---
    DatasetRegistryEntry(
        "option_surface_grid_daily",
        "options_chain",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="option_surface",
        source_system="uw",
        retention_days=None,  # attempt full history; empty UW response -> no_data once
    ),
    DatasetRegistryEntry(
        "greek_exposure_daily",
        "options_chain",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_range",
        healer_adapter="greek_exposure_daily",
        source_system="uw",
        retention_days=None,
        reason=(
            "UW /greek-exposure/{ticker} returns the FULL ~250-row date series in "
            "one call; measured 2026-08-16, 12 calls restored 3,000 rows across 4 "
            "outage dates"
        ),
    ),
    # --- UW historical alpha (migration 108) ---
    # retention_days is descriptive-only — the scanner keys on row EXISTENCE, not
    # nullness, so a VRP-only row counts as covered. A permanently-unhealable old
    # date is re-attempted each nightly run (same as greek_exposure_daily); add a
    # Caveat, not a retention_days, if that ever proves noisy.
    DatasetRegistryEntry(
        "uw_gex_levels_daily",
        "options_chain",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="gex_levels",
        source_system="uw",
        retention_days=None,
    ),
    DatasetRegistryEntry(
        "uw_volatility_signal_daily",
        "options_chain",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="volatility_signal",
        source_system="uw",
        retention_days=None,
        reason="VRP serves full YTD; anomaly/character ~16 recent sessions -> old dates fill VRP only",
    ),
    DatasetRegistryEntry(
        "uw_short_pressure_daily",
        "options_chain",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="short_pressure",
        source_system="uw",
        retention_days=None,
        reason="interest-float is current-snapshot; ftds/volumes carry history",
    ),
    DatasetRegistryEntry(
        "flow_alerts_daily_rollup",
        "options_chain",
        "freshness_only",
        ticker_col="ticker",
        source_system="derived",
        reason=(
            "Derived from flow_events, which UW cannot replay (byte-identical "
            "bodies across `date` values, response-hash differential "
            "2026-08-16). A derivative of an unreplayable source is itself "
            "unreplayable — this is a MEASURED refusal, not a TODO."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
]
