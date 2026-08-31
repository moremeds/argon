"""US rates mirror API endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.routers.macro import resolve_instant, state_summary_fields
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
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; returns the snapshot current at that day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None, description="Timezone-aware instant to replay."
    ),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RatesSnapshotResponse:
    """The rates snapshot, live or as it stood at a past instant.

    The macro desk renders four ``/api/macro/*`` cards beside this one.  Without a
    replay here, a desk asked for a historical date would have shown four historical
    tabs next to one live tab and nothing on screen saying which was which.
    """
    replaying = as_of is not None or as_of_ts is not None
    instant = resolve_instant(as_of, as_of_ts)
    # ``None`` rather than ``instant`` when live, so the shipped query is untouched: a
    # snapshot whose ``computed_at`` sits a second in the future because the worker and
    # the API disagree about the clock must not 404 the page.
    row = repo.fetch_latest_rates_snapshot(as_of=instant if replaying else None)
    if row is None:
        raise HTTPException(status_code=404, detail="rates snapshot not computed")
    snapshot = RatesSnapshotResponse.model_validate(row["payload"])
    snapshot = _mark_stale_snapshot_sources(snapshot, at=instant)
    if not settings.rates_snapshot_state_block_enabled:
        return snapshot
    return snapshot.model_copy(
        update={"state": _policy_state_summary(repo, at=instant)}
    )


def _policy_state_summary(
    repo: Repository, *, at: datetime
) -> MacroStateSummary | None:
    """The stored policy/rates state as of ``at``, or nothing.

    Read fresh on every request rather than baked into the stored snapshot: the two are
    computed by different jobs on different clocks, and a state copied into last night's
    snapshot would keep asserting last night's answer after the state itself was
    quarantined.
    """
    state = repo.fetch_macro_domain_state_as_of("policy_rates", at)
    if state is None:
        return None
    evidence = repo.fetch_macro_domain_state_evidence(int(state["state_id"]))
    return MacroStateSummary.model_validate(
        {
            **state_summary_fields(state, requested_as_of=at),
            "evidence_count": len(evidence),
            "detail_path": STATE_DETAIL_PATH,
        }
    )


def _mark_stale_snapshot_sources(
    snapshot: RatesSnapshotResponse, *, at: datetime
) -> RatesSnapshotResponse:
    """Age the snapshot against the instant being ASKED about, never the wall clock.

    ``at`` was ``now`` until ``/snapshot`` learned to replay, and the rename is the
    fix.  Measured against ``datetime.now()``, every historical snapshot is old, so a
    replay would have force-marked every source stale and appended a scheduler-failure
    risk to every past date on the desk -- reporting an outage that never happened, on
    evidence that was fresh at the time.  Aged against the requested instant, a replay
    reports the staleness the desk really had then, which is what a replay is for.
    """
    computed_at = snapshot.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=UTC)
    if at - computed_at <= SNAPSHOT_STALE_AFTER:
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
