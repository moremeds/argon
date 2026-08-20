"""US rates mirror API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.routers.macro import state_summary_fields
from uw_scan.config import Settings
from uw_scan.models import (
    MacroStateSummary,
    RatesSnapshotResponse,
    RatesSourceFreshness,
)
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/rates", tags=["rates"])
SNAPSHOT_STALE_AFTER = timedelta(hours=36)

#: Where the same state's full evidence lives.  Carried in the payload rather than left
#: to the client to guess, so the compact block can never become the only view of an
#: answer whose whole point is being checkable.
STATE_DETAIL_PATH = "/api/macro/rates"


@router.get("/snapshot", response_model=RatesSnapshotResponse)
def rates_snapshot(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RatesSnapshotResponse:
    row = repo.fetch_latest_rates_snapshot()
    if row is None:
        raise HTTPException(status_code=404, detail="rates snapshot not computed")
    now = datetime.now(UTC)
    snapshot = RatesSnapshotResponse.model_validate(row["payload"])
    snapshot = _mark_stale_snapshot_sources(snapshot, now=now)
    if not settings.rates_snapshot_state_block_enabled:
        return snapshot
    return snapshot.model_copy(update={"state": _policy_state_summary(repo, now=now)})


def _policy_state_summary(
    repo: Repository, *, now: datetime
) -> MacroStateSummary | None:
    """The latest stored policy/rates state, or nothing.

    Read fresh on every request rather than baked into the stored snapshot: the two are
    computed by different jobs on different clocks, and a state copied into last night's
    snapshot would keep asserting last night's answer after the state itself was
    quarantined.
    """
    state = repo.fetch_macro_domain_state_as_of("policy_rates", now)
    if state is None:
        return None
    evidence = repo.fetch_macro_domain_state_evidence(int(state["state_id"]))
    return MacroStateSummary.model_validate(
        {
            **state_summary_fields(state, requested_as_of=now),
            "evidence_count": len(evidence),
            "detail_path": STATE_DETAIL_PATH,
        }
    )


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
