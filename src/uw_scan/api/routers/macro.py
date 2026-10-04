"""Point-in-time macro policy comparison and domain-state API."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.macro.replay import (  # noqa: F401  (re-exported: STATE_STALE_AFTER)
    STATE_STALE_AFTER,
    resolve_instant,
    state_summary_fields,
)
from uw_scan.models import (
    MacroContextSnapshotResponse,
    MacroDomainStateResponse,
    MacroReleaseCalendarResponse,
    PolicyComparison,
)
from uw_scan.reports.macro_releases import week_releases
from uw_scan.storage.macro_release_calendar import MacroReleaseCalendarRepository
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/macro", tags=["macro"])


@router.get("/policy", response_model=PolicyComparison)
def macro_policy(
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; replay includes evidence available by day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None,
        description=(
            "Timezone-aware instant; replay includes evidence available at or "
            "before it. Required to replay across an intraday release."
        ),
    ),
    repo: Repository = Depends(get_repo),
) -> PolicyComparison:
    return build_policy_comparison(repo, as_of=resolve_instant(as_of, as_of_ts))


@router.get("/releases", response_model=MacroReleaseCalendarResponse)
def macro_releases(
    week: date | None = Query(
        default=None,
        description="Any date in the target week (Mon-Sun, UTC). Defaults to the current week.",
    ),
    repo: Repository = Depends(get_repo),
) -> MacroReleaseCalendarResponse:
    releases_repo = MacroReleaseCalendarRepository(repo.conn, schema=repo.schema)
    return week_releases(releases_repo, week or datetime.now(UTC).date())


@router.get("/inflation", response_model=MacroDomainStateResponse)
def macro_inflation_state(
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; returns the state answering for that day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None, description="Timezone-aware instant to replay."
    ),
    repo: Repository = Depends(get_repo),
) -> MacroDomainStateResponse:
    return _domain_state(repo, "inflation", resolve_instant(as_of, as_of_ts))


@router.get("/rates", response_model=MacroDomainStateResponse)
def macro_rates_state(
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; returns the state answering for that day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None, description="Timezone-aware instant to replay."
    ),
    repo: Repository = Depends(get_repo),
) -> MacroDomainStateResponse:
    return _domain_state(repo, "policy_rates", resolve_instant(as_of, as_of_ts))


@router.get("/usd", response_model=MacroDomainStateResponse)
def macro_usd_state(
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; returns the state answering for that day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None, description="Timezone-aware instant to replay."
    ),
    repo: Repository = Depends(get_repo),
) -> MacroDomainStateResponse:
    return _domain_state(repo, "usd", resolve_instant(as_of, as_of_ts))


@router.get("/gold", response_model=MacroDomainStateResponse)
def macro_gold_state(
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; returns the state answering for that day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None, description="Timezone-aware instant to replay."
    ),
    repo: Repository = Depends(get_repo),
) -> MacroDomainStateResponse:
    """The gold GATE, not a view on gold.

    This route did not exist until now, and the reason it did not is worth keeping:
    gold's inputs lived in warm-store tables rather than ``macro_observations``, so no
    state could cite evidence and the store refuses an answer nobody can reconstruct
    (design spec, deviation 7). That deviation names its own overturn condition -- "an
    ingest that lands the gold sources as macro_observations" -- and
    ``worker/jobs/macro_gold_ingest`` is it.

    Honest about the scope of that overturn: TWO of the manifest's sixteen inputs are
    citable, the gold price and the ETF tonnage. They are the two the state stands on,
    which is what makes it persistable. The rest of the manifest -- central-bank
    reserves, exchange inventory, COT, UW options -- is still warm-store only and is
    still served, with its omission reasons, by ``/api/gold/state`` and
    ``/api/gold/replay``. This endpoint does not replace those; it answers a narrower
    question they never answered.
    """
    return _domain_state(repo, "gold", resolve_instant(as_of, as_of_ts))


@router.get("/snapshot", response_model=MacroContextSnapshotResponse)
def macro_context_snapshot(
    as_of: date | None = Query(
        default=None,
        description="UTC calendar date; returns the snapshot answering for that day-end.",
    ),
    as_of_ts: datetime | None = Query(
        default=None, description="Timezone-aware instant to replay."
    ),
    repo: Repository = Depends(get_repo),
) -> MacroContextSnapshotResponse:
    """The four domains as one answer, with whatever refusal the assembler recorded.

    This is the route the desk should read instead of four independent latest states. The
    four-request shape cannot notice that USD stood on last night's rates, because every
    row it fetches is individually current and individually honest; only the snapshot
    holds the claim that they belong together.

    A ``complete`` status is not a claim that the macro picture is right -- only that the
    chain is internally coherent. The states remain descriptive.
    """
    requested_as_of = resolve_instant(as_of, as_of_ts)
    row = repo.fetch_macro_context_snapshot_as_of(requested_as_of)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "no macro context snapshot has been assembled for an instant at or "
                f"before {requested_as_of.isoformat()}"
            ),
        )
    domains = repo.fetch_macro_context_snapshot_domains(int(row["snapshot_id"]))
    return MacroContextSnapshotResponse.model_validate(
        {
            "requested_as_of": requested_as_of,
            "as_of": row["as_of"],
            "assembled_at": row["assembled_at"],
            "status": row["status"],
            "assembler_version": row["assembler_version"],
            "inputs_hash": row["inputs_hash"],
            "domains": [
                {
                    "domain": item["domain"],
                    "ordinal": item["ordinal"],
                    "state_id": item["state_id"],
                    "state": item["state"],
                    "direction": item["direction"],
                    "confidence": item["confidence"],
                    "as_of": item["state_as_of"],
                    "engine_version": item["engine_version"],
                    "inputs_hash": item["inputs_hash"],
                }
                for item in domains
            ],
            # Stored as written by the assembler. Rebuilding them here would be a second
            # place the refusal is decided, and the two would drift.
            "reasons": row["status_reasons_jsonb"] or [],
        }
    )


def _domain_state(
    repo: Repository, domain: str, requested_as_of: datetime
) -> MacroDomainStateResponse:
    """Return the stored answer, never a fresh computation.

    A replay recomputed with today's engine would report what we *would* have said, which
    is not what we said.  So a request for an instant nobody computed a state for is a
    404, not a state assembled on the spot: the honest reply to "what did you think in
    March" is "nothing was recorded", and inventing one would make the whole audit trail
    unfalsifiable.
    """
    row = repo.fetch_macro_domain_state_as_of(domain, requested_as_of)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no {domain} state has been computed for an instant at or before "
                f"{requested_as_of.isoformat()}"
            ),
        )
    state_id = int(row["state_id"])
    evidence = repo.fetch_macro_domain_state_evidence(state_id)
    upstream = repo.fetch_macro_domain_state_dependencies(state_id)
    return MacroDomainStateResponse.model_validate(
        {
            **state_summary_fields(row, requested_as_of=requested_as_of),
            "requested_as_of": requested_as_of,
            "inputs_hash": row["inputs_hash"],
            "factors": row["factors_jsonb"],
            # Rows written before migration 127 have no column value at all; an empty
            # list is what they actually carried, so it is not a substitution.
            "sub_states": row.get("sub_states_jsonb") or [],
            "evidence": [
                {
                    "ordinal": item["ordinal"],
                    "obs_id": item["obs_id"],
                    "artifact_id": item["artifact_id"],
                    "causal_role": item["causal_role"],
                    "series_id": item["series_id"],
                    "period_end": item["period_end"],
                    "unit": item["unit"],
                    "value_numeric": item["value_numeric"],
                    "available_at": item["available_at"],
                    "source": item["source"],
                    "source_kind": item["source_kind"],
                    "quality_status": item["quality_status"],
                }
                for item in evidence
            ],
            "upstream": [
                {
                    "upstream_state_id": item["upstream_state_id"],
                    "domain": item["upstream_domain"],
                    "causal_role": item["causal_role"],
                    "state": item["upstream_state"],
                    "direction": item["upstream_direction"],
                    "confidence": item["upstream_confidence"],
                    "as_of": item["upstream_as_of"],
                    "engine_version": item["upstream_engine_version"],
                    "inputs_hash": item["upstream_inputs_hash"],
                }
                for item in upstream
            ],
        }
    )
