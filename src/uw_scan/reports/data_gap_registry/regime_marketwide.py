"""Regime scanners with historical recovery entrypoints.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


REGIME_MARKETWIDE: list[DatasetRegistryEntry] = []


REGIME_MARKETWIDE.extend(
    [
        DatasetRegistryEntry(
            # STILL UNCOVERED, and deliberately so. Unlike GRG, this is not a
            # truncate-the-series fix: scanners/gex.py::run resolves a LIVE spot
            # and raises without one, so historical replay needs a spot source
            # per (ticker, date). Real work, out of scope for coverage hardening
            # — the honest answer is a dated refusal, not a silent gap.
            "gex_snapshots",
            "regime_marketwide",
            "freshness_only",
            source_system="uw",
            reason=(
                "scanners.gex.run resolves a live spot and raises without one; "
                "historical replay needs a spot source per (ticker, date). "
                "Unlike grg.run this is not fixable by truncating a fetched "
                "series. Tracked as follow-up work, not a provider refusal."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "matrix_state_snapshots",
            "regime_marketwide",
            "freshness_only",
            source_system="derived",
            reason=(
                "Cockpit-derived: written by cockpit_daily_snapshot, which reads "
                "the option-chain tables full_scan_once cannot yet replay. "
                "Cascades off that block rather than being independently "
                "refused; wired by coverage-hardening Task 7."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)

# Regime scanners that DO have a historical recovery entrypoint. The blanket
# "re-derive needs historical inputs (audit-only)" reason above was written
# without probing: recover_recent_gaps has existed in all three modules and was
# used to heal every one of them during the Aug 11-14 outage recovery.
REGIME_MARKETWIDE.extend(
    [
        DatasetRegistryEntry(
            # strict_session, NOT freshness_only: gap items are produced only by
            # strict_* modes and a per_ticker_date adapter is dispatched only
            # from those items, so freshness_only would make grg_as_of dead code
            # (see tests/unit/reports/test_no_dead_adapters.py). One marketwide
            # row per session keyed data_date — the same shape as
            # market_tide_snapshots / top_net_impact_snapshots.
            "grg_snapshots",
            "regime_marketwide",
            "strict_session",
            date_col="data_date",
            ticker_col=None,
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="grg_as_of",
            source_system="uw",
            reason=(
                "grg.run(as_of=) truncates the 1Y SPY/TLT greek-exposure series "
                "AND reads spot/flip/SPY-closes at that date, so past snapshots "
                "are reconstructible rather than restamped. An as_of with fewer "
                "than 70 aligned observations honestly returns no_data."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "cri_snapshots",
            "regime_marketwide",
            "freshness_only",
            provider="db",
            granularity="run_once_lookback",
            healer_adapter="cri_recover",
            source_system="derived",
            reason=(
                "scanners.cri.recover_recent_gaps(conn, schema, lookback_days=) "
                "re-derives missing snapshots from vol_index_daily at zero "
                "provider cost; used to heal Aug 11-14 on 2026-08-16."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "vcg_snapshots",
            "regime_marketwide",
            "freshness_only",
            provider="db",
            granularity="run_once_lookback",
            healer_adapter="vcg_recover",
            source_system="derived",
            reason=(
                "scanners.vcg.recover_recent_gaps(conn, schema, lookback_days=) "
                "re-derives from vol_index_daily; same shape as CRI."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "canary_snapshots",
            "regime_marketwide",
            "freshness_only",
            provider="db",
            granularity="run_once_lookback",
            healer_adapter="canary_recover",
            source_system="derived",
            reason=(
                "scanners.canary.recover_recent_gaps(conn, schema, "
                "lookback_days=) re-derives from vol_index_daily. "
                "composite_version is part of the uniqueness key, so a snapshot "
                "from an older calibration does not count as filled."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "massive_fundamentals",
            "options_chain",
            "freshness_only",
            ticker_col="ticker",
            provider="massive",
            granularity="run_once_lookback",
            healer_adapter="massive_fundamentals",
            source_system="massive",
            reason=(
                "worker/jobs/fundamentals_jobs.fundamentals_refresh_once(repo=..., "
                "provider=...) re-pulls the current statement set per watchlist "
                "ticker and upserts idempotently."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "corporate_actions",
            "options_chain",
            "freshness_only",
            ticker_col="ticker",
            provider="massive",
            granularity="run_once_lookback",
            healer_adapter="corporate_actions",
            source_system="massive",
            reason=(
                "worker/jobs/corporate_actions_jobs.corporate_actions_refresh_once"
                "(repo, provider) re-pulls the last 12 splits / 24 dividends per "
                "ticker, so a missed run self-heals."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "iv_smile_snapshots",
            "options_chain",
            "freshness_only",
            ticker_col="ticker",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            reason=(
                "DERIVED, not UW-retention: reports/volatility_series.py builds "
                "it from greeks_by_expiry_strike via build_iv_smile_snapshot_rows "
                "inside run_volatility_backfill (NOT the nightly vol rollup — "
                "that imports only persist_stock_analytics "
                "/ persist_vrp_daily). Cascades off greeks_by_expiry_strike; "
                "wired in Task 7. 700,540 rows, newest 2026-08-16 — live, not "
                "legacy."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)
