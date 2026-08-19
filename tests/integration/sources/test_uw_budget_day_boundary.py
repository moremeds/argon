"""The account guard must not inherit yesterday's counter across the day boundary.

Reproduces the 2026-08-18 outage: UW's `official_daily_count` resets a beat AFTER
00:00 UTC, so the first requests of a new budget day still carry the previous
day's tail. `read_snapshot` used `MAX()` over the UTC day, which pinned that tail
for the next 24h — and because `may_spend` halts EVERY pool once the account
counter reaches `total_guard`, one day closing above the guard silently disabled
the whole next day. full_scan made zero UW calls and health reported "16 expected
full scans missed".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from uw_scan.sources.uw_budget import BudgetLimits, may_spend, read_snapshot
from uw_scan.storage.repository import Repository

# The real boundary, to the millisecond: the last pre-reset row landed at
# 00:00:04.016Z reading 110214, the next at 00:00:04.227Z reading 1.
_DAY = datetime(2026, 8, 18, tzinfo=UTC)
_STALE_COUNT = 110_214
_LIMITS = BudgetLimits(
    live_ceiling=60_000, research_ceiling=45_000, total_guard=105_000, enabled=True
)


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _record(repo: Repository, *, at: datetime, job: str, count: int) -> None:
    repo.insert_external_api_request(
        provider="uw",
        endpoint_key="greek_exposure",
        method="GET",
        path_template="/api/stock/{ticker}/greek-exposure",
        path="/api/stock/SPY/greek-exposure",
        ticker="SPY",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=at,
        finished_at=at,
        latency_ms=40,
        official_daily_count=count,
        official_daily_limit=120_000,
        job_name=job,
    )


def test_pre_reset_counter_does_not_poison_the_new_budget_day(repo: Repository) -> None:
    # Four seconds of rows still carrying yesterday's (over-guard) tail...
    _record(
        repo,
        at=_DAY + timedelta(seconds=4.016),
        job="regime_gex_scan",
        count=_STALE_COUNT,
    )
    # ...then UW's counter resets and the real new day begins.
    _record(repo, at=_DAY + timedelta(seconds=4.227), job="regime_gex_scan", count=1)
    _record(repo, at=_DAY + timedelta(minutes=30), job="full_scan", count=812)
    repo.conn.commit()

    snap = read_snapshot(repo.conn, "uw_scan", now_utc=_DAY + timedelta(hours=6))

    # The guard reads the LATEST counter, not the day's max.
    assert snap.account_count == 812, (
        f"account_count={snap.account_count} inherited the pre-reset tail; "
        "the whole day would be halted"
    )
    assert snap.live_spent == 1  # full_scan
    assert snap.research_spent == 2  # regime_gex_scan x2

    # ...so scans are allowed to run, which is the behaviour that broke.
    assert may_spend("live", snap, _LIMITS) is True
    assert may_spend("research", snap, _LIMITS) is True


def test_guard_still_halts_when_the_account_is_genuinely_over(repo: Repository) -> None:
    """The fix must not defang the guard — a real over-guard reading still stops."""
    _record(repo, at=_DAY + timedelta(hours=1), job="full_scan", count=1_000)
    _record(repo, at=_DAY + timedelta(hours=9), job="full_scan", count=_STALE_COUNT)
    repo.conn.commit()

    snap = read_snapshot(repo.conn, "uw_scan", now_utc=_DAY + timedelta(hours=10))

    assert snap.account_count == _STALE_COUNT
    assert may_spend("live", snap, _LIMITS) is False
    assert may_spend("research", snap, _LIMITS) is False
