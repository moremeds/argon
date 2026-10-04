"""Research artifacts and remaining scanner-state coverage (T7).

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry, entries


RESEARCH_ARTIFACT: list[DatasetRegistryEntry] = []


RESEARCH_ARTIFACT.extend(
    entries(
        [
            "api_request_audit",
            "external_api_requests",
            "raw_payloads",
            "scan_runs",
            "jobs",
            "worker_heartbeat",
            "volatility_backfill_status",
        ],
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    )
)

RESEARCH_ARTIFACT.extend(
    entries(
        [
            "regime_backtest_daily",
            "regime_backtest_runs",
            "vrp_backtest_results",
            "vrp_backtest_trades",
            "vrp_paper_positions",
            "vrp_macro_sweep_results",
            "backtest_sweep_runs",
            "backtest_sweep_results",
            "vrp_trade_candidates",
            "vrp_leg_nbbo",
            "vrp_harvest_by_sector",
            "vrp_harvest_multihorizon",
            "vrp_harvest_verdicts",
            "vrp_directional_verdicts",
            "vrp_dvrp_reversion",
            "vrp_rv_validation",
            "vrp_30d_settlements",
            "vrp_macro_entry",
            "vrp_macro_entry_grid",
            "vrp_macro_entry_quote",
            "vrp_macro_signal_daily",
            "skew_directional_verdicts",
            "skew_rv_reversion_verdicts",
            "skew_analytics_snapshot",
            "skew_swing_greeks",
            "iv_source_validation",
            "vanna_signals",
            "charm_signals",
        ],
        "research_artifact",
        "research_artifact",
        expected_frequency="event",
    )
)

# Theta Harvester (migration 109). Spelled out rather than folded into the
# entries list above so the heal instructions survive next to the entry.
RESEARCH_ARTIFACT.extend(
    [
        DatasetRegistryEntry(
            "theta_harvester_candidates",
            "research_artifact",
            # research_artifact, NOT strict_ticker_date. strict_ticker_date sets
            # the denominator to (eligible watchlist tickers x sessions), but
            # candidates only exist for tickers that clear the thin-input checks
            # -- so it would report a large, permanent, UNHEALABLE gap
            # (healer_adapter is None) on every audit forever.
            "research_artifact",
            date_col="as_of",
            ticker_col="ticker",
            expected_frequency="event",
            provider="db",
            # "none", not "run_once_lookback": granularity names how the healer
            # DISPATCHES, and there is no adapter here -- healing is a manual
            # backfill-script run. Claiming a granularity without an adapter
            # trips test_healable_entries_name_an_adapter_others_do_not_dispatch.
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            reason=(
                "Derived from option_surface_grid_daily; heal by re-running "
                "scripts/backfill/theta_harvester_backfill.py. Rows are absent "
                "by design for tickers with thin price history or no chain."
            ),
        ),
        DatasetRegistryEntry(
            "theta_harvester_markouts",
            "research_artifact",
            "research_artifact",
            date_col="as_of",
            ticker_col="ticker",
            expected_frequency="event",
            provider="db",
            granularity="none",  # no adapter -> no dispatch; see above
            healer_adapter=None,
            source_system="derived",
            reason=(
                "Forward re-marks accrue as sessions pass; a missing horizon is "
                "not-yet-reached rather than a gap. Written by the nightly "
                "theta_harvester_markout job."
            ),
        ),
    ]
)

RESEARCH_ARTIFACT.extend(
    entries(
        [
            "opportunity_scores",
            "signal_hits",
            "signal_context_flags",
            "signal_gates",
            "trade_insight_snapshots",
            "trade_insight_candidates",
            "trade_insight_ai_analyses",
            "trade_insight_outcomes",
            "watchlist",
        ],
        "scanner_state",
        "freshness_only",
        expected_frequency="liveness",
        reason=(
            "live state, not a time series: a row asserts what is true NOW and is "
            "rewritten in place. A missing row means the condition does not hold, "
            "not that history was lost — there is nothing to backfill."
        ),
        reason_verified_on=date(2026, 8, 16),
    )
)

# scanner_candidate_snapshots is NOT liveness, despite sitting in the same
# scanner_state group. Checked 2026-08-16 rather than assumed: surrogate `id`
# PK, an (ticker, scored_at DESC) index, and signals_repository's own docstring
# — "Append-only (no upsert) — every run accrues a new batch so history is
# preserved for Phase-2 markout". Production holds 7,389 rows across 23 dates.
# Pasting the liveness reason here would have written a false statement into
# the registry and buried a real series behind "nothing to backfill".
RESEARCH_ARTIFACT.extend(
    [
        DatasetRegistryEntry(
            "scanner_candidate_snapshots",
            "scanner_state",
            "freshness_only",
            ticker_col="ticker",
            expected_frequency="equity_session",
            source_system="derived",
            reason=(
                "Append-only scan history (one batch per scanner run), NOT live "
                "state. Re-deriving a past scan needs the flow/GEX inputs as they "
                "stood at scan time, which the warm store overwrites — so a lost "
                "batch is genuinely unrecoverable rather than merely unwired. "
                "Freshness-monitored so a stalled scanner is still visible."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)
