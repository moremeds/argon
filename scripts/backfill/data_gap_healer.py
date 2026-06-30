"""Data gap healer CLI: detect (audit), heal (execute/resume), and report
(verify / verify-all). Audit + verify are read-only and make ZERO provider
calls. Only `execute`/`resume` spend provider budget, and only UW is capped.

Reproduce (dry audit against the mini, no provider calls):
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    uv run python scripts/backfill/data_gap_healer.py audit --start 2026-01-01

Heal DB-to-DB datasets (no UW spend), then a UW-capped option-surface heal:
  ... execute --datasets vrp_daily,market_tide_sentiment_daily --confirm
  ... execute --datasets option_surface_grid_daily --max-uw-calls 20000 --confirm

Full report + evidence artifact under output/data-gap/:
  ... verify-all --start 2026-01-01 --json
"""

from __future__ import annotations

import argparse
import json
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
    HealContext,
    RequestBudget,
    execute_run,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_gap_healer")

DEFAULT_MAX_UW_CALLS = 20000
_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "data-gap"


# --- testable core (take repo/gap, no argparse/settings construction) -------


def _per_dataset(summaries: list[CoverageSummary]) -> dict:
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


def _active_tickers(repo: Repository, active: list[str] | None) -> list[str]:
    if active is not None:
        return active
    return [c.ticker for c in repo.list_watchlist_cards()]


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
    active = _active_tickers(repo, active)
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
    per_dataset = _per_dataset(summaries)
    summary = {"datasets": per_dataset, "total_gaps": len(items)}
    if extra:
        summary.update(extra)
    gap.finish_run(run_id, status="complete", summary=summary)
    return per_dataset


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
    """Recompute strict coverage for a run's window/datasets (read-only)."""
    run = gap.get_run(run_id)
    if run is None:
        raise SystemExit(f"run {run_id} not found")
    datasets = run["datasets"] or None
    active = _active_tickers(repo, active)
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
        "datasets": _per_dataset(summaries),
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


# --- argparse command wrappers ---------------------------------------------


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _datasets_arg(value: str) -> list[str] | None:
    items = [t.strip() for t in value.split(",") if t.strip()]
    return items or None


def _open(settings: Settings) -> tuple[Repository, DataGapHealerRepository]:
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    return repo, DataGapHealerRepository(repo.conn, schema=settings.db_schema)


def cmd_audit(args: argparse.Namespace, settings: Settings) -> int:
    repo, gap = _open(settings)
    try:
        gap.sync_dataset_registry(REGISTRY)
        if args.discover:
            missing = discover_unregistered_tables(repo.conn, settings.db_schema)
            print(
                json.dumps(
                    {"unregistered_tables": missing, "count": len(missing)}, indent=2
                )
            )
            return 1 if missing else 0

        start = _parse_date(args.start)
        end = _parse_date(args.end) if args.end else date.today()
        run_id, summaries, items = audit_into_run(
            repo,
            gap,
            settings.db_schema,
            start=start,
            end=end,
            datasets=_datasets_arg(args.datasets),
        )
        per = finalize_run(gap, run_id, summaries, items)
        _print_summary(args, run_id, items, per, header=f"audit window={start}..{end}")
        return 0
    finally:
        repo.conn.close()


def cmd_execute(args: argparse.Namespace, settings: Settings) -> int:
    if not args.confirm:
        logger.info(
            "DRY RUN — pass --confirm to heal. Use `audit` for a read-only scan."
        )
        return 0
    repo, gap = _open(settings)
    try:
        start = _parse_date(args.start)
        end = _parse_date(args.end) if args.end else date.today()
        run_id, outcome, budget, _, items = execute_into_run(
            repo,
            gap,
            settings,
            start=start,
            end=end,
            datasets=_datasets_arg(args.datasets),
            max_uw_calls=args.max_uw_calls,
            today=date.today(),
        )
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "outcome": outcome,
                    "budget_spent": budget.as_dict(),
                    "total_gaps": len(items),
                },
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        repo.conn.close()


def cmd_resume(args: argparse.Namespace, settings: Settings) -> int:
    repo, gap = _open(settings)
    try:
        outcome, budget = resume_run(
            repo,
            gap,
            settings,
            args.run_id,
            today=date.today(),
            max_uw_calls=args.max_uw_calls,
        )
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "outcome": outcome,
                    "budget_spent": budget.as_dict(),
                },
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        repo.conn.close()


def cmd_verify(args: argparse.Namespace, settings: Settings) -> int:
    repo, gap = _open(settings)
    try:
        result = verify_run(repo, gap, settings.db_schema, args.run_id)
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        repo.conn.close()


def cmd_verify_all(args: argparse.Namespace, settings: Settings) -> int:
    repo, gap = _open(settings)
    try:
        start = _parse_date(args.start)
        end = _parse_date(args.end) if args.end else date.today()
        evidence, paths = verify_all(
            repo,
            gap,
            settings,
            start=start,
            end=end,
            as_of=date.today(),
            out_dir=_OUTPUT_DIR,
            command="verify-all",
        )
        if args.json:
            print(json.dumps(evidence, indent=2, default=str))
        else:
            print(
                f"verify-all run #{evidence['run_id']}  total_gaps={evidence['total_gaps']}  "
                f"unregistered={evidence['unregistered_count']}"
            )
            print(f"  report: {paths['md']}")
        if args.fail_on_open_gaps and evidence["total_gaps"]:
            return 2
        return 0
    finally:
        repo.conn.close()


def _print_summary(args, run_id, items, per_dataset, *, header) -> None:
    if args.json:
        print(
            json.dumps(
                {"run_id": run_id, "total_gaps": len(items), "datasets": per_dataset},
                indent=2,
                default=str,
            )
        )
        return
    print(f"run #{run_id}  {header}  total_gaps={len(items)}")
    for name, d in sorted(
        per_dataset.items(), key=lambda kv: kv[1]["missing"], reverse=True
    ):
        if d["missing"]:
            print(
                f"  {name:<32} {d['audit_mode']:<18} missing={d['missing']:<6} "
                f"gap_days={d['gap_days']:<4} covered={d['covered']}/{d['expected']}"
            )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Argon data gap healer")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "audit", help="read-only exact-coverage audit (no provider calls)"
    )
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="")
    p.add_argument("--datasets", default="")
    p.add_argument(
        "--discover",
        action="store_true",
        help="list unregistered temporal tables, exit nonzero if any",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser(
        "execute", help="heal gaps (requires --confirm); only UW is capped"
    )
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="")
    p.add_argument("--datasets", default="")
    p.add_argument("--max-uw-calls", type=int, default=DEFAULT_MAX_UW_CALLS)
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=cmd_execute)

    p = sub.add_parser(
        "resume", help="continue planned/failed/skipped_budget items of a run"
    )
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--max-uw-calls", type=int, default=DEFAULT_MAX_UW_CALLS)
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("verify", help="recompute coverage for a run (read-only)")
    p.add_argument("--run-id", type=int, required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("verify-all", help="full audit + evidence artifact (read-only)")
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fail-on-open-gaps", action="store_true")
    p.set_defaults(func=cmd_verify_all)

    return ap


def main() -> int:
    args = build_parser().parse_args()  # before Settings so --help needs no env
    settings = Settings.from_env()
    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
