"""Healable macro/FRED/rates/gold ingest datasets plus credential-blocked freshness-only sources.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry, entries


GOLD_RATES_MACRO: list[DatasetRegistryEntry] = []


# Healable macro/FRED/rates/gold — freshness audit + run_once_lookback heal.
GOLD_RATES_MACRO.extend(
    [
        DatasetRegistryEntry(
            "macro_series_daily",
            "gold_rates_macro",
            "freshness_only",
            date_col="obs_date",
            provider="external",
            granularity="run_once_lookback",
            healer_adapter="macro_fred",
            source_system="fred",
            expected_frequency="daily",
        ),
        DatasetRegistryEntry(
            "macro_series_monthly",
            "gold_rates_macro",
            "freshness_only",
            date_col="obs_date",
            provider="external",
            granularity="run_once_lookback",
            healer_adapter="macro_fred",
            source_system="fred",
            expected_frequency="monthly",
        ),
    ]
    + entries(
        [
            "rates_observations",
            "rates_snapshots",
            "rates_policy_path",
            "rates_fiscal_debt_daily",
        ],
        "gold_rates_macro",
        "freshness_only",
        provider="external",
        granularity="run_once_lookback",
        healer_adapter="rates_fred",
        source_system="fred",
    )
    + entries(
        # Genuinely weekly-cadence FRED series, not daily -- previously
        # defaulted to expected_frequency="equity_session" (the dataclass
        # default), which meant the freshness monitor's frequency-derived
        # grace period was wrong for these regardless of any per-table
        # override.
        ["rates_cftc_tff_weekly", "rates_treasury_auctions"],
        "gold_rates_macro",
        "freshness_only",
        provider="external",
        granularity="run_once_lookback",
        healer_adapter="rates_fred",
        source_system="fred",
        expected_frequency="weekly",
    )
    + entries(
        # FOMC-meeting-driven, ~8x/year -- genuinely event-shaped, not
        # periodic at any fixed cadence.
        ["rates_policy_events"],
        "gold_rates_macro",
        "freshness_only",
        provider="external",
        granularity="run_once_lookback",
        healer_adapter="rates_fred",
        source_system="fred",
        expected_frequency="event",
    )
    + [
        DatasetRegistryEntry(
            "gold_posture_daily",
            "gold_rates_macro",
            "freshness_only",
            provider="db",
            granularity="run_once",
            healer_adapter="gold_posture",
            source_system="derived",
        ),
        DatasetRegistryEntry(
            "uw_gold_options_daily",
            "gold_rates_macro",
            "freshness_only",
            provider="uw",
            granularity="run_once",
            healer_adapter="gold_uw_options",
            source_system="uw",
        ),
        DatasetRegistryEntry(
            "exchange_inventory_daily",
            "gold_rates_macro",
            "freshness_only",
            provider="external",
            granularity="run_once",
            healer_adapter="gold_lbma",
            source_system="lbma",
            # LBMA is the only writer: the COMEX scraper (CME 403, never wrote a
            # row) was deleted 2026-10.
            expected_frequency="monthly",
        ),
        DatasetRegistryEntry(
            "cot_gold_weekly",
            "gold_rates_macro",
            "freshness_only",
            provider="external",
            granularity="run_once",
            healer_adapter="gold_cot",
            source_system="cftc",
            expected_frequency="weekly",
        ),
    ]
)

GOLD_RATES_MACRO.extend(
    entries(
        ["etf_holdings_daily", "etf_flows_daily", "etf_aum_cache"],
        "gold_rates_macro",
        "freshness_only",
        reason=(
            "EXTERNAL-PROVIDER BLOCK, not a healer gap: the source requires an "
            "interactive auth cookie and exposes no historical API, so there is "
            "nothing for an adapter to call. Re-probe if a credential is ever "
            "provisioned."
        ),
        reason_verified_on=date(2026, 8, 16),
    )
    + entries(
        # WGC releases monthly -- previously defaulted to "equity_session",
        # which meant a frequency-derived grace period would have been wrong
        # even before the missing-credential block is ever fixed.
        ["wgc_etf_monthly", "wgc_etf_monthly_canonical", "cb_gold_reserves_monthly"],
        "gold_rates_macro",
        "freshness_only",
        reason=(
            "World Gold Council source requires an interactive auth cookie and "
            "exposes no historical API; the ingest can only capture what is live "
            "at fetch time. Same failure as etf_holdings_daily."
        ),
        reason_verified_on=date(2026, 8, 16),
        expected_frequency="monthly",
    )
)
