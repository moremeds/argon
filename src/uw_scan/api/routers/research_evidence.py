"""Events, deterministic risks, and the discovery gate (M6). Read-only.

Its own router rather than more lines on `radar.py`: the module-size budget
targets <500 lines and the seam here is a real domain boundary — dimensions
answer "how does this name score", evidence answers "what happened and what
might be wrong with the answer".
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models import (
    CompanyEvidenceResponse,
    EventClassStatus,
    ResearchEvent,
    RiskFact,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.research_events import ResearchEventsRepository

log = logging.getLogger(__name__)

router = APIRouter(tags=["research-evidence"])


@router.get(
    "/stock/{ticker}/research/evidence", response_model=CompanyEvidenceResponse
)
def company_evidence(
    ticker: str,
    known_by: date | None = Query(
        default=None,
        description=(
            "Show only what Argon could know by this date. Predicates on "
            "first_known_at, never on when the event occurred."
        ),
    ),
    limit: int = Query(default=40, ge=1, le=200),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CompanyEvidenceResponse:
    """One name's event timeline and deterministic risk facts."""
    events_repo = ResearchEventsRepository(repo.conn, schema=settings.db_schema)
    symbol = ticker.upper()

    events = events_repo.events_for(symbol, known_by=known_by, limit=limit)
    risks = events_repo.risks_for(symbol, as_of=known_by)
    killed = [c for c in events_repo.classes() if c["status"] == "killed"]

    state = "ok"
    reason = None
    if not events and not risks:
        state = "no_coverage"
        reason = (
            f"no derived events or risk facts for {symbol}. Run "
            "worker/jobs/research_events_derive, or the name is outside the "
            "fundamental universe."
        )

    return CompanyEvidenceResponse(
        ticker=symbol,
        events=[
            ResearchEvent(
                event_id=e["event_id"],
                event_class=e["event_class"],
                occurred_at=e["occurred_at"],
                first_known_at=e["first_known_at"],
                title=e["title"],
                detail=e["detail_jsonb"] or {},
                source_kind=e["source_kind"],
                source_ref=e["source_ref"],
                superseded_by=e["superseded_by"],
            )
            for e in events
        ],
        risks=[
            RiskFact(
                risk_kind=r["risk_kind"],
                observed_value=(
                    float(r["observed_value"])
                    if r["observed_value"] is not None
                    else None
                ),
                threshold=(
                    float(r["threshold"]) if r["threshold"] is not None else None
                ),
                breached=bool(r["breached"]),
                severity=r["severity"],
                statement=r["statement"],
                invalidates=r["invalidates"],
                source_kind=r["source_kind"],
                as_of=r["as_of"],
            )
            for r in risks
        ],
        # Always sent, even on a healthy name: a timeline with no supply-chain
        # events looks complete unless the reader is told that class was killed
        # for want of a source.
        killed_classes=[
            EventClassStatus(
                event_class=c["event_class"],
                status=c["status"],
                source_table=c["source_table"],
                rationale=c["rationale"],
                measured_rows=c["measured_rows"],
            )
            for c in killed
        ],
        state=state,
        reason=reason,
    )


@router.get("/research/evidence/classes", response_model=list[EventClassStatus])
def evidence_classes(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> list[EventClassStatus]:
    """The discovery gate, as data. Live and killed classes with their counts."""
    rows = ResearchEventsRepository(
        repo.conn, schema=settings.db_schema
    ).classes()
    return [
        EventClassStatus(
            event_class=c["event_class"],
            status=c["status"],
            source_table=c["source_table"],
            rationale=c["rationale"],
            measured_rows=c["measured_rows"],
        )
        for c in rows
    ]
