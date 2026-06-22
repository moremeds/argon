"""Nightly VRP research-expansion compute (items 1, 2, 4, 5).

Orchestrates the five research runs over the warm store: RV validation, sector
drilldown, multi-horizon harvest, directional, ΔVRP-reversion. Pure compute
(no external calls); idempotent (each run is full-rewrite). Each sub-run is
isolated in try/except + rollback so one failing axis does not sink the rest or
leak a partial transaction into the next run.
"""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.reports.vrp_directional import (
    run_vrp_directional,
    run_vrp_dvrp_reversion,
)
from uw_scan.reports.vrp_harvest_axes import (
    run_vrp_harvest_by_sector,
    run_vrp_harvest_multihorizon,
)
from uw_scan.reports.vrp_rv_validation import run_vrp_rv_validation
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def vrp_research_refresh(*, repo: Repository) -> dict[str, Any]:
    results: dict[str, Any] = {}
    runs = [
        ("rv_validation", run_vrp_rv_validation),
        ("harvest_by_sector", run_vrp_harvest_by_sector),
        ("harvest_multihorizon", run_vrp_harvest_multihorizon),
        ("directional", run_vrp_directional),
        ("dvrp_reversion", run_vrp_dvrp_reversion),
    ]
    for name, fn in runs:
        try:
            results[name] = fn(repo=repo)
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()  # discard the failed run's partial txn
            log.exception("vrp_research_refresh: %s failed: %s", name, repr(exc))
            results[name] = {"error": repr(exc)}
    log.info("vrp_research_refresh done: %s", results)
    return results
