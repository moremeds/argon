"""VRP harvest markout job (Spec B) — thin scheduler wrapper."""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.reports.vrp_markout import run_vrp_markout
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def vrp_markout_refresh(*, repo: Repository) -> dict[str, Any]:
    """Re-score the realized VRP harvest per bucket and (re)write
    vrp_harvest_verdicts. Pure compute over the warm store; idempotent."""
    counts = run_vrp_markout(repo=repo)
    log.info(
        "vrp_markout_refresh: %d buckets over %d tickers",
        counts.get("buckets_written", 0),
        counts.get("tickers", 0),
    )
    return counts
