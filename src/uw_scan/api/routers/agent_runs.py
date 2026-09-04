"""Generic ingest and reads for structured agent runs (migration 148).

WHY A TOKEN HERE AND NOWHERE ELSE IN THIS API
----------------------------------------------
Every other route in this service reads, and CORS is permissive on purpose
because the real boundary is the private Tailnet. This one WRITES, and its
failure mode is silent: a bad row does not raise, it publishes a document a
person then reads as a briefing. Unset means disabled, never open.

The `kind` in these paths is an opaque, writer-chosen label. Nothing here
switches on its value, enumerates the legal set, or interprets the stored
document — that knowledge belongs to whichever view renders it.
"""

from __future__ import annotations

import hmac
import logging
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models import (
    AgentRunIndexRow,
    AgentRunIngest,
    AgentRunIngestResult,
    AgentRunResponse,
    AgentRunWeek,
    AgentRunWeekListResponse,
    AgentRunWeekResponse,
)
from uw_scan.storage.agent_runs import AgentRunsRepository, iso_week_key
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

router = APIRouter(tags=["agent-runs"])


def require_ingest_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    configured = settings.agent_ingest_token
    if configured is None:
        raise HTTPException(
            503,
            "agent-run ingest is disabled: UW_SCAN_AGENT_INGEST_TOKEN is not set",
        )
    presented = authorization[7:] if (authorization or "").startswith("Bearer ") else ""
    # Constant time, and it runs even when nothing was presented, so a missing
    # header and a wrong token take the same path.
    if not hmac.compare_digest(presented, configured.get_secret_value()):
        raise HTTPException(401, "invalid or missing ingest token")


def _store(repo: Repository) -> AgentRunsRepository:
    return AgentRunsRepository(repo.conn, schema=repo._schema)


@router.post(
    "/agent-runs",
    response_model=AgentRunIngestResult,
    dependencies=[Depends(require_ingest_token)],
)
def ingest_agent_run(
    payload: AgentRunIngest,
    response: Response,
    repo: Repository = Depends(get_repo),
) -> AgentRunIngestResult:
    """201 on a new run, 200 when this run_id was already stored."""
    week_key = payload.week_key or iso_week_key(payload.run_day)
    version_no, created = _store(repo).ingest(
        tenant=payload.tenant,
        kind=payload.kind,
        run_day=payload.run_day,
        run_id=payload.run_id,
        code_sha=payload.code_sha,
        schema_version=payload.schema_version,
        outcome=payload.outcome,
        headline=payload.headline,
        view=payload.view,
        report=payload.report,
        week_key=week_key,
    )
    response.status_code = 201 if created else 200
    return AgentRunIngestResult(
        tenant=payload.tenant,
        kind=payload.kind,
        run_day=payload.run_day,
        week_key=week_key,
        version_no=version_no,
        created=created,
    )


@router.get("/agent-runs/weeks", response_model=AgentRunWeekListResponse)
def list_agent_run_weeks(
    tenant: str = Query(...),
    limit: int = Query(52, ge=1, le=520),
    repo: Repository = Depends(get_repo),
) -> AgentRunWeekListResponse:
    """Only weeks that have a run: a week with no rows is not a destination."""
    rows = _store(repo).weeks(tenant=tenant, limit=limit)
    return AgentRunWeekListResponse(
        tenant=tenant,
        weeks=[AgentRunWeek.model_validate(r) for r in rows],
    )


@router.get("/agent-runs/week/{week_key}", response_model=AgentRunWeekResponse)
def get_agent_run_week(
    week_key: str,
    tenant: str = Query(...),
    repo: Repository = Depends(get_repo),
) -> AgentRunWeekResponse:
    rows = _store(repo).week(tenant=tenant, week_key=week_key)
    return AgentRunWeekResponse(
        tenant=tenant,
        week_key=week_key,
        runs=[AgentRunIndexRow.model_validate(r) for r in rows],
    )


@router.get("/agent-runs/latest", response_model=AgentRunResponse)
def get_latest_agent_run(
    tenant: str = Query(...),
    kind: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> AgentRunResponse:
    row = _store(repo).latest(tenant=tenant, kind=kind)
    if row is None:
        raise HTTPException(
            404,
            f"no run recorded for tenant {tenant!r}"
            + (f", kind {kind!r}" if kind else ""),
        )
    return AgentRunResponse(tenant=tenant, **row)


@router.get("/agent-runs/run/{kind}/{run_day}", response_model=AgentRunResponse)
def get_agent_run(
    kind: str,
    run_day: date,
    tenant: str = Query(...),
    version: int | None = Query(default=None, ge=1),
    repo: Repository = Depends(get_repo),
) -> AgentRunResponse:
    row = _store(repo).run(
        tenant=tenant, kind=kind, run_day=run_day, version_no=version
    )
    if row is None:
        raise HTTPException(
            404,
            f"no {kind!r} run recorded for tenant {tenant!r} on {run_day.isoformat()}",
        )
    return AgentRunResponse(tenant=tenant, **row)
