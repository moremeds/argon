"""/api/health — reports DB up, scheduler lag, last successful full scan.

The response is assembled by ``reports/health_assembly.build_health``; this
router parses the query params, passes the clock and the two ``worker``
functions the assembly needs, and maps ``UnknownRecordTables`` to a 400."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models.health import HealthResponse
from uw_scan.reports.health_assembly import HealthSource, build_health
from uw_scan.reports.health_blocks import UnknownRecordTables
from uw_scan.storage.repository import Repository
from uw_scan.worker.schedule_expectations import expected_market_cron_fires_between

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    source: Annotated[HealthSource, Query()] = "uw",
    record_window_hours: Annotated[float | None, Query(ge=0.1, le=168)] = None,
    record_min_coverage: Annotated[float, Query(ge=0.0, le=1.0)] = 0.9,
    record_tables: Annotated[str | None, Query()] = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    # Imported per request (as before the move) so a monkeypatched
    # `market_session.current_market_date` is the one passed in.
    from uw_scan.worker.market_session import current_market_date

    try:
        return build_health(
            repo,
            settings,
            clock=lambda: datetime.now(timezone.utc),
            source=source,
            record_window_hours=record_window_hours,
            record_min_coverage=record_min_coverage,
            record_tables=record_tables,
            expected_fires=expected_market_cron_fires_between,
            market_date_fn=current_market_date,
        )
    except UnknownRecordTables as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
