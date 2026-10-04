"""Options-chain tables probed for replay healability, wired adapters, and measured refusals.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry, entries


OPTIONS_CHAIN_REPLAY: list[DatasetRegistryEntry] = []


OPTIONS_CHAIN_REPLAY.extend(
    entries(
        [
            # migration-108 event logs: append-only, no (ticker,date) uniqueness
            # to audit-heal — freshness-monitored, backfilled via uw_alpha_catchup.
        ],
        "options_chain",
        "freshness_only",
        reason="UW-retention/event-log shaped; freshness-monitored, no auto-backfill",
    )
)

# Probed 2026-08-16 by response-hash differential, NOT by "HTTP 200 with rows"
# (three endpoints answer 200 with a full row set for any date you ask and serve
# the identical body every time — see docs/research/2026-08-16-replay-endpoint-matrix.md).
# The nine entries below are now healed by pipeline.run_single_stock(market_date=...)
# via the `pipeline_replay` adapter. The four that follow them stay freshness_only
# for reasons specific to each — read them; they are not the old blanket assumption.
OPTIONS_CHAIN_REPLAY.extend(
    [
        DatasetRegistryEntry(
            "oi_by_strike",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "oi_change_events",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "greeks_by_expiry_strike",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "exposures_by_expiry_strike",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "exposures_summary",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "iv_term_snapshots",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "interpolated_iv_snapshots",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "risk_reversal_skew_history",
            "options_chain",
            "freshness_only",
            reason=(
                "Self-healing: /historical-risk-reversal-skew returns a ~250-row trailing SERIES, so any nightly run re-persists the whole window. Measured 2026-08-16 at 170/170 tickers for the 2026-08-11..14 outage with no intervention. No adapter needed."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "max_pain_by_expiry",
            "options_chain",
            "strict_ticker_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "pcr_history",
            "options_chain",
            "strict_ticker_date",
            # snapshot_date is NOT in _DATE_COL_PREFERENCE, so auto-detect finds
            # nothing and the dataset silently audits as zero gaps. Explicit.
            date_col="snapshot_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="pipeline_replay",
            reason=(
                "Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...)."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "dark_pool_events",
            "options_chain",
            "freshness_only",
            reason=(
                "Written by the replay (UW honours ?date= on /darkpool/{ticker}, "
                "proven 2026-08-16) but keyed on executed_at: a name with no dark-pool "
                "print on a given session is legitimately absent, so a strict "
                "ticker-x-session audit would report phantom gaps for illiquid names."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "option_contract_snapshots",
            "options_chain",
            "freshness_only",
            reason=(
                "Written by the replay (UW honours ?date=, proven 2026-08-16) but the table has NO date column — only run_id/ticker/option_symbol — so it cannot carry a per-ticker-date audit. Freshness is the only honest measure here."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "iv_rank_history",
            "options_chain",
            "freshness_only",
            reason=(
                "Replayable in principle (UW honours ?date=, proven 2026-08-16) but written only for the 4 cockpit tickers by cockpit_daily_snapshot. A strict_ticker_date audit would measure it against the 170-name watchlist and invent ~166 phantom gaps per session, so it stays freshness_only."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "option_chain_per_strike",
            "options_chain",
            "strict_ticker_date",
            # snapshot_date is NOT in _DATE_COL_PREFERENCE, so auto-detect finds
            # nothing and the dataset silently audits as zero gaps. Explicit.
            date_col="snapshot_date",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="flow_chain_replay",
            reason=(
                "Replayable: UW honours ?date= on /option-contracts, proven "
                "2026-08-16 by response-hash differential. Owned by "
                "flow_data_refresh (not run_single_stock), and needs that "
                "session's close to pick the +/-60% strike band — a ticker with "
                "no daily_ohlc close for the date is skipped, not stamped with a "
                "live quote."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "option_intraday_buckets",
            "options_chain",
            "freshness_only",
            reason=(
                "UW serves this endpoint for past dates (probed 2026-08-16, HTTP 200 with rows). Blocked only by missing date plumbing in pipeline.run_single_stock — full_scan_once takes no `date`. Not a provider refusal."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)

# MEASURED refusals: probed by response-hash differential on 2026-08-16 — UW
# returns byte-identical bodies across different `date` values, so a
# date-looped replay would write today's payload under yesterday's key.
OPTIONS_CHAIN_REPLAY.extend(
    [
        DatasetRegistryEntry(
            "flow_events",
            "options_chain",
            "freshness_only",
            reason=(
                "UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill"
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "options_volume_daily",
            "options_chain",
            "freshness_only",
            reason=(
                "UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill"
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "short_interest_snapshots",
            "options_chain",
            "freshness_only",
            reason=(
                "UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill"
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "uw_positioning",
            "options_chain",
            "freshness_only",
            reason=(
                "UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill"
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)

# Wired in coverage-hardening Task 6.
OPTIONS_CHAIN_REPLAY.extend(
    [
        DatasetRegistryEntry(
            "vol_index_daily",
            "options_chain",
            "freshness_only",
            provider="db",
            granularity="run_once_lookback",
            healer_adapter="vol_index_lake",
            source_system="derived",
            reason=(
                "run_vol_index_lake_sync + run_credit_etf_lake_sync (worker/jobs/) both write this table from the market-warehouse lake at zero provider cost; used to heal Aug 11-14 on 2026-08-16."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "index_ohlc_daily",
            "options_chain",
            "freshness_only",
            provider="massive",
            granularity="run_once_lookback",
            healer_adapter="index_ohlc",
            source_system="massive",
            reason=(
                "worker/volatility_jobs.daily_spy_ohlc_refresh writes this (NOT the lake syncs — those write vol_index_daily). Its window was hardcoded to today-2d; it now takes lookback_days so the healer can reach an older hole."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "uw_dark_lit_flow_prints",
            "options_chain",
            "strict_ticker_date",
            ticker_col="ticker",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="uw_alpha_dark_lit",
            source_system="uw",
            reason=(
                "capture_dark_lit_for(client, repo, alpha_repo, run_id, ticker, market_date) already takes the date; scripts/backfill/uw_alpha_catchup.py backfill-eventlog healed all 4 outage dates on 2026-08-16. strict_ticker_date (not freshness_only) because a per_ticker_date adapter is dispatched only from gap items."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "uw_intraday_option_flow_bars",
            "options_chain",
            "strict_ticker_date",
            ticker_col="ticker",
            provider="uw",
            granularity="per_ticker_date",
            healer_adapter="uw_alpha_intraday_flow",
            source_system="uw",
            reason=(
                "capture_intraday_flow_for(...) already takes the date; same backfill-eventlog path as uw_dark_lit_flow_prints. Promoted to strict_ticker_date so the per_ticker_date adapter is actually dispatched."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)

# The one genuinely dead table. freshness_only implies something monitors it;
# measured 2026-08-16 it has 0 rows and no INSERT anywhere in the codebase.
# A dataset with no writer cannot go stale, so monitoring it is pure noise.
# NOTE the discipline this pair teaches: iv_smile_snapshots also has no
# grep-able writer, yet holds 700,540 rows — it is written indirectly via
# build_iv_smile_snapshot_rows. Check the ROW COUNT before calling a table
# dead; never grep for a writer.
OPTIONS_CHAIN_REPLAY.extend(
    [
        DatasetRegistryEntry(
            "oi_by_expiry",
            "options_chain",
            "excluded",
            reason=(
                "no writer anywhere in the codebase and 0 rows as of 2026-08-16; the table exists but nothing populates it"
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
    ]
)
