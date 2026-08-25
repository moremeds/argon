"""Data gap healer orchestration + the nightly scheduled job.

The CLI (`scripts/backfill/data_gap_healer.py`) is a thin argparse wrapper over
the core functions here. The nightly job (`data_gap_healer_job`) runs at 20:00 ET
(just after the UW quota reset), audits + heals strict gaps under a UW cap, then
refreshes the re-runnable (macro/FRED/rates/gold + DB rollup) datasets, and
writes the report artifact.

Single-flight is layered, and the order matters: EVERY path that spends provider
budget holds the session advisory lock (`_single_flight`), so a live heal makes
the nightly job stand down before it touches anything; the `status='running'` row
check then catches runs a lock cannot (it is not session-scoped, so it survives
the process); and `_reap_stale_runs` clears rows whose process is gone, which
that check would otherwise honour forever.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.data_gap_evidence import build_evidence, write_evidence
from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    CoverageSummary,
    GapItem,
    audit,
    discover_unregistered_tables,
)
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.data_gap_adapters import (
    HEAL_SPECS,
    HealContext,
    RequestBudget,
    execute_run,
    run_refresh_adapters,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parents[4] / "output" / "data-gap"
_LOCK_KEY = 92010  # advisory lock: single-flight for the gap healer


class HealerBusy(RuntimeError):
    """Another heal already holds the single-flight lock."""


@contextmanager
def _single_flight(gap: DataGapHealerRepository):
    """Hold the gap-healer advisory lock for a heal that spends provider budget.

    A Postgres SESSION lock is released when the connection dies, which is
    exactly the liveness guarantee `data_gap_runs.status='running'` does NOT
    give -- that gap is why the row-based guard needed a reaper at all. Holding
    this around the operator heal paths means a live manual heal makes the
    nightly job return `{"skipped": "locked"}` *before* it reaps anything, so a
    running process can never be mistaken for a corpse.

    The nightly job holds this lock itself and calls execute_run directly, so it
    does not nest here. data_freshness_monitor's autoheal DOES take it and then
    call execute_into_run -- same connection, and session locks are re-entrant
    with a counter, so the nested acquire/release balances correctly.

    Re-entrant on the same connection; raises HealerBusy on a different one.
    """
    with gap._conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
        if not cur.fetchone()[0]:
            raise HealerBusy(
                "another gap-heal holds the single-flight lock (key "
                f"{_LOCK_KEY}); refusing to race it and double-spend the "
                "provider budget"
            )
    try:
        yield
    finally:
        with gap._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))


# --- core orchestration (testable; take repo/gap, no settings construction) ---


def per_dataset_summary(summaries: list[CoverageSummary]) -> dict:
    return {
        s.dataset: {
            "audit_mode": s.audit_mode,
            "expected": s.expected_pairs,
            "covered": s.covered_pairs,
            "missing": s.missing_pairs,
            "gap_days": len(s.gap_dates),
        }
        for s in summaries
    }


def active_tickers(repo: Repository, active: list[str] | None) -> list[str]:
    if active is not None:
        return active
    return [c.ticker for c in repo.list_watchlist_cards()]


def reconcile_watchlist_lifecycle(
    repo: Repository,
    gap: DataGapHealerRepository,
    today: date,
    active: list[str] | None = None,
) -> dict:
    """Log watchlist add/remove deltas vs the last-known state.

    - **added** (new or re-added): logged; the audit in the same run then finds
      their missing history as gaps and heals it (that IS the backfill schedule).
    - **removed** (gone from the watchlist): logged, rows left untouched. No
      exclusion code needed — the denominator is the live watchlist, so a removed
      ticker is already out of every count; the log just records when/why.

    Append-only, so a remove->re-add cycle keeps both events. First run logs the
    whole current watchlist as 'added' (the tracking baseline).
    """
    active_set = {t.upper() for t in active_tickers(repo, active)}
    status = gap.current_ticker_status()
    known_active = {t for t, ev in status.items() if ev == "added"}
    added = sorted(active_set - known_active)
    removed = sorted(known_active - active_set)
    events: list[tuple[str, str, date, str | None]] = [
        (t, "added", today, None) for t in added
    ] + [(t, "removed", today, "absent from watchlist") for t in removed]
    gap.record_ticker_events(events)
    return {"added": added, "removed": removed}


def audit_into_run(
    repo: Repository,
    gap: DataGapHealerRepository,
    schema: str,
    *,
    start: date,
    end: date,
    datasets: list[str] | None,
    mode: str = "audit",
    active: list[str] | None = None,
) -> tuple[int, list[CoverageSummary], list[GapItem]]:
    gap.sync_dataset_registry(REGISTRY)
    active = active_tickers(repo, active)
    caveats = gap.list_caveats()
    summaries, items = audit(
        repo.conn, schema, REGISTRY, active, caveats, start, end, datasets
    )
    run_id = gap.create_run(
        mode=mode, start_date=start, end_date=end, datasets=datasets or []
    )
    gap.upsert_items(run_id, items)
    return run_id, summaries, items


def finalize_run(
    gap: DataGapHealerRepository,
    run_id: int,
    summaries: list[CoverageSummary],
    items: list[GapItem],
    *,
    extra: dict | None = None,
) -> dict:
    per = per_dataset_summary(summaries)
    summary = {"datasets": per, "total_gaps": len(items)}
    if extra:
        summary.update(extra)
    gap.finish_run(run_id, status="complete", summary=summary)
    return per


def execute_into_run(
    repo: Repository,
    gap: DataGapHealerRepository,
    settings: Settings,
    *,
    start: date,
    end: date,
    datasets: list[str] | None,
    max_uw_calls: int,
    today: date,
    specs: dict | None = None,
    active: list[str] | None = None,
    recorder: object | None = None,
) -> tuple[int, dict, RequestBudget, list[CoverageSummary], list[GapItem]]:
    with _single_flight(gap):
        run_id, summaries, items = audit_into_run(
            repo,
            gap,
            settings.db_schema,
            start=start,
            end=end,
            datasets=datasets,
            mode="execute",
            active=active,
        )
        ctx = HealContext(
            repo=repo,
            gap=gap,
            schema=settings.db_schema,
            today=today,
            budget=RequestBudget(max_uw_calls),
            settings=settings,
            recorder=recorder,
        )
        outcome = execute_run(ctx, run_id, datasets=datasets, specs=specs)
        finalize_run(
            gap,
            run_id,
            summaries,
            items,
            extra={"outcome": outcome, "budget_spent": ctx.budget.as_dict()},
        )
        return run_id, outcome, ctx.budget, summaries, items


def resume_run(
    repo: Repository,
    gap: DataGapHealerRepository,
    settings: Settings,
    run_id: int,
    *,
    today: date,
    max_uw_calls: int,
    specs: dict | None = None,
    recorder: object | None = None,
) -> tuple[dict, RequestBudget]:
    with _single_flight(gap):
        # Recover items orphaned in 'running' by a killed/timed-out prior run, so
        # resume actually picks up where it left off (claim skips 'running').
        requeued = gap.requeue_running(run_id)
        if requeued:
            logger.info(
                "resume run=%s requeued %d orphaned running items", run_id, requeued
            )
        ctx = HealContext(
            repo=repo,
            gap=gap,
            schema=settings.db_schema,
            today=today,
            budget=RequestBudget(max_uw_calls),
            settings=settings,
            recorder=recorder,
        )
        outcome = execute_run(ctx, run_id, specs=specs)
        # Close the run. Without this a resume that SUCCEEDS still left the row
        # 'running' forever, wedging the nightly job exactly like a killed run
        # does -- and resume is the ordinary way an operator drains a backfill,
        # so this was the common path into that wedge, not the crash path.
        # Merge rather than replace: the audit's per-dataset rollup is this run's
        # durable record, and staged per-dataset resumes each deserve an entry.
        summary = dict((gap.get_run(run_id) or {}).get("summary_jsonb") or {})
        summary.setdefault("resumes", []).append(
            {
                "outcome": outcome,
                "budget_spent": ctx.budget.as_dict(),
                "requeued": requeued,
            }
        )
        gap.finish_run(run_id, status="complete", summary=summary)
        return outcome, ctx.budget


def verify_run(
    repo: Repository,
    gap: DataGapHealerRepository,
    schema: str,
    run_id: int,
    active: list[str] | None = None,
) -> dict:
    run = gap.get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    datasets = run["datasets"] or None
    active = active_tickers(repo, active)
    caveats = gap.list_caveats()
    summaries, items = audit(
        repo.conn,
        schema,
        REGISTRY,
        active,
        caveats,
        run["start_date"],
        run["end_date"],
        datasets,
    )
    before = (run["summary_jsonb"] or {}).get("total_gaps")
    return {
        "run_id": run_id,
        "before_gaps": before,
        "after_gaps": len(items),
        "datasets": per_dataset_summary(summaries),
    }


def verify_all(
    repo: Repository,
    gap: DataGapHealerRepository,
    settings: Settings,
    *,
    start: date,
    end: date,
    as_of: date,
    out_dir: Path,
    command: str,
    active: list[str] | None = None,
) -> tuple[dict, dict[str, str]]:
    run_id, summaries, items = audit_into_run(
        repo,
        gap,
        settings.db_schema,
        start=start,
        end=end,
        datasets=None,
        active=active,
    )
    unreg = discover_unregistered_tables(repo.conn, settings.db_schema)
    caveats = gap.list_caveats()
    finalize_run(gap, run_id, summaries, items, extra={"unregistered": len(unreg)})
    evidence = build_evidence(
        run_id=run_id,
        summaries=summaries,
        items=items,
        unregistered=unreg,
        caveat_count=len(caveats),
        db_host=settings.db_host,
        db_name=settings.db_name,
        schema=settings.db_schema,
        command=command,
        as_of=as_of,
    )
    paths = write_evidence(evidence, out_dir, as_of)
    return evidence, paths


# --- nightly scheduled job --------------------------------------------------


def _another_run_active(gap: DataGapHealerRepository) -> bool:
    with gap._conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM data_gap_runs "
            "WHERE status = 'running' AND mode = 'execute' LIMIT 1"
        )
        return cur.fetchone() is not None


# A run killed mid-flight (SSH drop, container recreate, OOM) never reaches
# finish_run, so its row stays status='running' forever and _another_run_active
# above skips every later nightly job -- silently, with no alert. Four such runs
# disabled the healer for a week in 2026-08 while the flag, cron and adapters
# were all correct. See docs/research/2026-08-16-outage-replay-heal-record.md.
#
# Six hours is a floor, not a timeout: _single_flight already guarantees no live
# heal is running by the time we reap, so this only decides how long a corpse's
# row survives. Progress (max verified_at) rather than age keeps the window short
# without punishing a slow-but-working run if that guarantee is ever loosened.
_STALE_RUN_HOURS = 6


def _reap_stale_runs(gap: DataGapHealerRepository) -> list[int]:
    """Cancel execute-runs with no item progress for _STALE_RUN_HOURS, requeuing
    the items they orphaned. The run-level twin of resume_run's requeue_running.

    'cancelled', never 'complete' -- the run did not finish, and only 'running'
    trips the active-run gate, so cancelling is enough to unwedge it.

    This is a BACKSTOP, not the liveness mechanism. _single_flight is: every path
    that spends provider budget holds the session advisory lock, and Postgres
    frees a session lock when the process dies. So the caller (data_gap_healer_job)
    only reaches this code once it already owns that lock, which means no live
    heal is running and every 'running' row it finds is genuinely a corpse. Do not
    weaken that ordering -- without the lock, a live-but-idle run could be reaped
    and the nightly would then audit the same still-missing gaps into a NEW run
    and heal them alongside the live process, double-charging the provider budget.
    That is the exact hazard data_freshness_monitor documents at its own lock.

    The heuristic's known blind spot, for when you are reading this after it fired
    on something unexpected: verified_at is stamped by mark_item_healed and
    mark_item_no_data, but NOT by mark_item_failed or mark_item_skipped_budget, so
    a run producing only failures reads as idle. The heal loop has no backoff, so
    failures drain a run in minutes; holding that state for six hours takes a
    provider hard-down where every request burns its full client timeout.
    """
    reason = (
        f"auto-cancelled by data_gap_healer_job: "
        f"no item progress in {_STALE_RUN_HOURS}h"
    )
    # One statement, one transaction: cancelling a run and requeuing its orphans
    # must not be separable. Committing the cancel first and dying before the
    # requeue would leave items stranded 'running' inside a run the reaper no
    # longer matches (it only looks at status='running' RUNS), so nothing would
    # ever free them again.
    with gap._conn.cursor() as cur:
        cur.execute(
            """
            WITH stale AS (
                SELECT r.id
                  FROM data_gap_runs r
                 WHERE r.status = 'running'
                   AND r.mode = 'execute'
                   -- heartbeat: last item driven to a verdict, else the run's start
                   AND COALESCE(
                         (SELECT max(i.verified_at) FROM data_gap_items i
                           WHERE i.run_id = r.id),
                         r.started_at
                       ) < now() - make_interval(hours => %s)
            ),
            requeued AS (
                UPDATE data_gap_items SET status = 'planned'
                 WHERE run_id IN (SELECT id FROM stale)
                   AND status = 'running'
             RETURNING run_id
            ),
            cancelled AS (
                UPDATE data_gap_runs
                   SET status = 'cancelled',
                       finished_at = now(),
                       summary_jsonb = summary_jsonb
                           || jsonb_build_object('cancelled_reason', %s::text)
                 WHERE id IN (SELECT id FROM stale)
             RETURNING id
            )
            SELECT c.id,
                   (SELECT count(*) FROM requeued q WHERE q.run_id = c.id)
              FROM cancelled c
            """,
            (_STALE_RUN_HOURS, reason),
        )
        reaped = cur.fetchall()
    gap._conn.commit()
    for run_id, requeued in reaped:
        logger.warning(
            "data_gap_healer: reaped stale run %s (requeued %d orphaned items)",
            run_id,
            requeued,
        )
    return [run_id for run_id, _ in reaped]


def _make_recorder(settings: Settings):
    """The recorder every healer provider client should carry, or None.

    Fails OPEN on purpose: Task 1 is instrumentation, and a healer that refuses
    to run because its telemetry connection is down would be a worse outage than
    a blind one. The run-level `telemetry_write_failures` counter is what makes
    the blindness visible rather than silent. The budget governor wired in later
    is the piece that must fail CLOSED -- an unknown counter is not permission to
    spend a shared paid account.
    """
    from uw_scan.storage.provider_usage import ExternalApiRequestRecorder

    try:
        return ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    except Exception as exc:
        logger.warning(
            "data_gap_healer: telemetry recorder unavailable, spend will be "
            "invisible to uw_budget this run: %s",
            repr(exc),
        )
        return None


def _refresh_targets(datasets: list[str] | None) -> list[str]:
    return [
        e.table_name
        for e in REGISTRY
        if e.granularity in ("run_once", "run_once_lookback")
        and e.healer_adapter in HEAL_SPECS
        and (datasets is None or e.table_name in datasets)
    ]


def data_gap_healer_job(
    *, settings: Settings, today: date | None = None, out_dir: Path | None = None
) -> dict:
    """Nightly: reap stale runs, then audit + heal strict gaps (UW-capped) +
    refresh re-runnable datasets and write the report. Off unless
    DATA_GAP_HEALER_ENABLED."""
    if not settings.data_gap_healer_enabled:
        return {"skipped": "disabled"}
    today = today or date.today()
    out_dir = out_dir or OUTPUT_DIR
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    gap = DataGapHealerRepository(repo.conn, schema=settings.db_schema)
    try:
        with repo.conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
            got = cur.fetchone()[0]
        if not got:
            logger.info("data_gap_healer: lock held; skipping")
            return {"skipped": "locked"}
        try:
            _reap_stale_runs(gap)
            if _another_run_active(gap):
                logger.info("data_gap_healer: a prior run is active; skipping")
                return {"skipped": "run_active"}
            # Built here, not above: on a night the lock is held or a prior run is
            # still active this job returns without spending anything, and a
            # telemetry connection opened for that is a connection opened for
            # nothing -- ahead of the lock, at that.
            recorder = _make_recorder(settings)
            try:
                return _run_nightly(
                    repo, gap, settings, today, out_dir, recorder=recorder
                )
            finally:
                if recorder is not None:
                    recorder.close()
        finally:
            with repo.conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    finally:
        repo.conn.close()


def _nightly_uw_cap(settings: Settings, today: date) -> int:
    """The night's UW ceiling — larger when the run bills a non-trading day.

    The UW budget day runs 20:00 ET -> 20:00 ET and this job fires AT 20:00, so a run
    spends against the day that FOLLOWS it, not the one it starts in. Friday's and
    Saturday's runs bill Saturday and Sunday: no session, so the live pool needs nothing
    and the healer may take most of the account. Sunday is not scheduled at all (see
    ``data_gap_healer_cron_et``) precisely because that run would bill Monday.

    Getting the boundary wrong in the safe-looking direction — treating Sunday night as
    "the weekend" — would hand a full trading Monday a 90k head start against a 105k
    guard, which is the failure this function exists to prevent.
    """
    is_weekend_billing = today.weekday() in (4, 5)  # Fri, Sat
    return (
        settings.data_gap_healer_max_uw_calls_weekend
        if is_weekend_billing
        else settings.data_gap_healer_max_uw_calls
    )


def _run_nightly(
    repo: Repository,
    gap: DataGapHealerRepository,
    settings: Settings,
    today: date,
    out_dir: Path,
    *,
    recorder: object | None = None,
) -> dict:
    start = date.fromisoformat(settings.data_gap_healer_start)
    datasets = [
        d.strip() for d in settings.data_gap_healer_datasets.split(",") if d.strip()
    ] or None

    # Log watchlist add/remove deltas before the audit, so newly-added tickers
    # are on record and the audit below backfills their history this run.
    lifecycle = reconcile_watchlist_lifecycle(repo, gap, today)

    run_id, summaries, items = audit_into_run(
        repo,
        gap,
        settings.db_schema,
        start=start,
        end=today,
        datasets=datasets,
        mode="execute",
    )
    ctx = HealContext(
        repo=repo,
        gap=gap,
        schema=settings.db_schema,
        today=today,
        # Only the NIGHTLY job is sliced. An operator draining one dataset on
        # purpose via the CLI should not be.
        budget=RequestBudget(
            _nightly_uw_cap(settings, today),
            dataset_share=settings.data_gap_healer_dataset_share,
        ),
        settings=settings,
        recorder=recorder,
    )
    outcome = execute_run(ctx, run_id, datasets=datasets)
    lookback = max(1, (today - start).days)
    refresh = run_refresh_adapters(
        ctx, _refresh_targets(datasets), lookback_days=lookback
    )
    finalize_run(
        gap,
        run_id,
        summaries,
        items,
        extra={
            "outcome": outcome,
            "refresh": refresh,
            "lifecycle": lifecycle,
            "budget_spent": ctx.budget.as_dict(),
            **(ctx.heartbeat.counters() if ctx.heartbeat is not None else {}),
        },
    )
    evidence = build_evidence(
        run_id=run_id,
        summaries=summaries,
        items=items,
        unregistered=[],
        caveat_count=len(gap.list_caveats()),
        db_host=settings.db_host,
        db_name=settings.db_name,
        schema=settings.db_schema,
        command="data_gap_healer_job",
        as_of=today,
        budget=ctx.budget.as_dict(),
        outcome=outcome,
    )
    write_evidence(evidence, out_dir, today)
    logger.info(
        "data_gap_healer run=%s outcome=%s refresh=%s lifecycle=+%d/-%d budget=%s",
        run_id,
        outcome,
        refresh,
        len(lifecycle["added"]),
        len(lifecycle["removed"]),
        ctx.budget.as_dict(),
    )
    return {
        "run_id": run_id,
        "outcome": outcome,
        "refresh": refresh,
        "lifecycle": lifecycle,
        "budget_spent": ctx.budget.as_dict(),
    }
