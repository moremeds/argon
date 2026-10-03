"""/api/stock/{ticker}/volatility/series — see spec 2026-05-13 §5.1."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from uw_scan.api.deps import get_repo
from uw_scan.models import VolatilitySeriesResponse
from uw_scan.reports.volatility_series import (
    assemble_volatility_series,
    public_backfill_status,
)
from uw_scan.storage.repository import Repository

router = APIRouter()

HISTORY_THRESHOLD_DAYS = 90


@router.get(
    "/stock/{ticker}/volatility/series",
    response_model=VolatilitySeriesResponse,
)
def get_volatility_series(
    ticker: str,
    repo: Repository = Depends(get_repo),
) -> VolatilitySeriesResponse:
    t = ticker.upper()
    history_fresh = repo.count_realized_vol_history(t, days=HISTORY_THRESHOLD_DAYS)
    persisted = repo.get_volatility_backfill_status(t)
    persisted_status = persisted["status"] if persisted else None

    status = "ready"
    if history_fresh < HISTORY_THRESHOLD_DAYS:
        if persisted_status in ("queued", "running", "failed"):
            status = public_backfill_status(persisted_status)
        else:
            # Durable enqueue (I-22): the uw-0 worker's volatility_backfill_tick
            # runs it under the research UW budget, and it survives an API
            # restart. The ticker PK makes concurrent GETs one row. A stuck
            # 'running' row is requeued by the worker, not here.
            repo.enqueue_volatility_backfill(t)
            status = "running"
    # Read path is otherwise read-only: derived vrp_daily/stock_analytics rows
    # are written by nightly_vol_analytics_rollup, not by whoever opens the page
    # (one GET was issuing ~594 upserts + a commit).
    return assemble_volatility_series(
        ticker=t, repo=repo, backfill_status=status, persist_derived=False
    )
