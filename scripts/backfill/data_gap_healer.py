"""Data gap healer CLI: detect (audit), heal (execute/resume), and report
(verify / verify-all). Thin argparse wrapper over the orchestration core in
`uw_scan.worker.jobs.data_gap_healer`. Audit + verify are read-only (ZERO
provider calls); only `execute`/`resume` spend budget, and only UW is capped.

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

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.data_gap_healer import REGISTRY, discover_unregistered_tables
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.storage.repository import Repository

# re-exported so the importlib-loaded CLI tests can call the core directly
from uw_scan.worker.jobs.data_gap_healer import (  # noqa: F401
    OUTPUT_DIR,
    HealerBusy,
    audit_into_run,
    execute_into_run,
    finalize_run,
    per_dataset_summary,
    reconcile_watchlist_lifecycle,
    resume_run,
    verify_all,
    verify_run,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_gap_healer_cli")

DEFAULT_MAX_UW_CALLS = 20000


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _datasets_arg(value: str) -> list[str] | None:
    items = [t.strip() for t in value.split(",") if t.strip()]
    return items or None


def _open(settings: Settings) -> tuple[Repository, DataGapHealerRepository]:
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    return repo, DataGapHealerRepository(repo.conn, schema=settings.db_schema)


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


def _warn_if_spine_degraded(conn, schema: str, start: date, end: date) -> None:
    """Print a loud banner when the reference calendar lost sessions.

    The union in `_calendar_dates` keeps THIS audit correct, but every other
    report that reads market_tide_sentiment_daily is still blind until the
    reference itself is rebuilt.
    """
    from uw_scan.reports.data_gap_healer import _REFERENCE_CALENDAR, spine_health

    health = spine_health(conn, schema, start, end)
    if not health.missing_from_ref:
        return
    ref_name = _REFERENCE_CALENDAR[0]
    print(
        f"!! SPINE DEGRADED: {ref_name} is missing "
        f"{len(health.missing_from_ref)} session(s) the SPY witness has: "
        + ", ".join(d.isoformat() for d in health.missing_from_ref)
    )
    print(
        "!! The union keeps this audit correct, but rebuild the reference "
        "before trusting any OTHER report:\n"
        "     uv run python scripts/backfill/market_tide_backfill.py "
        "--confirm --sessions 10\n"
        "     uv run python scripts/backfill/market_tide_sentiment_backfill.py"
    )


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
        _warn_if_spine_degraded(repo.conn, settings.db_schema, start, end)
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
        print(
            json.dumps(
                verify_run(repo, gap, settings.db_schema, args.run_id),
                indent=2,
                default=str,
            )
        )
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
            out_dir=OUTPUT_DIR,
            command="verify-all",
        )
        if args.json:
            print(json.dumps(evidence, indent=2, default=str))
        else:
            print(
                f"verify-all run #{evidence['run_id']}  "
                f"total_gaps={evidence['total_gaps']}  "
                f"unregistered={evidence['unregistered_count']}"
            )
            print(f"  report: {paths['md']}")
        if args.fail_on_open_gaps and evidence["total_gaps"]:
            return 2
        return 0
    finally:
        repo.conn.close()


def cmd_reconcile(args: argparse.Namespace, settings: Settings) -> int:
    repo, gap = _open(settings)
    try:
        result = reconcile_watchlist_lifecycle(repo, gap, date.today())
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        repo.conn.close()


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

    p = sub.add_parser(
        "reconcile", help="log watchlist add/remove deltas (added -> backfilled)"
    )
    p.set_defaults(func=cmd_reconcile)

    return ap


def main() -> int:
    args = build_parser().parse_args()  # before Settings so --help needs no env
    settings = Settings.from_env()
    try:
        return args.func(args, settings)
    except HealerBusy as exc:
        # The nightly job, the freshness autoheal, or another operator holds the
        # single-flight lock. Refusing is the point: racing it would re-audit the
        # same still-missing gaps and heal them twice, double-charging the
        # provider budget. Exit 2 so a wrapper can tell "busy" from "broken".
        logger.error("refusing to start: %s", repr(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
