"""Core watchlist market data (OHLC, live state, misc).

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


CORE_WATCHLIST: list[DatasetRegistryEntry] = [
    # --- core market data ---
    DatasetRegistryEntry(
        "daily_ohlc",
        "core_watchlist",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="massive",
        granularity="per_ticker_range",
        healer_adapter="daily_ohlc",
        source_system="massive",
    ),
    DatasetRegistryEntry(
        "intraday_quote",
        "core_watchlist",
        "freshness_only",
        ticker_col="ticker",
        expected_frequency="liveness",
        reason=(
            "live state, not a time series: a row asserts what is true NOW "
            "and is rewritten in place. A missing row means the condition does "
            "not hold, not that history was lost — there is nothing to "
            "backfill."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    DatasetRegistryEntry(
        # Latest-only live-technicals cache (upsert per ticker off intraday_quote,
        # recomputed live). Age matters, exact coverage does not — no backfill.
        "technical_live",
        "core_watchlist",
        "freshness_only",
        ticker_col="ticker",
        expected_frequency="liveness",
        reason=(
            "live state, not a time series: a row asserts what is true NOW "
            "and is rewritten in place. A missing row means the condition does "
            "not hold, not that history was lost — there is nothing to "
            "backfill."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    DatasetRegistryEntry(
        # User-set VWAP anchor for the Technicals price pane (one row per
        # ticker, written only on user click). No cadence to audit.
        "technical_vwap_anchor",
        "core_watchlist",
        "excluded",
        ticker_col="ticker",
        expected_frequency="none",
        reason="user-triggered anchor state; written only on click, no expected cadence",
    ),
    DatasetRegistryEntry(
        # UW /api/market/economic-calendar exposes only the current+next
        # week with no date parameter -- a missed capture day's window is
        # gone, never re-fetchable from this source. No ticker dimension.
        "macro_release_calendar",
        "core_watchlist",
        "excluded",
        date_col="scheduled_at",
        expected_frequency="none",
        reason=(
            "UW's economic-calendar endpoint has no history/date param "
            "(current+next week only); a missed capture cannot be backfilled "
            "from this source"
        ),
        reason_verified_on=date(2026, 9, 9),
    ),
    DatasetRegistryEntry(
        # Sector RS + breadth (migration 152). Derived from apex adjusted bars at
        # zero provider cost. Not healer-enrolled by design (spec 2026-09-26 §5):
        # the resumable backfill script shares the nightly job's compute core
        # and IS the heal.
        "sector_rs_daily",
        "regime_marketwide",
        "excluded",
        date_col="as_of",
        ticker_col=None,
        expected_frequency="none",
        reason=(
            "derived from apex bars; the heal is scripts/backfill/"
            "sector_rs_backfill.py (resumable, same compute core as the nightly "
            "job), not a healer adapter; freshness is watched via MONITORED_TABLES"
        ),
    ),
]
