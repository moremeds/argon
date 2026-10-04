"""Fundamentals derived products, taxonomy, and earnings spine.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


FUNDAMENTALS_DERIVED: list[DatasetRegistryEntry] = [
    DatasetRegistryEntry(
        "chain_membership",
        "fundamentals",
        # `provenance`. Validity intervals over a versioned taxonomy; a row
        # appears when a placement CHANGES, so freshness would measure how
        # often the taxonomy is edited.
        "provenance",
        date_col="valid_from",
        ticker_col="ticker",
        expected_frequency="none",
        provider="none",
        granularity="none",
        healer_adapter=None,
        source_system="argon",
        retention_days=None,
        reason=(
            "versioned chain membership (migration 139). Seeded by "
            "worker/jobs/research_taxonomy_seed at zero provider spend; a "
            "reseed is idempotent (an unchanged placement opens no interval)."
        ),
        reason_verified_on=date(2026, 8, 25),
    ),
    DatasetRegistryEntry(
        "company_exposure",
        "fundamentals",
        "provenance",
        date_col="recorded_at",
        ticker_col="ticker",
        expected_frequency="none",
        provider="none",
        granularity="none",
        healer_adapter=None,
        source_system="derived",
        retention_days=None,
        reason=(
            "economic chain exposure (migration 140). Derived from "
            "revenue_breakdown_obs through published alias rules, or asserted "
            "with no magnitude — a CHECK forbids a number on an asserted row. "
            "Rebuilt by re-running the seed job; nothing to heal from a "
            "provider."
        ),
        reason_verified_on=date(2026, 8, 25),
    ),
    DatasetRegistryEntry(
        "chain_segment_alias",
        "fundamentals",
        "provenance",
        date_col="created_at",
        ticker_col=None,
        expected_frequency="none",
        provider="none",
        granularity="none",
        healer_adapter=None,
        source_system="argon",
        retention_days=None,
        reason=(
            "published segment->chain mapping rules (migration 141). The "
            "recorded judgement half of a derived exposure, so the "
            "attribution is auditable rather than baked into a magnitude."
        ),
        reason_verified_on=date(2026, 8, 25),
    ),
    DatasetRegistryEntry(
        "research_taxonomy_versions",
        "fundamentals",
        "provenance",
        date_col="created_at",
        ticker_col=None,
        expected_frequency="none",
        provider="none",
        granularity="none",
        healer_adapter=None,
        source_system="argon",
        retention_days=None,
        reason=(
            "taxonomy version catalogue (migration 139). One row per "
            "published taxonomy; nothing to heal."
        ),
        reason_verified_on=date(2026, 8, 25),
    ),
    DatasetRegistryEntry(
        "revenue_breakdown_obs",
        "fundamentals",
        # freshness_only for the same reason as fundamental_statement_obs:
        # the grain is (ticker x fiscal QUARTER), not (ticker x SESSION), so
        # a strict audit would invent a gap of roughly the session-to-quarter
        # ratio that no filing will ever fill.
        "freshness_only",
        date_col="report_date",
        ticker_col="ticker",
        # A breakdown row appears when a filing appears.
        expected_frequency="event",
        provider="uw",
        granularity="none",
        healer_adapter=None,
        source_system="uw",
        retention_days=None,
        reason=(
            "revenue breakdown by XBRL axis over the fundamental universe. "
            "Deliberately NOT wired to the healer: this is a provider "
            "INGEST, and its own capture job is the only writer. Heal by "
            "re-running worker/jobs/fundamental_concentration_capture "
            "(insert-or-touch by content hash, safe to repeat) as a "
            "budgeted operator action, not on the nightly cron. Note the "
            "provider window may roll: a period that has aged out cannot be "
            "healed at all, which is why capture runs monthly rather than "
            "quarterly."
        ),
        reason_verified_on=date(2026, 8, 18),
    ),
    DatasetRegistryEntry(
        "fundamental_obs_violations",
        "fundamentals",
        # A verdict about an immutable payload. It is never backfilled on its
        # own: it is re-derived when its parent observation is re-ingested.
        "provenance",
        date_col="detected_at",
        ticker_col=None,
        expected_frequency="event",
        provider="none",
        granularity="none",
        source_system="derived",
    ),
    DatasetRegistryEntry(
        "fundamental_scores",
        "fundamentals",
        # freshness_only for the same reason as the observations it derives
        # from: the grain is (ticker x knowledge QUARTER) over a universe that
        # is not the watchlist, so a session-based strict denominator would
        # invent a gap no filing will ever fill.
        "freshness_only",
        date_col="as_of",
        ticker_col="ticker",
        expected_frequency="event",
        provider="db",
        # Healing is re-running the scoring job, which is idempotent on
        # (ticker, as_of, engine_version, inputs_hash) and costs zero API
        # calls — it reads the tier-1 panel, never a provider. run_once (not
        # per_ticker_*) because this is freshness_only, and only the
        # run_once* channel dispatches for a non-strict dataset.
        granularity="run_once",
        healer_adapter="fundamental_refresh",
        source_system="derived",
        reason=(
            "derived from fundamental_statement_obs; worker/jobs/"
            "fundamental_refresh re-runs routing -> scoring -> anchors at "
            "zero provider spend. The old reason named this job and then "
            "declined to wire it."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    DatasetRegistryEntry(
        "valuation_anchors",
        "fundamentals",
        # freshness_only, same reasoning as fundamental_scores: the grain is
        # (ticker x knowledge QUARTER) over a universe that is not the
        # watchlist, so a session-based denominator would invent gaps that no
        # filing will ever fill.
        "freshness_only",
        date_col="as_of",
        ticker_col="ticker",
        expected_frequency="event",
        provider="db",
        granularity="run_once",
        healer_adapter="fundamental_refresh",
        source_system="derived",
        reason=(
            "derived from fundamental_statement_obs + fundamental_company_type; "
            "healed by the same worker/jobs/fundamental_refresh chain as "
            "fundamental_scores (routing runs FIRST because anchors read "
            "company_type). Zero provider spend."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    DatasetRegistryEntry(
        "fundamental_company_type",
        "fundamentals",
        "excluded",
        date_col="updated_at",
        ticker_col="ticker",
        expected_frequency="none",
        reason=(
            "hand-maintainable routing table, not a time series — a missing "
            "row means the name is unrouted, which the card states explicitly"
        ),
    ),
    DatasetRegistryEntry(
        "fundamental_method_versions",
        "fundamentals",
        "excluded",
        date_col="created_at",
        ticker_col=None,
        expected_frequency="none",
        reason="immutable method registry, not a time series",
    ),
    DatasetRegistryEntry(
        "fundamental_method_params",
        "fundamentals",
        "excluded",
        date_col=None,
        ticker_col=None,
        expected_frequency="none",
        reason="immutable parameter rows keyed by engine_version",
    ),
    DatasetRegistryEntry(
        "fundamental_method_state",
        "fundamentals",
        "excluded",
        date_col="activated_at",
        ticker_col=None,
        expected_frequency="none",
        reason="singleton pointer to the active method version",
    ),
    DatasetRegistryEntry(
        "fundamental_universe",
        "fundamentals",
        "excluded",
        date_col=None,
        ticker_col="ticker",
        expected_frequency="none",
        provider="none",
        granularity="none",
        reason=(
            "seeded membership list, not a time series; "
            "scripts/seed_fundamental_universe.py is the source of truth"
        ),
    ),
    # Data spine, tasks 4/6/7 (spec §5-i/ii/iii). `freshness_only`, not
    # `strict_ticker_date`, for all three: the grain is (ticker x KNOWN
    # PRINT), and a ticker with no upcoming/recent earnings correctly has
    # no row for it -- a strict session denominator would invent a gap no
    # print will ever fill.
    DatasetRegistryEntry(
        "earnings_calendar",
        "fundamentals",
        "freshness_only",
        date_col="report_date",
        ticker_col="ticker",
        expected_frequency="event",
        provider="uw",
        # No adapter: the daily calendar-driven ingest (fundamental_ingest_daily,
        # 3-day lookback) and the monthly full-tier sweep already re-fetch and
        # upsert the classified calendar every time they run, so a missed print
        # self-heals on the next scheduled run at zero incremental UW cost (the
        # calendar fetch rides the existing statement-ingest call, per
        # fundamental_statement_obs's own entry above).
        granularity="none",
        healer_adapter=None,
        source_system="uw",
        retention_days=None,
        reason=(
            "forward-accruing print calendar (migration 144), the spine "
            "earnings_reactions and implied_move_daily below both read. Session "
            "NULL for the ~2% UW leaves unclassified is a real third state, not "
            "a gap."
        ),
        reason_verified_on=date(2026, 8, 28),
    ),
    DatasetRegistryEntry(
        "earnings_reactions",
        "fundamentals",
        "freshness_only",
        date_col="report_date",
        ticker_col="ticker",
        expected_frequency="event",
        # Pure warm-store derivation (earnings_calendar x daily_ohlc) --
        # zero UW/IB spend, unlike earnings_calendar's own provider="uw".
        provider="db",
        # No adapter needed: earnings_reactions_compute is ALREADY
        # self-healing within its own 10-day lookback. It SKIPS -- never
        # nulls -- a print whose before/after close is not yet in
        # daily_ohlc, and the calendar row persists, so the identical
        # print is retried on every subsequent nightly run until the
        # missing close lands (`skipped_incomplete` counter). Beyond the
        # 10-day window (e.g. a corporate-action-driven OHLC hole),
        # scripts/backfill/earnings_reactions_backfill.py is the operator
        # path -- an existing, dry-run-by-default script, not new wiring.
        granularity="none",
        healer_adapter=None,
        source_system="derived",
        retention_days=None,
        reason=(
            "per-print reaction (migration 145), computed from "
            "earnings_calendar x daily_ohlc. Deliberately re-attemptable: a "
            "pending print is ABSENT here, never null, which is what makes "
            "'retry every night until the price lands' safe."
        ),
        reason_verified_on=date(2026, 8, 28),
    ),
    DatasetRegistryEntry(
        "implied_move_daily",
        "fundamentals",
        "freshness_only",
        date_col="market_date",
        ticker_col="ticker",
        expected_frequency="event",
        # Reads option_surface_grid_daily, already captured by that job's
        # own UW spend -- this snapshot itself makes zero new UW calls.
        provider="db",
        # No adapter: per the migration's own table comment, "ABSENCE OF A
        # ROW IS THE COVERAGE STATEMENT" -- a ticker with a calendar print
        # but no covering expiry/strike on TONIGHT's option surface grid
        # gets no row, by design, forever (never a stale carry-forward). A
        # missed night can only be re-derived if that night's
        # option_surface_grid_daily rows still exist; if the grid was
        # never captured, there is nothing for any adapter to read.
        granularity="none",
        healer_adapter=None,
        source_system="derived",
        retention_days=None,
        reason=(
            "nightly implied-move snapshot (migration 146) for names with a "
            "known print inside the 21-day lookahead. One row per "
            "(ticker, market_date); a night with no imminent print for a "
            "ticker correctly writes none."
        ),
        reason_verified_on=date(2026, 8, 28),
    ),
    DatasetRegistryEntry(
        "fundamentals_desk_rollup",
        "fundamentals",
        "freshness_only",
        date_col="period_end",
        ticker_col="ticker",
        # FISCAL periods, not sessions: a name reports roughly quarterly and
        # the gap between two rows is the company's calendar, never a
        # missed run.
        expected_frequency="event",
        # Pure re-derivation of fundamental_statement_obs already on hand --
        # zero UW/IB spend.
        provider="db",
        # No adapter: the job is a full recompute over every ticker, so a
        # missed night heals itself on the next run rather than needing a
        # per-date backfill. `scripts/backfill/fundamentals_desk_rollup_run.py`
        # is the manual trigger.
        granularity="none",
        healer_adapter=None,
        source_system="derived",
        retention_days=None,
        reason=(
            "nightly rollup (migration 147) of per-name revenue YoY and "
            "gross margin, one row per (ticker, period_end). Absence of a "
            "period is the coverage statement: a name whose filings do not "
            "support a four-quarters-back comparison correctly gets no row, "
            "and `knowledge_date_known` records whether that row's "
            "knowledge date is a real filing date or the period-end "
            "estimate."
        ),
        reason_verified_on=date(2026, 8, 28),
    ),
]
