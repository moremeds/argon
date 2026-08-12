"""Point-in-time macro policy comparison API."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Query

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
    repo: Repository = Depends(get_repo),
) -> PolicyComparison:
    instant = (
        datetime.combine(as_of, time.max, tzinfo=UTC)
        if as_of is not None
        else datetime.now(UTC)
    )
    return build_policy_comparison(repo, as_of=instant)
