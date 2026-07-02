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
from uw_scan.worker.jobs.data_gap_healer import _another_run_active, execute_into_run

logger = logging.getLogger(__name__)

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
    streaks = fresh_repo.consecutive_frozen_counts()
    gap = DataGapHealerRepository(repo.conn, schema=settings.db_schema)

    healed: list[str] = []
    circuit_broken: list[str] = []
    skipped_no_adapter: list[str] = []

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
        healed.append(row.table_name)
        logger.warning(
            "data_freshness autoheal: retriggered %s (frozen %d nights) "
            "outcome=%s budget_spent=%s",
            row.table_name,
            streak,
            outcome,
            budget.as_dict(),
        )

    return {
        "healed": healed,
        "circuit_broken": circuit_broken,
        "skipped_no_adapter": skipped_no_adapter,
    }


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

    persisted = DataFreshnessRepository(
        repo.conn, schema=settings.db_schema
    ).upsert_snapshot(today, rows)

    autoheal: dict[str, Any] = {}
    if settings.data_freshness_autoheal_enabled and frozen_rows:
        autoheal = _autoheal_frozen_tables(repo, settings, today, frozen_rows)

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
