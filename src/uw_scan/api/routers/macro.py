"""Point-in-time macro policy comparison API."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.models import PolicyComparison
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
        instant = as_of_ts
    elif as_of is not None:
        instant = datetime.combine(as_of, time.max, tzinfo=UTC)
    else:
        instant = datetime.now(UTC)
    return build_policy_comparison(repo, as_of=instant)
