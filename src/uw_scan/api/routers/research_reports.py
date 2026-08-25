"""Versioned research reports (M7). Read, plus one deliberate assemble.

The read always carries the delta. A surface that could render a report without
"what changed since last time" would be the un-versioned document this whole
milestone replaces — same title, same shape, quietly different meaning.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.fundamentals.report_delta import report_delta
from uw_scan.models import (
    ReportDeltaModel,
    ReportListResponse,
    ReportResponse,
    ResearchReportModel,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.research_reports import ResearchReportsRepository

log = logging.getLogger(__name__)

router = APIRouter(tags=["research-reports"])

_KEY_PREFIX = {"company": "company", "chain": "chain"}


def _report_key(report_type: str, key: str) -> str:
    if report_type not in _KEY_PREFIX:
        raise HTTPException(
            404, f"unknown report type {report_type!r}; expected company or chain"
        )
    return f"{report_type}:{key.upper() if report_type == 'company' else key}"


def _as_model(row: dict) -> ResearchReportModel:
    return ResearchReportModel.model_validate(
        {
            **row,
            "manifest": row["manifest_jsonb"],
            "blocks": [
                {**b, "payload": b["payload_jsonb"], "evidence": b["evidence_jsonb"]}
                for b in row.get("blocks") or []
            ],
        }
    )


def _delta_model(previous: dict | None, current: dict) -> ReportDeltaModel:
    d = report_delta(previous, current)
    return ReportDeltaModel.model_validate(
        {
            "is_first_version": d["is_first_version"],
            "manifest": d["manifest"],
            "added": d["blocks"]["added"],
            "removed": d["blocks"]["removed"],
            "moved": d["blocks"]["moved"],
            "summary": d["summary"],
        }
    )


@router.get("/research/reports", response_model=ReportListResponse)
def list_reports(
    limit: int = Query(default=25, ge=1, le=200),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ReportListResponse:
    """The newest version of each report key."""
    reports = ResearchReportsRepository(repo.conn, schema=settings.db_schema)
    return ReportListResponse(reports=reports.recent(limit=limit))


@router.get("/research/reports/{report_type}/{key}", response_model=ReportResponse)
def get_report(
    report_type: str,
    key: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ReportResponse:
    """Latest version of one report, its delta, and its version history."""
    reports = ResearchReportsRepository(repo.conn, schema=settings.db_schema)
    report_key = _report_key(report_type, key)
    current = reports.latest(report_key)
    if current is None:
        # Distinct from no_coverage: nobody has asked for this report yet, which
        # says nothing at all about whether Argon could build it.
        return ReportResponse(
            state="no_report",
            reason=(
                f"no report has been assembled for {report_key}; POST this path "
                "to assemble one"
            ),
        )
    previous = (
        reports.version(report_key, current["version_no"] - 1)
        if current["version_no"] > 1
        else None
    )
    return ReportResponse(
        state="ok",
        report=_as_model(current),
        delta=_delta_model(previous, current),
        versions=reports.versions(report_key),
    )


@router.get(
    "/research/reports/{report_type}/{key}/versions/{version_no}",
    response_model=ReportResponse,
)
def get_report_version(
    report_type: str,
    key: str,
    version_no: int,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ReportResponse:
    """One frozen version, exactly as it was published.

    This is the replay path. It reads stored blocks rather than re-assembling,
    because re-assembly under today's data is a DIFFERENT answer wearing an old
    version number.
    """
    reports = ResearchReportsRepository(repo.conn, schema=settings.db_schema)
    report_key = _report_key(report_type, key)
    row = reports.version(report_key, version_no)
    if row is None:
        raise HTTPException(404, f"{report_key} has no version {version_no}")
    previous = (
        reports.version(report_key, version_no - 1) if version_no > 1 else None
    )
    return ReportResponse(
        state="ok",
        report=_as_model(row),
        delta=_delta_model(previous, row),
        versions=reports.versions(report_key),
    )


@router.post("/research/reports/{report_type}/{key}", response_model=ReportResponse)
def assemble_report(
    report_type: str,
    key: str,
    as_of: date | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ReportResponse:
    """Assemble and publish the next version. Deterministic — no model, no network.

    Republishing unchanged content is a no-op that returns the existing version
    with an empty delta, so a double-click cannot manufacture history.
    """
    # ponytail: a deliberate write on a read router, same shape as
    # /technicals/refresh — user-triggered, idempotent by content hash, and
    # bounded to warm-store reads. Promote to a /jobs kind if it ever needs to
    # be async or batched over a universe.
    from uw_scan.worker.jobs.research_report_assemble import (
        assemble_chain_report,
        assemble_company_report,
    )

    report_key = _report_key(report_type, key)
    try:
        if report_type == "company":
            assemble_company_report(
                repo.conn, key, schema=settings.db_schema, as_of=as_of
            )
        else:
            assemble_chain_report(
                repo.conn, key, schema=settings.db_schema, as_of=as_of
            )
    except ValueError as exc:
        # A refused assembly is a data state, not a transport failure: the
        # caller asked a well-formed question Argon declined to answer.
        log.warning("assemble_report %s refused: %r", report_key, exc)
        return ReportResponse(state="failed_run", reason=str(exc))

    return get_report(report_type, key, repo=repo, settings=settings)
