"""/api/health — reports DB up, scheduler lag, last successful full scan."""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

router = APIRouter()


class HealthResponse(BaseModel):
    ok: bool
    db: str
    scheduler_lag_seconds: float | None = None
    last_full_scan_at: datetime | None = None
    reason: str | None = None


def _full_scan_interval_seconds(cron_expr: str, tz: str) -> float:
    """Two consecutive fires from an in-RTH anchor measure the typical gap.

    Anchored at Tue 10:00 UTC (≈ 06:00 ET) so the cron walks into RTH and
    yields the in-session interval (the threshold we actually care about);
    after-hours gaps would inflate the threshold and mask outages.
    """
    trig = CronTrigger.from_crontab(cron_expr, timezone=tz)
    anchor = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    a = trig.get_next_fire_time(None, anchor)
    if a is None:
        return 3600.0
    b = trig.get_next_fire_time(a, a)
    return (b - a).total_seconds() if b else 3600.0


@router.get("/health", response_model=HealthResponse)
def health(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    db_status = "up"
    try:
        with repo.conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as e:  # noqa: BLE001
        return HealthResponse(
            ok=False,
            db=f"down: {e!r}",
            reason="database unreachable",
        )

    last_scan = repo.get_last_full_scan_finished_at()
    if last_scan is None:
        return HealthResponse(
            ok=False,
            db=db_status,
            reason="no successful full scan yet",
        )

    lag = (datetime.now(timezone.utc) - last_scan).total_seconds()
    threshold = 2.0 * _full_scan_interval_seconds(
        settings.full_scan_cron, settings.rth_tz
    )
    if lag > threshold:
        return HealthResponse(
            ok=False,
            db=db_status,
            scheduler_lag_seconds=lag,
            last_full_scan_at=last_scan,
            reason=f"scheduler lag {lag:.0f}s exceeds 2x interval ({threshold:.0f}s)",
        )

    return HealthResponse(
        ok=True,
        db=db_status,
        scheduler_lag_seconds=lag,
        last_full_scan_at=last_scan,
    )
