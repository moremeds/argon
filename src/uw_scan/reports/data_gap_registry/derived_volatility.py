"""Derived volatility + regime/market-wide session datasets.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


DERIVED_VOLATILITY: list[DatasetRegistryEntry] = [
    # --- derived volatility (db-to-db) ---
    DatasetRegistryEntry(
        "vrp_daily",
        "derived_volatility",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="db",
        granularity="run_once",
        healer_adapter="vol_analytics_rollup",
        source_system="derived",
    ),
    DatasetRegistryEntry(
        "stock_analytics_daily",
        "derived_volatility",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="db",
        granularity="run_once",
        healer_adapter="vol_analytics_rollup",
        source_system="derived",
    ),
    DatasetRegistryEntry(
        # Technicals tab warm store: the nightly technical_daily_refresh recomputes
        # the FULL series from apex bars and upserts idempotently, so a missing
        # date self-heals on the next run — freshness matters, per-date backfill
        # does not (same treatment as intraday_quote / flow_alerts_daily_rollup).
        "technical_daily",
        "derived_volatility",
        "freshness_only",
        ticker_col="ticker",
        provider="db",
        granularity="run_once_lookback",
        healer_adapter="technical_daily",
        source_system="derived",
        reason=(
            "worker/jobs/technical_daily_refresh.technical_daily_refresh "
            "recomputes the FULL series per ticker from apex bars and upserts "
            "idempotently, so ONE run heals every historical hole — the "
            "'no per-date heal' note was right about the shape and wrong to "
            "conclude no heal exists."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    DatasetRegistryEntry(
        # UW /volatility/realized — full ~1y series in one call (NOT the rollup,
        # which only writes vrp_daily + stock_analytics_daily).
        "realized_volatility_history",
        "uw_volatility",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_range",
        healer_adapter="realized_volatility",
        source_system="uw",
    ),
    DatasetRegistryEntry(
        # UW /volatility/stats — one row per (ticker, date) via ?date=; the
        # current-snapshot fetcher is why this never backfilled before May 11.
        "volatility_stats_history",
        "uw_volatility",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="volatility_stats",
        source_system="uw",
    ),
    # --- regime / market-wide (session-level) ---
    DatasetRegistryEntry(
        "market_tide_sentiment_daily",
        "regime_marketwide",
        "strict_session",
        date_col="data_date",
        provider="db",
        granularity="run_once_lookback",
        healer_adapter="market_tide_sentiment",
        source_system="derived",
    ),
    DatasetRegistryEntry(
        "spx_density_forecast",
        "regime_marketwide",
        # freshness_only, not strict_session: a PROSPECTIVE cone for a past date cannot
        # be recreated retroactively -- what the healer writes is origin='reconstructed',
        # a separate in-sample tally. Healing the gap is legitimate; relabelling a
        # forward-issued row is not, and select_sessions is what forbids it.
        "freshness_only",
        date_col="as_of",
        ticker_col=None,
        expected_frequency="equity_session",
        provider="db",
        granularity="run_once_lookback",
        healer_adapter="spx_density_reconstruct",
        source_system="derived",
        reason=(
            "worker/jobs/spx_density_forecast.reconstruct_recent_gaps(conn, schema, "
            "lookback_days=) re-derives missing cones from vol_index_daily at zero "
            "provider cost -- same shape as CRI/VCG/canary. The issue pass anchors only "
            "the freshest bar, so a session it skipped is unreachable from that pass "
            "forever (2026-08-14). Writes origin='reconstructed' and never over a "
            "prospective row; deeper seeding stays with "
            "scripts/backfill/spx_density_backfill.py."
        ),
        reason_verified_on=date(2026, 8, 18),
    ),
    DatasetRegistryEntry(
        "market_tide_snapshots",
        "regime_marketwide",
        "strict_session",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="market_tide",
        source_system="uw",
        reason=(
            "scanners.market_tide.run already takes trading_date (and "
            "capture_spot=False for backfill); UW served all 4 outage dates with "
            "full 81-82 bar sessions. The previous 'current-session only' claim "
            "was never probed. This is the audit's calendar reference — healing "
            "it is what stops the spine going blind."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    DatasetRegistryEntry(
        "top_net_impact_snapshots",
        "regime_marketwide",
        "strict_session",
        provider="uw",
        granularity="per_ticker_date",
        healer_adapter="top_net_impact",
        source_system="uw",
        reason=(
            "scanners.top_net_impact.run already takes trading_date; UW served "
            "40 rows/date back to 2026-01-02 (121 sessions backfilled "
            "2026-08-16). The 'may return only current session' claim was untested."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
]
