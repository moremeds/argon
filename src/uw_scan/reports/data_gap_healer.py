"""Exact per-ticker/date gap audit + heal specs (strict cousin of data_freshness).

`data_freshness` answers "is this table fresh enough?" with a grace window and a
curated allow-list. This module answers the stricter question "exactly which
(ticker, date) rows are missing?" with no grace, and classifies EVERY recorded
dataset through a registry so nothing is silently uncovered.

Each dataset declares an ``audit_mode`` (how to measure coverage) and, when
healable, a ``provider`` + ``granularity`` + ``healer_adapter`` naming an EXISTING
job to re-run. The healer never invents a second write path; it orchestrates the
production writers Argon already uses.

Plan: docs/superpowers/plans/2026-06-30-data-gap-healer.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from psycopg import Connection

# How coverage is measured for a dataset.
AuditMode = Literal[
    "strict_ticker_date",  # denominator = eligible watchlist tickers x sessions
    "strict_session",  # denominator = sessions (no ticker dimension)
    "freshness_only",  # newest write age matters, exact coverage does not
    "operational_state",  # liveness/state row; no historical gap healing
    "provenance",  # raw/audit/event log; never rewritten or backfilled
    "research_artifact",  # persisted backtest/research output; audit existence only
    "excluded",  # intentionally outside healer scope (reason required)
]
# Which budget bucket a heal spends from.
Provider = Literal["uw", "massive", "external", "db", "none"]
# How the heal is dispatched.
Granularity = Literal[
    "run_once",  # whole-run idempotent job (vol rollup, sentiment refresh)
    "run_once_lookback",  # idempotent ingest job re-run with a lookback window (FRED/gold/rates)
    "per_ticker_range",  # fetch one ticker over a date range (Massive OHLC)
    "per_ticker_date",  # build one ticker-date (option surface)
    "none",  # not healable (freshness/provenance/excluded)
]

# SPCX listed 2026-06-17; before that it is not a valid strict denominator.
# Encoded as a seed Caveat below (data, not hardcoded SQL) so the rule is uniform.
SPCX_LISTED_ON = date(2026, 6, 17)

# Date/ticker column auto-detection. Superset of data_freshness's order plus the
# data_date / obs_date columns used by sentiment + FRED macro tables.
_DATE_COL_PREFERENCE: tuple[str, ...] = (
    "market_date",
    "trade_date",
    "session_date",
    "data_date",
    "curr_date",
    "as_of_date",
    "obs_date",
    "date",
)
_TICKER_COL_PREFERENCE: tuple[str, ...] = (
    "ticker",
    "symbol",
    "underlying",
    "underlying_symbol",
)


@dataclass(frozen=True)
class DatasetRegistryEntry:
    """One recorded dataset and how the healer treats it."""

    table_name: str
    dataset_group: str
    audit_mode: AuditMode
    date_col: str | None = None  # None -> auto-detect at scan time
    ticker_col: str | None = None  # None -> auto-detect (or genuinely tickerless)
    expected_frequency: str = (
        "equity_session"  # equity_session|weekly|monthly|event|liveness|none
    )
    provider: Provider = "none"
    granularity: Granularity = "none"
    healer_adapter: str | None = None  # key into the heal-dispatch registry (T4)
    source_system: str | None = None
    retention_days: int | None = None  # source history limit; older -> no_data
    enabled: bool = True
    reason: str | None = None  # required when audit_mode == 'excluded'


@dataclass(frozen=True)
class Caveat:
    """A known no-data exclusion: (dataset, ticker, [start,end]) -> reason."""

    dataset: str
    ticker: str | None
    start_date: date | None  # None = open lower bound
    end_date: date | None  # None = open upper bound
    reason: str
    source: str = "manual"


@dataclass(frozen=True)
class GapItem:
    """A single missing scope (one row per MISS, never per expected pair)."""

    dataset: str
    scope_key: str  # stable unique key within a run, e.g. "2026-06-22|KORU"
    data_date: date | None
    ticker: str | None
    expected_count: int | None
    covered_count: int | None
    status: str = "planned"  # planned|running|healed|no_data|skipped_budget|failed
    reason: str | None = None


@dataclass(frozen=True)
class CoverageSummary:
    """Per-dataset rollup, stored in data_gap_runs.summary_jsonb (not per pair)."""

    dataset: str
    audit_mode: AuditMode
    expected_pairs: int
    covered_pairs: int
    missing_pairs: int
    gap_dates: tuple[date, ...]


# Seed caveats. SPCX is excluded from strict denominators through the day before
# it listed -> the eligibility filter handles it generically, no special-casing.
SEED_CAVEATS: tuple[Caveat, ...] = (
    Caveat(
        dataset="option_surface_grid_daily",
        ticker="SPCX",
        start_date=None,
        end_date=date(2026, 6, 16),
        reason="listed after 2026-06-17",
        source="manual",
    ),
)


# Core registry: the actively-healed warm-store datasets + key state tables. The
# remaining ~70 families (full coverage incl. macro/FRED/rates/gold) are appended
# in T7. Group names match the policy buckets in the dataset-policy runbook (T6).
REGISTRY: list[DatasetRegistryEntry] = [
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
        granularity="per_ticker_date",
        healer_adapter="greek_exposure_daily",
        source_system="uw",
        retention_days=1,
        reason="UW aggregate returns the current snapshot only; past dates -> no_data",
    ),
    DatasetRegistryEntry(
        "flow_alerts_daily_rollup",
        "options_chain",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="db",
        granularity="run_once",
        healer_adapter="flow_rollup",
        source_system="derived",
        reason="heals only from existing flow_events; pre-ingest gaps unhealable",
    ),
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
    ),
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
        "realized_volatility_history",
        "derived_volatility",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="db",
        granularity="run_once",
        healer_adapter="vol_analytics_rollup",
        source_system="derived",
    ),
    DatasetRegistryEntry(
        "volatility_stats_history",
        "derived_volatility",
        "strict_ticker_date",
        ticker_col="ticker",
        provider="db",
        granularity="run_once",
        healer_adapter="vol_analytics_rollup",
        source_system="derived",
    ),
    # --- regime / market-wide (session-level) ---
    DatasetRegistryEntry(
        "market_tide_sentiment_daily",
        "regime_marketwide",
        "strict_session",
        date_col="data_date",
        provider="db",
        granularity="run_once",
        healer_adapter="market_tide_sentiment",
        source_system="derived",
    ),
    DatasetRegistryEntry(
        "market_tide_snapshots",
        "regime_marketwide",
        "strict_session",
        provider="uw",
        granularity="run_once",
        healer_adapter="market_tide",
        source_system="uw",
        retention_days=1,
        reason="UW market-tide is current-session; historical may be unavailable",
    ),
    DatasetRegistryEntry(
        "top_net_impact_snapshots",
        "regime_marketwide",
        "strict_session",
        provider="uw",
        granularity="run_once",
        healer_adapter="top_net_impact",
        source_system="uw",
        retention_days=1,
        reason="UW historical endpoint may return only the current session",
    ),
    # --- scanner / page state (freshness) ---
    DatasetRegistryEntry(
        "watchlist_card",
        "scanner_state",
        "freshness_only",
        ticker_col="ticker",
        expected_frequency="liveness",
    ),
    # --- operational / provenance (audit only, never healed) ---
    DatasetRegistryEntry(
        "pipeline_benchmark_snapshots",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_freshness_snapshots",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "ws_consumer_state",
        "operational_provenance",
        "operational_state",
        expected_frequency="liveness",
    ),
]


def registered_table_names(registry: list[DatasetRegistryEntry]) -> set[str]:
    return {e.table_name for e in registry}


def eligible_tickers_for_date(
    active_tickers: list[str],
    data_date: date,
    caveats: tuple[Caveat, ...] | list[Caveat],
) -> set[str]:
    """Active watchlist minus any ticker caveated out on ``data_date``.

    A caveat applies when its ticker matches and ``data_date`` falls within
    [start_date, end_date] (open bounds = None). This is how SPCX is kept out of
    the denominator before it listed, without hardcoding the symbol or date here.
    """
    active = {t.upper() for t in active_tickers}
    for cav in caveats:
        if cav.ticker is None:
            continue
        if cav.start_date is not None and data_date < cav.start_date:
            continue
        if cav.end_date is not None and data_date > cav.end_date:
            continue
        active.discard(cav.ticker.upper())
    return active


def temporal_tables(conn: Connection, schema: str) -> set[str]:
    """Every table in ``schema`` that has any date/time/_at-ish column.

    Mirrors the registry-acceptance SQL in the plan: a table is "recorded data"
    if it has a temporal column. Pure set-difference against the registry lives
    in ``unregistered`` so it can be unit-tested without a DB.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
              FROM information_schema.columns
             WHERE table_schema = %s
             GROUP BY table_name
            HAVING bool_or(
                data_type IN (
                    'date',
                    'timestamp with time zone',
                    'timestamp without time zone'
                )
                OR lower(column_name) LIKE '%%date%%'
                OR lower(column_name) LIKE '%%time%%'
                OR lower(column_name) LIKE '%%\\_at'
            )
            """,
            (schema,),
        )
        return {r[0] for r in cur.fetchall()}


def unregistered(temporal: set[str], registry: list[DatasetRegistryEntry]) -> list[str]:
    """Temporal tables with no registry row -> the 'did we forget one?' list."""
    return sorted(temporal - registered_table_names(registry))


def discover_unregistered_tables(
    conn: Connection,
    schema: str,
    registry: list[DatasetRegistryEntry] | None = None,
) -> list[str]:
    reg = REGISTRY if registry is None else registry
    return unregistered(temporal_tables(conn, schema), reg)
