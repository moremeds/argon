"""Point-in-time macro policy comparison and domain-state API."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.models import MacroDomainStateResponse, PolicyComparison
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/macro", tags=["macro"])

#: A state older than this has not been recomputed since, which is a statement about our
#: scheduler and not about the publishers -- each factor carries its own freshness inside
#: ``confidence_reasons``.  Matched to the rates snapshot's own window so two surfaces
#: reading the same desk do not disagree about what "stale" means.
STATE_STALE_AFTER = timedelta(hours=36)


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
    return build_policy_comparison(repo, as_of=_resolve_instant(as_of, as_of_ts))


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
    return _domain_state(repo, "inflation", _resolve_instant(as_of, as_of_ts))


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
    return _domain_state(repo, "policy_rates", _resolve_instant(as_of, as_of_ts))


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
    evidence = repo.fetch_macro_domain_state_evidence(int(row["state_id"]))
    return MacroDomainStateResponse.model_validate(
        {
            **state_summary_fields(row, requested_as_of=requested_as_of),
            "requested_as_of": requested_as_of,
            "inputs_hash": row["inputs_hash"],
            "factors": row["factors_jsonb"],
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
        }
    )


def state_summary_fields(
    row: dict[str, Any], *, requested_as_of: datetime
) -> dict[str, Any]:
    """The fields both the full state and the compact snapshot block share."""
    age = requested_as_of - row["as_of"]
    return {
        "domain": row["domain"],
        "as_of": row["as_of"],
        "computed_at": row["computed_at"],
        "engine_version": row["engine_version"],
        "state": row["state"],
        "direction": row["direction"],
        "confidence": row["confidence"],
        "freshness": "fresh" if age <= STATE_STALE_AFTER else "stale",
        # Negative when a caller replays a date the state predates by design; reported as
        # measured rather than clamped, so an odd number stays visible instead of
        # rounding to a reassuring zero.
        "age_hours": round(age.total_seconds() / 3600, 2),
        "velocity": row["velocity_jsonb"],
        "confidence_reasons": row["confidence_reasons_jsonb"],
        "contradictions": row["contradictions_jsonb"],
        "notes": row["notes_jsonb"],
    }


def _resolve_instant(as_of: date | None, as_of_ts: datetime | None) -> datetime:
    if as_of is not None and as_of_ts is not None:
        raise HTTPException(
            status_code=422, detail="supply either as_of or as_of_ts, not both"
        )
    if as_of_ts is not None:
        # A naive instant is a timezone guess, and the FOMC publishes at 14:00
        # ET -- guessing UTC moves the release four or five hours.
        if as_of_ts.tzinfo is None or as_of_ts.utcoffset() is None:
            raise HTTPException(
                status_code=422, detail="as_of_ts must carry a UTC offset"
            )
        return as_of_ts
    if as_of is not None:
        return datetime.combine(as_of, time.max, tzinfo=UTC)
    return datetime.now(UTC)
