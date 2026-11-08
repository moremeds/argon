"""Recompute pcr_history.pcr_oi as put OI / call OI for rows before --before.

Before the 2026-11-08 fix the scan stored UW's screener ``put_call_ratio``
(put VOLUME / call volume per UW's spec) as ``pcr_oi``, so every older row is a
copy of ``pcr_vol``. This rewrites those rows from ``options_volume_daily``;
rows with no OI session within --max-lag-days are set NULL. Dry run by default.

Reproduce:
  uv run python scripts/backfill/pcr_history_oi_repair.py --before 2026-11-09
  uv run python scripts/backfill/pcr_history_oi_repair.py --before 2026-11-09 --apply

Pass the day AFTER the deploy as --before. Rows on the deploy day itself may
still hold the old value when the deploy landed after that day's last scan.
For rows the fixed scan wrote, the repair recomputes the same OI ratio, so a
later cutoff is safe; an earlier one leaves volume ratios behind.
"""

from __future__ import annotations

import argparse
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


def main(argv: list[str] | None = None) -> dict[str, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=date.fromisoformat)
    parser.add_argument("--max-lag-days", type=int, default=4)
    parser.add_argument(
        "--apply", action="store_true", help="commit (default: dry run)"
    )
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        counts = repo.repair_pcr_history_oi(
            before=args.before, max_lag_days=args.max_lag_days, apply=args.apply
        )
    print({"apply": args.apply, "before": args.before.isoformat(), **counts})
    return counts


if __name__ == "__main__":
    main()
