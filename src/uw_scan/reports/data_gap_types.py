"""Shared types, constants, and seed data for the data-gap audit.

These were split out of ``data_gap_healer``: ``data_gap_healer`` keeps the
scanner/spine/audit code, ``data_gap_registry`` builds ``REGISTRY`` from
per-domain part files, and both import from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

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
# Audit modes that are existence-only BY DESIGN: there is no time series to
# backfill, so "no adapter" is the correct answer rather than an undocumented
# refusal. Everything outside this set must carry either a heal adapter or a
# dated, measured reason — see tests/unit/reports/test_full_coverage.py.
BY_DESIGN_AUDIT_MODES: tuple[str, ...] = (
    "excluded",
    "provenance",
    "operational_state",
    "research_artifact",
)
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
    # When the refusal/claim in `reason` was actually PROBED against the
    # provider. None = untested assumption, not a measurement. The blanket
    # "no auto-backfill" reason proved false for 13 datasets in round 1.
    reason_verified_on: date | None = None


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


def entries(
    tables: list[str], group: str, mode: AuditMode, **kw
) -> list[DatasetRegistryEntry]:
    return [DatasetRegistryEntry(t, group, mode, **kw) for t in tables]
