"""UW daily-budget governor.

The whole stack shares one UW account daily counter (120k, resets 00:00 UTC /
20:00 ET). This module decides, per job, whether another UW call is allowed —
so live page-serving scans keep priority while research/backfill yields first,
and a hard total-guard keeps a safety margin below the account cap.

Two layers:
- pure decision (`may_spend`, `pool_for_job`, `bucket_spend`) — no DB, unit-tested
- one DB read (`read_snapshot`) over `external_api_requests` for today's spend

Design: read a snapshot ONCE at the top of a scan pass, then gate cheaply. The
account-wide counter (`official_daily_count` header) is the real guard because
it also sees un-instrumented consumers; per-pool ceilings come from our own
attributed rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Pool = Literal["live", "research"]

# Jobs that serve the web pages fresh — they get budget priority. Everything
# else (regime/tide/gex capture, nightly snapshots, all *_backfill scripts,
# and any unknown job) is research and yields first.
LIVE_JOBS: frozenset[str] = frozenset({"full_scan", "full_scan_hot", "rescan_tick"})


def pool_for_job(job_name: str | None) -> Pool:
    return "live" if job_name in LIVE_JOBS else "research"


@dataclass(frozen=True)
class BudgetLimits:
    live_ceiling: int
    research_ceiling: int
    total_guard: int
    enabled: bool


@dataclass(frozen=True)
class BudgetSnapshot:
    live_spent: int
    research_spent: int
    account_count: int | None  # account-wide daily counter; None if unknown today

    def spent_for(self, pool: Pool) -> int:
        return self.live_spent if pool == "live" else self.research_spent


def limits_from_settings(settings) -> BudgetLimits:
    return BudgetLimits(
        live_ceiling=settings.uw_live_daily_ceiling,
        research_ceiling=settings.uw_research_daily_ceiling,
        total_guard=settings.uw_total_daily_guard,
        enabled=settings.uw_budget_governor_enabled,
    )


def may_spend(pool: Pool, snap: BudgetSnapshot, limits: BudgetLimits) -> bool:
    """True if a job in `pool` may make another UW call under the snapshot."""
    if not limits.enabled:
        return True
    # Account-wide guard: near the hard cap, halt everything (even under-ceiling
    # pools) to protect the last margin — this is what un-instrumented backfill
    # and any shared-key consumer can only be caught by.
    if snap.account_count is not None and snap.account_count >= limits.total_guard:
        return False
    ceiling = limits.live_ceiling if pool == "live" else limits.research_ceiling
    return snap.spent_for(pool) < ceiling


def bucket_spend(rows: Iterable[tuple[str | None, int, int | None]]) -> BudgetSnapshot:
    """Fold (job_name, call_count, account_count) rows into a pool snapshot."""
    live = 0
    research = 0
    account: int | None = None
    for job_name, n, acct in rows:
        if pool_for_job(job_name) == "live":
            live += n
        else:
            research += n
        if acct is not None and (account is None or acct > account):
            account = acct
    return BudgetSnapshot(
        live_spent=live, research_spent=research, account_count=account
    )


def _utc_day_start(now_utc: datetime) -> datetime:
    cur = (
        now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
    )
    cur = cur.astimezone(timezone.utc)
    return cur.replace(hour=0, minute=0, second=0, microsecond=0)


def read_snapshot(
    conn, schema: str, *, now_utc: datetime | None = None
) -> BudgetSnapshot:
    """Read today's (UTC-day) UW spend grouped into pools from telemetry."""
    day_start = _utc_day_start(now_utc or datetime.now(timezone.utc))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT job_name, COUNT(*)::bigint AS n,
                   MAX(official_daily_count) AS acct
            FROM {schema}.external_api_requests
            WHERE provider = 'uw' AND request_started_at >= %s
            GROUP BY job_name
            """,
            (day_start,),
        )
        rows = [(r[0], int(r[1]), r[2]) for r in cur.fetchall()]
    return bucket_spend(rows)
