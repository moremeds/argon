"""US rates mirror API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.models import RatesSnapshotResponse, RatesSourceFreshness
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/rates", tags=["rates"])
SNAPSHOT_STALE_AFTER = timedelta(hours=36)


@router.get("/snapshot", response_model=RatesSnapshotResponse)
def rates_snapshot(repo: Repository = Depends(get_repo)) -> RatesSnapshotResponse:
    row = repo.fetch_latest_rates_snapshot()
    if row is None:
        raise HTTPException(status_code=404, detail="rates snapshot not computed")
    snapshot = RatesSnapshotResponse.model_validate(row["payload"])
    return _mark_stale_snapshot_sources(snapshot, now=datetime.now(UTC))


def _mark_stale_snapshot_sources(
    snapshot: RatesSnapshotResponse, *, now: datetime
) -> RatesSnapshotResponse:
    computed_at = snapshot.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=UTC)
    if now - computed_at <= SNAPSHOT_STALE_AFTER:
        return snapshot

    stale_sources = [
        RatesSourceFreshness(
            id=source.id,
            label=source.label,
            latest_obs_date=source.latest_obs_date,
            last_seen_at=source.last_seen_at,
            status="stale" if source.status == "ok" else source.status,
        )
        for source in snapshot.source_freshness
    ]
    synthesis = snapshot.synthesis.model_copy(
        update={
            "risks": [
                *snapshot.synthesis.risks,
                "Rates snapshot is stale because the scheduled FRED refresh has not completed within the expected window.",
            ]
        }
    )
    return snapshot.model_copy(
        update={"source_freshness": stale_sources, "synthesis": synthesis}
    )
