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

_KEY_PREFIX = {"company": "company", "chain": "chain", "comparison": "comparison"}


#: A comparison's key is its SORTED ticker set, so `NVDA,AMD` and `AMD,NVDA` are
#: one report with two versions rather than two reports with one each.
def _comparison_key(raw: str) -> str:
    symbols = sorted({t.strip().upper() for t in raw.split(",") if t.strip()})
    if not symbols:
        raise HTTPException(400, "a comparison needs at least one ticker")
    return "-".join(symbols)


def _report_key(report_type: str, key: str) -> str:
    if report_type not in _KEY_PREFIX:
        raise HTTPException(
            404,
            f"unknown report type {report_type!r}; expected one of "
            f"{sorted(_KEY_PREFIX)}",
        )
    if report_type == "comparison":
        return f"comparison:{_comparison_key(key)}"
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


# `key` uses the `:path` converter because 20 of the desk's 38 chain names
# contain a slash (`Networking/Optical`, `Semi-Logic/ASIC`, …) and a plain
# `{key}` segment 404s on one: uvicorn unquotes `%2F` to a real `/` before
# Starlette routes the request, so the slash arrives as an extra path segment
# that a single-segment converter cannot match.
#
# REGISTRATION ORDER BELOW IS LOAD-BEARING AND FAILS SILENTLY IF REVERSED.
# `{key:path}` is greedy and unanchored at the end of the URL, so if the plain
# route (`.../{key}`) is registered before the `/versions/{version_no}` route,
# it swallows `versions/3` into `key` and matches FIRST — `.../versions/3`
# then returns 200 from the WRONG route with a corrupted key
# (`key='Networking/Optical/versions/3'`) instead of ever reaching the version
# route or 404ing. Not a crash: a wrong answer that looks like a right one.
# Do not "tidy" these back into alphabetical/declaration order.
@router.get(
    "/research/reports/{report_type}/{key:path}/versions/{version_no}",
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
    previous = reports.version(report_key, version_no - 1) if version_no > 1 else None
    return ReportResponse(
        state="ok",
        report=_as_model(row),
        delta=_delta_model(previous, row),
        versions=reports.versions(report_key),
    )


@router.get("/research/reports/{report_type}/{key:path}", response_model=ReportResponse)
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


#: Same `:path` reason as the GET pair above — a slash-bearing chain name must
#: reach `assemble_chain_report` intact, or the desk that is about to assemble
#: the first-ever chain report would 404 on exactly the names this fix exists
#: for. No ordering hazard here: POST and GET occupy separate method spaces, so
#: this route never competes with the GET routes above for a match.
@router.post(
    "/research/reports/{report_type}/{key:path}", response_model=ReportResponse
)
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
        assemble_comparison_report,
    )

    report_key = _report_key(report_type, key)
    try:
        if report_type == "company":
            assemble_company_report(
                repo.conn, key, schema=settings.db_schema, as_of=as_of
            )
        elif report_type == "comparison":
            assemble_comparison_report(
                repo.conn,
                key.split(","),
                schema=settings.db_schema,
                as_of=as_of,
            )
        else:
            assemble_chain_report(
                repo.conn, key, schema=settings.db_schema, as_of=as_of
            )
    except ValueError as exc:
        # A refused assembly is a data state, not a transport failure: the
        # caller asked a well-formed question Argon declined to answer.
        log.warning("assemble_report %s refused: %s", report_key, repr(exc))
        return ReportResponse(state="failed_run", reason=str(exc))

    return get_report(report_type, key, repo=repo, settings=settings)
