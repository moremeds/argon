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
from psycopg import sql as psql

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
        reason="derived from flow_events; heal adapter is a TODO (audit-only)",
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
    DatasetRegistryEntry(
        # Latest-only live-technicals cache (upsert per ticker off intraday_quote,
        # recomputed live). Age matters, exact coverage does not — no backfill.
        "technical_live",
        "core_watchlist",
        "freshness_only",
        ticker_col="ticker",
        expected_frequency="liveness",
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
        source_system="derived",
        reason="full series recomputed nightly from apex bars; no per-date heal",
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
        "market_tide_snapshots",
        "regime_marketwide",
        "strict_session",
        source_system="uw",
        retention_days=1,
        reason="UW market-tide is current-session; historical heal TODO (audit-only)",
    ),
    DatasetRegistryEntry(
        "top_net_impact_snapshots",
        "regime_marketwide",
        "strict_session",
        source_system="uw",
        retention_days=1,
        reason="UW historical endpoint may return only current session; heal TODO",
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
    # the healer's own bookkeeping tables (registered so discovery stays honest)
    DatasetRegistryEntry(
        "data_gap_runs",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_gap_items",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_gap_caveats",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_gap_dataset_registry",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "watchlist_ticker_events",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "chanlun_signal_events",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    # Ephemeral same-day UW fetch dedupe cache (#225): rows live one trading day
    # and are pruned; there is nothing to backfill or heal.
    DatasetRegistryEntry(
        "uw_fetch_memo",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="ephemeral same-day fetch dedupe cache; pruned daily, nothing to backfill/heal",
    ),
    # Ops-hardening job-failure streaks (#C12): per-job consecutive-failure
    # counters maintained live by the scheduler listener — not a time series,
    # nothing to backfill or heal.
    DatasetRegistryEntry(
        "job_failures",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="live per-job failure-streak state; scheduler-maintained, nothing to backfill/heal",
    ),
]


def _entries(
    tables: list[str], group: str, mode: AuditMode, **kw
) -> list[DatasetRegistryEntry]:
    return [DatasetRegistryEntry(t, group, mode, **kw) for t in tables]


# --- full coverage (T7): every remaining temporal table classified -----------
# Strict modes are kept only for tables we actually heal; big un-healable
# per-ticker tables are freshness_only (the data_freshness monitor already
# covers them) to avoid a gap-item explosion. macro/FRED/rates/gold are
# freshness_only for audit but carry a run_once_lookback heal adapter (re-run
# the idempotent ingest over a lookback window).

REGISTRY.extend(
    _entries(
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

REGISTRY.extend(
    _entries(
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
# _entries list above so the heal instructions survive next to the entry.
REGISTRY.extend(
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

REGISTRY.extend(
    _entries(
        [
            "opportunity_scores",
            "signal_hits",
            "signal_context_flags",
            "signal_gates",
            "scanner_candidate_snapshots",
            "trade_insight_snapshots",
            "trade_insight_candidates",
            "trade_insight_ai_analyses",
            "trade_insight_outcomes",
            "watchlist",
        ],
        "scanner_state",
        "freshness_only",
        expected_frequency="liveness",
    )
)

REGISTRY.extend(
    _entries(
        [
            "options_volume_daily",
            "pcr_history",
            "flow_events",
            "dark_pool_events",
            "option_contract_snapshots",
            "option_chain_per_strike",
            "iv_rank_history",
            "iv_term_snapshots",
            "interpolated_iv_snapshots",
            "risk_reversal_skew_history",
            "greeks_by_expiry_strike",
            "exposures_by_expiry_strike",
            "exposures_summary",
            "oi_by_strike",
            "oi_by_expiry",
            "oi_change_events",
            "max_pain_by_expiry",
            "short_interest_snapshots",
            "uw_positioning",
            "massive_fundamentals",
            "corporate_actions",
            "iv_smile_snapshots",
            "option_intraday_buckets",
            "index_ohlc_daily",
            "vol_index_daily",
            # migration-108 event logs: append-only, no (ticker,date) uniqueness
            # to audit-heal — freshness-monitored, backfilled via uw_alpha_catchup.
            "uw_dark_lit_flow_prints",
            "uw_intraday_option_flow_bars",
        ],
        "options_chain",
        "freshness_only",
        reason="UW-retention/event-log shaped; freshness-monitored, no auto-backfill",
    )
)

REGISTRY.extend(
    _entries(
        [
            "gex_snapshots",
            "cri_snapshots",
            "vcg_snapshots",
            "grg_snapshots",
            "matrix_state_snapshots",
            "canary_snapshots",
        ],
        "regime_marketwide",
        "freshness_only",
        reason="regime scanner output; re-derive needs historical inputs (audit-only)",
    )
)

# Healable macro/FRED/rates/gold — freshness audit + run_once_lookback heal.
REGISTRY.extend(
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
    + _entries(
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
    + _entries(
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
    + _entries(
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
            healer_adapter="gold_comex",
            source_system="comex",
            # COMEX leg is intended daily but blocked (CME 403); LBMA leg is
            # the only realistic contributor, on an ~monthly cadence.
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

REGISTRY.extend(
    _entries(
        ["etf_holdings_daily", "etf_flows_daily", "etf_aum_cache"],
        "gold_rates_macro",
        "freshness_only",
        reason="source needs auth cookie / no historical API (audit-only)",
    )
    + _entries(
        # WGC releases monthly -- previously defaulted to "equity_session",
        # which meant a frequency-derived grace period would have been wrong
        # even before the missing-credential block is ever fixed.
        ["wgc_etf_monthly", "wgc_etf_monthly_canonical", "cb_gold_reserves_monthly"],
        "gold_rates_macro",
        "freshness_only",
        reason="source needs auth cookie / no historical API (audit-only)",
        expected_frequency="monthly",
    )
)


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


# --- read-only coverage scanner --------------------------------------------

# The canonical equity-session calendar. We use ONLY this clean trading-day
# reference (market_tide_sentiment_daily: weekday-only, holiday-excluded — UW
# emits no sentiment on closed-market days). Earlier we also self-unioned the
# dataset's own dates, but a stray weekend/holiday price-bar in the dataset then
# leaked that non-trading day into its own expected calendar, manufacturing a
# full-watchlist phantom gap for every ticker missing that bar. Limitation: the
# window cannot extend before the reference table's earliest date (YTD scope).
_REFERENCE_CALENDAR = ("market_tide_sentiment_daily", "data_date")


def _detect_col(
    conn: Connection, schema: str, table: str, preference: tuple[str, ...]
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        cols = {r[0] for r in cur.fetchall()}
    for pref in preference:
        if pref in cols:
            return pref
    return None


def _calendar_dates(
    conn: Connection,
    schema: str,
    start: date,
    end: date,
) -> list[date]:
    """Trading-day calendar in [start, end] from the clean session reference.

    No self-union: the reference (market_tide_sentiment_daily) is the sole
    source of expected sessions, so weekends/holidays never enter. A dataset
    row on a non-trading day no longer manufactures a phantom calendar entry.
    """
    ref_tbl, ref_col = _REFERENCE_CALENDAR
    query = psql.SQL(
        """
        SELECT DISTINCT {rcol} AS d FROM {rtbl}
         WHERE {rcol} BETWEEN %s AND %s AND {rcol} IS NOT NULL
         ORDER BY d
        """
    ).format(
        rcol=psql.Identifier(ref_col),
        rtbl=psql.Identifier(schema, ref_tbl),
    )
    with conn.cursor() as cur:
        cur.execute(query, (start, end))
        return [r[0] for r in cur.fetchall()]


def _missing_ticker_date_pairs(
    conn: Connection,
    schema: str,
    table: str,
    date_col: str,
    ticker_col: str,
    calendar: list[date],
    tickers: list[str],
) -> list[tuple[date, str]]:
    if not calendar or not tickers:
        return []
    query = psql.SQL(
        """
        SELECT cal.d, tk.t
          FROM unnest(%s::date[]) AS cal(d)
          CROSS JOIN unnest(%s::text[]) AS tk(t)
          LEFT JOIN {tbl} a
                 ON a.{dcol} = cal.d AND UPPER(a.{tcol}) = tk.t
         WHERE a.{tcol} IS NULL
         ORDER BY cal.d, tk.t
        """
    ).format(
        tbl=psql.Identifier(schema, table),
        dcol=psql.Identifier(date_col),
        tcol=psql.Identifier(ticker_col),
    )
    with conn.cursor() as cur:
        cur.execute(query, (calendar, tickers))
        return [(r[0], r[1]) for r in cur.fetchall()]


def _present_session_dates(
    conn: Connection, schema: str, table: str, date_col: str, start: date, end: date
) -> set[date]:
    query = psql.SQL(
        "SELECT DISTINCT {dcol} FROM {tbl} WHERE {dcol} BETWEEN %s AND %s"
    ).format(dcol=psql.Identifier(date_col), tbl=psql.Identifier(schema, table))
    with conn.cursor() as cur:
        cur.execute(query, (start, end))
        return {r[0] for r in cur.fetchall() if r[0] is not None}


def _scan_strict_ticker_date(
    conn: Connection,
    schema: str,
    entry: DatasetRegistryEntry,
    active: list[str],
    caveats: tuple[Caveat, ...] | list[Caveat],
    start: date,
    end: date,
) -> tuple[CoverageSummary, list[GapItem]]:
    table = entry.table_name
    date_col = entry.date_col or _detect_col(conn, schema, table, _DATE_COL_PREFERENCE)
    tcol = entry.ticker_col or _detect_col(conn, schema, table, _TICKER_COL_PREFERENCE)
    if not date_col or not tcol:
        return CoverageSummary(table, "strict_ticker_date", 0, 0, 0, ()), []

    calendar = _calendar_dates(conn, schema, start, end)
    eligible_by_date = {
        d: eligible_tickers_for_date(active, d, caveats) for d in calendar
    }
    tickers = sorted({t.upper() for t in active})
    raw = _missing_ticker_date_pairs(
        conn, schema, table, date_col, tcol, calendar, tickers
    )

    items: list[GapItem] = []
    gap_dates: set[date] = set()
    for d, tk in raw:
        if tk not in eligible_by_date.get(d, set()):
            continue  # caveated out (e.g. SPCX pre-listing)
        items.append(
            GapItem(table, f"{d.isoformat()}|{tk}", d, tk, None, None, "planned")
        )
        gap_dates.add(d)

    expected = sum(len(v) for v in eligible_by_date.values())
    missing = len(items)
    summary = CoverageSummary(
        table,
        "strict_ticker_date",
        expected,
        expected - missing,
        missing,
        tuple(sorted(gap_dates)),
    )
    return summary, items


def _scan_strict_session(
    conn: Connection,
    schema: str,
    entry: DatasetRegistryEntry,
    start: date,
    end: date,
) -> tuple[CoverageSummary, list[GapItem]]:
    table = entry.table_name
    date_col = entry.date_col or _detect_col(conn, schema, table, _DATE_COL_PREFERENCE)
    if not date_col:
        return CoverageSummary(table, "strict_session", 0, 0, 0, ()), []
    calendar = _calendar_dates(conn, schema, start, end)
    present = _present_session_dates(conn, schema, table, date_col, start, end)
    missing_dates = [d for d in calendar if d not in present]
    items = [
        GapItem(table, d.isoformat(), d, None, None, None, "planned")
        for d in missing_dates
    ]
    summary = CoverageSummary(
        table,
        "strict_session",
        len(calendar),
        len(calendar) - len(missing_dates),
        len(missing_dates),
        tuple(missing_dates),
    )
    return summary, items


def scan_dataset(
    conn: Connection,
    schema: str,
    entry: DatasetRegistryEntry,
    active: list[str],
    caveats: tuple[Caveat, ...] | list[Caveat],
    start: date,
    end: date,
) -> tuple[CoverageSummary, list[GapItem]]:
    """Coverage + gap items for one dataset, branching on audit_mode.

    Only ``strict_*`` modes produce gap items. freshness/operational/provenance/
    research/excluded datasets are accounted for (a summary row) but never get
    gap items here — they are not strict-coverage problems.
    """
    if entry.audit_mode == "strict_ticker_date":
        return _scan_strict_ticker_date(
            conn, schema, entry, active, caveats, start, end
        )
    if entry.audit_mode == "strict_session":
        return _scan_strict_session(conn, schema, entry, start, end)
    return CoverageSummary(entry.table_name, entry.audit_mode, 0, 0, 0, ()), []


def audit(
    conn: Connection,
    schema: str,
    registry: list[DatasetRegistryEntry],
    active: list[str],
    caveats: tuple[Caveat, ...] | list[Caveat],
    start: date,
    end: date,
    datasets: list[str] | None = None,
) -> tuple[list[CoverageSummary], list[GapItem]]:
    """Read-only exact-coverage audit. Makes ZERO provider calls."""
    wanted = set(datasets) if datasets else None
    summaries: list[CoverageSummary] = []
    items: list[GapItem] = []
    for entry in registry:
        if not entry.enabled:
            continue
        if wanted is not None and entry.table_name not in wanted:
            continue
        summary, dataset_items = scan_dataset(
            conn, schema, entry, active, caveats, start, end
        )
        summaries.append(summary)
        items.extend(dataset_items)
    return summaries, items


def render_dataset_policy_markdown(
    registry: list[DatasetRegistryEntry] | None = None,
) -> str:
    """Generate the dataset-policy runbook table from the registry (one source
    of truth). Re-run after registry changes; committed to docs/runbooks/."""
    reg = REGISTRY if registry is None else registry
    by_group: dict[str, list[DatasetRegistryEntry]] = {}
    for e in reg:
        by_group.setdefault(e.dataset_group, []).append(e)

    lines = [
        "# Data gap dataset policy",
        "",
        "Generated from `REGISTRY` in `src/uw_scan/reports/data_gap_healer.py` "
        "(one source of truth). Regenerate with:",
        "",
        "```bash",
        'uv run python -c "from uw_scan.reports.data_gap_healer import '
        "render_dataset_policy_markdown as r; "
        "open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())\"",
        "```",
        "",
        f"**{len(reg)} datasets** across {len(by_group)} groups.",
        "",
    ]
    for group in sorted(by_group):
        lines.append(f"## {group}")
        lines.append("")
        lines.append(
            "| table | audit_mode | provider | granularity | adapter | freq | reason |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for e in sorted(by_group[group], key=lambda x: x.table_name):
            lines.append(
                f"| {e.table_name} | {e.audit_mode} | {e.provider} | "
                f"{e.granularity} | {e.healer_adapter or ''} | "
                f"{e.expected_frequency} | {e.reason or ''} |"
            )
        lines.append("")
    return "\n".join(lines)
