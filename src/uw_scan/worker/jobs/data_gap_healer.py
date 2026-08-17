"""Data gap healer orchestration + the nightly scheduled job.

The CLI (`scripts/backfill/data_gap_healer.py`) is a thin argparse wrapper over
the core functions here. The nightly job (`data_gap_healer_job`) runs at 20:00 ET
(just after the UW quota reset), audits + heals strict gaps under a UW cap, then
refreshes the re-runnable (macro/FRED/rates/gold + DB rollup) datasets, and
writes the report artifact. Single-flight via an advisory lock; skips if a prior
healer run is still active so it never fights a manual backfill -- but first
reaps runs left 'running' by a killed process, which would otherwise wedge that
skip forever (see _reap_stale_runs).
"""

from __future__ import annotations

import logging
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
) -> tuple[int, dict, RequestBudget, list[CoverageSummary], list[GapItem]]:
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
) -> tuple[dict, RequestBudget]:
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
    )
    outcome = execute_run(ctx, run_id, specs=specs)
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
# were all correct. The staleness test is the run's own PROGRESS, not its age: a
# legitimate multi-day manual backfill keeps verifying items and is never reaped,
# while a corpse clears on the very next nightly. See
# docs/research/2026-08-16-outage-replay-heal-record.md.
_STALE_RUN_HOURS = 6


def _reap_stale_runs(gap: DataGapHealerRepository) -> list[int]:
    """Cancel execute-runs with no item progress for _STALE_RUN_HOURS, and requeue
    the items they orphaned. The run-level twin of resume_run's requeue_running.

    'cancelled', never 'complete' -- the run did not finish, and only 'running'
    trips the active-run gate, so cancelling is enough to unwedge it.
    """
    reason = (
        f"auto-cancelled by data_gap_healer_job: "
        f"no item progress in {_STALE_RUN_HOURS}h"
    )
    with gap._conn.cursor() as cur:
        cur.execute(
            """
            UPDATE data_gap_runs r
               SET status = 'cancelled',
                   finished_at = now(),
                   summary_jsonb = r.summary_jsonb
                                   || jsonb_build_object('cancelled_reason', %s::text)
             WHERE r.status = 'running'
               AND r.mode = 'execute'
               -- heartbeat: last item driven to a verdict, else the run's own start
               AND COALESCE(
                     (SELECT max(i.verified_at) FROM data_gap_items i
                       WHERE i.run_id = r.id),
                     r.started_at
                   ) < now() - make_interval(hours => %s)
         RETURNING r.id
            """,
            (reason, _STALE_RUN_HOURS),
        )
        run_ids = [row[0] for row in cur.fetchall()]
    gap._conn.commit()
    for run_id in run_ids:
        # Items left 'running' were never driven to a verdict, and claim_next_items
        # skips that status -- without this they stay unhealable forever.
        logger.warning(
            "data_gap_healer: reaped stale run %s (requeued %d orphaned items)",
            run_id,
            gap.requeue_running(run_id),
        )
    return run_ids


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
            reaped = _reap_stale_runs(gap)
            if _another_run_active(gap):
                logger.info("data_gap_healer: a prior run is active; skipping")
                return {"skipped": "run_active", "reaped": reaped}
            return _run_nightly(repo, gap, settings, today, out_dir) | {
                "reaped": reaped
            }
        finally:
            with repo.conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    finally:
        repo.conn.close()


def _run_nightly(
    repo: Repository,
    gap: DataGapHealerRepository,
    settings: Settings,
    today: date,
    out_dir: Path,
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
            settings.data_gap_healer_max_uw_calls,
            dataset_share=settings.data_gap_healer_dataset_share,
        ),
        settings=settings,
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
