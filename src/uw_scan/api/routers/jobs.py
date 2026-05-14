"""POST /api/watchlist/{ticker}/rescan + GET /api/jobs/{job_id}."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from uw_scan.api.deps import get_repo
from uw_scan.api.schemas import JobStatus
from uw_scan.storage.repository import Repository

router = APIRouter()


class RescanAllRequest(BaseModel):
    confirmed: bool = False


def _to_status(job) -> JobStatus:
    return JobStatus(
        job_id=str(job.id),
        status=job.status,
        run_id=job.run_id,
        error=job.error,
        requested_at=job.requested_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/watchlist/{ticker}/rescan", status_code=202, response_model=JobStatus)
def enqueue_rescan(ticker: str, repo: Repository = Depends(get_repo)) -> JobStatus:
    job_id = repo.enqueue_rescan_job(ticker.upper())
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=500, detail="job not persisted")
    return _to_status(job)


@router.post("/watchlist/rescan-all", status_code=202, response_model=list[JobStatus])
def enqueue_rescan_all(
    payload: RescanAllRequest | None = None,
    repo: Repository = Depends(get_repo),
) -> list[JobStatus]:
    """Enqueue a rescan job for every active watchlist ticker."""
    if payload is None or not payload.confirmed:
        raise HTTPException(
            status_code=400, detail="rescan-all requires explicit confirmation"
        )
    out: list[JobStatus] = []
    for row in repo.list_active_watchlist():
        job_id = repo.enqueue_rescan_job(row.ticker)
        job = repo.get_job(job_id)
        if job is not None:
            out.append(_to_status(job))
    return out


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str, repo: Repository = Depends(get_repo)) -> JobStatus:
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _to_status(job)
