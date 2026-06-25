"""Nightly data-date freshness monitor (prevention layer for silent freezes).

Computes per-table data-date staleness + scope-aware coverage, persists a daily
snapshot, and WARN-logs any frozen / low-coverage table so the next silent
freeze surfaces the morning it starts.
"""

from __future__ import annotations

import logging
from datetime import date

from uw_scan.config import Settings
from uw_scan.reports.data_freshness import MONITORED_TABLES, compute_freshness
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

LOW_COVERAGE_PCT = 0.5  # ponytail: half the expected scope missing = alert-worthy


def data_freshness_monitor(
    *, repo: Repository, settings: Settings, today: date
) -> dict[str, int]:
    active = [c.ticker for c in repo.list_watchlist_cards()]
    rows = compute_freshness(
        repo.conn, settings.db_schema, MONITORED_TABLES, active, today
    )

    frozen = 0
    for r in rows:
        if r.frozen:
            frozen += 1
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
    summary = {"tables": len(rows), "frozen": frozen, "persisted": persisted}
    logger.info(
        "data_freshness_monitor complete tables=%d frozen=%d persisted=%d",
        summary["tables"],
        summary["frozen"],
        summary["persisted"],
    )
    return summary
