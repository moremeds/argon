"""Nightly data-date freshness monitor (prevention layer for silent freezes).

Computes per-table data-date staleness + scope-aware coverage, persists a daily
snapshot, and WARN-logs any frozen / low-coverage table so the next silent
freeze surfaces the morning it starts. Optionally (DATA_FRESHNESS_AUTOHEAL_ENABLED)
triggers a same-night, single-dataset heal for a frozen table that has a
healer_adapter -- a second chance for a table the 20:00 ET gap-healer left
frozen due to budget exhaustion or a transient failure, NOT a substitute for
that nightly job. A circuit breaker (DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS
consecutive frozen nights) stops retriggering a genuinely unfixable source
(missing credential, licensed data feed) instead of burning budget forever.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from uw_scan.config import Settings
from uw_scan.reports.data_freshness import (
    _REGISTRY_BY_NAME,
    MONITORED_TABLES,
    FreshnessRow,
    compute_freshness,
)
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget
from uw_scan.worker.jobs.data_gap_adapters import run_refresh_adapters as _run_refresh
from uw_scan.worker.jobs.data_gap_healer import (
    _LOCK_KEY as _GAP_HEALER_LOCK_KEY,
)
from uw_scan.worker.jobs.data_gap_healer import _another_run_active, execute_into_run

logger = logging.getLogger(__name__)

# Granularities healed via claimed data_gap_items (execute_into_run). The
# other granularity, run_once/run_once_lookback, has no gap-item concept at
# all -- audit() only ever produces items for strict_* audit modes, so
# execute_into_run() silently claims nothing and does nothing for these
# (macro/FRED/rates/gold + DB rollups). Those go through run_refresh_adapters
# instead, same as the nightly gap-healer job does.
_GAP_ITEM_GRANULARITIES = frozenset({"per_ticker_date", "per_ticker_range"})

LOW_COVERAGE_PCT = 0.5  # ponytail: half the expected scope missing = alert-worthy
AUTOHEAL_LOOKBACK_DAYS = 14  # recent window only -- this is a retry, not a backfill


def _autoheal_frozen_tables(
    repo: Repository,
    settings: Settings,
    today: date,
    frozen_rows: list[FreshnessRow],
    specs: dict | None = None,  # test injection only; None -> real HEAL_SPECS
) -> dict[str, Any]:
    """For each frozen table with a gap-healer adapter, either retrigger a
    scoped heal or trip the circuit breaker. Returns what happened per table
    so it can be logged and surfaced on /api/health."""
    fresh_repo = DataFreshnessRepository(repo.conn, schema=settings.db_schema)
    streaks = fresh_repo.consecutive_frozen_counts(as_of=today)
    gap = DataGapHealerRepository(repo.conn, schema=settings.db_schema)

    healed: list[str] = []
    circuit_broken: list[str] = []
    skipped_no_adapter: list[str] = []
    attempted_no_change: list[str] = []  # heal ran, adapter invoked, still not fixed

    # Same advisory lock key the nightly gap-healer job holds for its whole
    # run. A bare _another_run_active() SELECT is check-then-act -- it can't
    # see a nightly run that starts a moment later, so two execute_into_run
    # callers could both proceed and double-spend the same provider budget
    # in the same window. Taking the lock here makes the two mutually
    # exclusive the same way two nightly-job invocations already are.
    with repo.conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_GAP_HEALER_LOCK_KEY,))
        got_lock = cur.fetchone()[0]
    if not got_lock:
        logger.info("data_freshness autoheal: gap-healer lock held; skipping")
        return {
            "healed": healed,
            "circuit_broken": circuit_broken,
            "skipped_no_adapter": [r.table_name for r in frozen_rows],
        }

    try:
        if _another_run_active(gap):
            logger.info("data_freshness autoheal: a gap-healer run is active; skipping")
            return {
                "healed": healed,
                "circuit_broken": circuit_broken,
                "skipped_no_adapter": [r.table_name for r in frozen_rows],
            }

        for row in frozen_rows:
            entry = _REGISTRY_BY_NAME.get(row.table_name)
            if entry is None or not entry.healer_adapter:
                skipped_no_adapter.append(row.table_name)
                continue

            streak = streaks.get(row.table_name, 0)
            if streak >= settings.data_freshness_autoheal_circuit_breaker_nights:
                circuit_broken.append(row.table_name)
                logger.error(
                    "data_freshness autoheal: %s CIRCUIT BREAKER TRIPPED — frozen "
                    "%d consecutive nights, not retriggering (needs a human: "
                    "credential, license, or code fix)",
                    row.table_name,
                    streak,
                )
                continue

            if entry.granularity in _GAP_ITEM_GRANULARITIES:
                _run_id, outcome, budget, _summaries, _items = execute_into_run(
                    repo,
                    gap,
                    settings,
                    start=today - timedelta(days=AUTOHEAL_LOOKBACK_DAYS),
                    end=today,
                    datasets=[row.table_name],
                    max_uw_calls=settings.data_freshness_autoheal_max_uw_calls,
                    today=today,
                    specs=specs,
                )
                success = outcome.get("healed", 0) > 0
                budget_spent = budget.as_dict()
            else:
                # run_once / run_once_lookback: no gap-item concept, re-run
                # the ingest job directly (same path the nightly job uses).
                ctx = HealContext(
                    repo=repo,
                    gap=gap,
                    schema=settings.db_schema,
                    today=today,
                    budget=RequestBudget(settings.data_freshness_autoheal_max_uw_calls),
                    settings=settings,
                )
                refresh = _run_refresh(
                    ctx,
                    [row.table_name],
                    lookback_days=AUTOHEAL_LOOKBACK_DAYS,
                    specs=specs if specs is not None else HEAL_SPECS,
                )
                outcome = refresh
                success = refresh.get(row.table_name) == "refreshed"
                budget_spent = ctx.budget.as_dict()

            if success:
                healed.append(row.table_name)
            else:
                attempted_no_change.append(row.table_name)
            logger.warning(
                "data_freshness autoheal: retriggered %s (frozen %d nights) "
                "success=%s outcome=%s budget_spent=%s",
                row.table_name,
                streak,
                success,
                outcome,
                budget_spent,
            )
    finally:
        with repo.conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_GAP_HEALER_LOCK_KEY,))

    result: dict[str, Any] = {
        "healed": healed,
        "circuit_broken": circuit_broken,
        "skipped_no_adapter": skipped_no_adapter,
    }
    if attempted_no_change:
        result["attempted_no_change"] = attempted_no_change
    return result


def data_freshness_monitor(
    *, repo: Repository, settings: Settings, today: date
) -> dict[str, Any]:
    active = [c.ticker for c in repo.list_watchlist_cards()]
    rows = compute_freshness(
        repo.conn, settings.db_schema, MONITORED_TABLES, active, today
    )

    frozen_rows: list[FreshnessRow] = []
    for r in rows:
        if r.frozen:
            frozen_rows.append(r)
            logger.warning(
                "data_freshness: %s FROZEN — newest data %s is %s days stale (cov %.0f%%)",
                r.table_name,
                r.max_data_date,
                r.days_stale,
                (r.coverage_pct or 0) * 100,
            )
        elif r.coverage_pct is not None and r.coverage_pct < LOW_COVERAGE_PCT:
            logger.warning(
                "data_freshness: %s LOW COVERAGE — %d/%d tickers (%.0f%%) at newest date %s",
                r.table_name,
                r.covered_count,
                r.expected_count,
                r.coverage_pct * 100,
                r.max_data_date,
            )

    # Autoheal's circuit breaker must count consecutive PRIOR frozen nights,
    # not tonight's -- so it runs before tonight's row is persisted. Doing it
    # after would make consecutive_frozen_counts() see tonight's just-written
    # row on the same connection (read-your-own-writes, same open
    # transaction), tripping the breaker one night earlier than
    # DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS actually says.
    autoheal: dict[str, Any] = {}
    if settings.data_freshness_autoheal_enabled and frozen_rows:
        autoheal = _autoheal_frozen_tables(repo, settings, today, frozen_rows)

    persisted = DataFreshnessRepository(
        repo.conn, schema=settings.db_schema
    ).upsert_snapshot(today, rows)

    summary: dict[str, Any] = {
        "tables": len(rows),
        "frozen": len(frozen_rows),
        "persisted": persisted,
    }
    if autoheal:
        summary["autoheal"] = autoheal
    logger.info(
        "data_freshness_monitor complete tables=%d frozen=%d persisted=%d autoheal=%s",
        summary["tables"],
        summary["frozen"],
        summary["persisted"],
        autoheal or None,
    )
    return summary
