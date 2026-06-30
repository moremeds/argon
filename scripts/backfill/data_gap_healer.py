"""Data gap healer CLI: detect (audit) and — in later milestones — heal exact
warm-store gaps. Audit is read-only and makes ZERO provider calls.

Reproduce (dry audit against the mini, no provider calls):
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    uv run python scripts/backfill/data_gap_healer.py audit \\
      --start 2026-01-01 --end 2026-06-29

Discovery gate (nonzero if any temporal table is unregistered):
  uv run python scripts/backfill/data_gap_healer.py audit --discover
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    audit,
    discover_unregistered_tables,
)
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_gap_healer")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _datasets_arg(value: str) -> list[str] | None:
    items = [t.strip() for t in value.split(",") if t.strip()]
    return items or None


def cmd_audit(args: argparse.Namespace, settings: Settings) -> int:
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    gap = DataGapHealerRepository(repo.conn, schema=settings.db_schema)
    try:
        gap.sync_dataset_registry(REGISTRY)

        if args.discover:
            missing = discover_unregistered_tables(repo.conn, settings.db_schema)
            payload = {"unregistered_tables": missing, "count": len(missing)}
            print(json.dumps(payload, indent=2))
            if missing:
                logger.warning(
                    "%d temporal table(s) unregistered: %s",
                    len(missing),
                    ", ".join(missing),
                )
                return 1
            logger.info("discovery: all temporal tables registered")
            return 0

        start = _parse_date(args.start)
        end = _parse_date(args.end) if args.end else date.today()
        datasets = _datasets_arg(args.datasets) if args.datasets else None
        active = [c.ticker for c in repo.list_watchlist_cards()]
        caveats = gap.list_caveats()

        summaries, items = audit(
            repo.conn,
            settings.db_schema,
            REGISTRY,
            active,
            caveats,
            start,
            end,
            datasets,
        )

        run_id = gap.create_run(
            mode="audit",
            start_date=start,
            end_date=end,
            datasets=datasets or [],
        )
        gap.upsert_items(run_id, items)
        per_dataset = {
            s.dataset: {
                "audit_mode": s.audit_mode,
                "expected": s.expected_pairs,
                "covered": s.covered_pairs,
                "missing": s.missing_pairs,
                "gap_days": len(s.gap_dates),
            }
            for s in summaries
        }
        gap.finish_run(
            run_id,
            status="complete",
            summary={
                "datasets": per_dataset,
                "total_gaps": len(items),
                "active_tickers": len(active),
            },
        )

        if args.json:
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "total_gaps": len(items),
                        "datasets": per_dataset,
                    },
                    indent=2,
                    default=str,
                )
            )
        else:
            print(
                f"audit run #{run_id}  active_tickers={len(active)}  "
                f"window={start}..{end}  total_gaps={len(items)}"
            )
            for s in sorted(summaries, key=lambda x: x.missing_pairs, reverse=True):
                if s.missing_pairs:
                    print(
                        f"  {s.dataset:<32} {s.audit_mode:<18} "
                        f"missing={s.missing_pairs:<6} "
                        f"gap_days={len(s.gap_dates):<4} covered={s.covered_pairs}/{s.expected_pairs}"
                    )
        return 0
    finally:
        repo.conn.close()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Argon data gap healer")
    sub = ap.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser(
        "audit", help="read-only exact-coverage audit (no provider calls)"
    )
    audit_p.add_argument("--start", default="2026-01-01", help="ISO start date")
    audit_p.add_argument("--end", default="", help="ISO end date (default: today)")
    audit_p.add_argument(
        "--datasets", default="", help="comma list; default = all registered"
    )
    audit_p.add_argument(
        "--discover",
        action="store_true",
        help="list unregistered temporal tables and exit nonzero if any",
    )
    audit_p.add_argument("--json", action="store_true", help="machine-readable output")
    audit_p.set_defaults(func=cmd_audit)

    return ap


def main() -> int:
    args = build_parser().parse_args()  # before Settings so --help needs no env
    settings = Settings.from_env()
    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
