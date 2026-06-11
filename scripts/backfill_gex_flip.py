"""Backfill gex_snapshots.level_gex_flip_strike from stored payloads.

Issue #123: compute_gex_flip dropped negative→positive crossings above spot,
so short-gamma-regime rows persisted levels.gex_flip = null even though the
full per-strike profile (and spot) sit in the payload. This script recomputes
the flip with the fixed function and writes it back into payload.levels.
level_gex_flip_strike is GENERATED ALWAYS from the payload, so it updates
automatically.

Idempotent: only touches rows whose levels.gex_flip is currently null, and a
recomputation that still finds no crossing leaves the row untouched.

Usage:
    uv run python scripts/backfill_gex_flip.py [--dry-run] [--ticker SPX]
"""

from __future__ import annotations

import argparse
import json
import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.scanners.gex import compute_gex_flip

logger = logging.getLogger("backfill_gex_flip")

_SELECT = """
SELECT id, ticker, payload->'spot' AS spot, payload->'profile' AS profile
FROM {schema}.gex_snapshots
WHERE (payload->'levels'->'gex_flip' IS NULL
       OR jsonb_typeof(payload->'levels'->'gex_flip') = 'null')
  AND payload->'profile' IS NOT NULL
  AND payload->'spot' IS NOT NULL
  {ticker_clause}
ORDER BY id
"""

_UPDATE = """
UPDATE {schema}.gex_snapshots
SET payload = jsonb_set(payload, '{{levels,gex_flip}}', %s::jsonb)
WHERE id = %s
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    parser.add_argument("--ticker", default=None, help="restrict to one ticker")
    parser.add_argument("--batch", type=int, default=500, help="commit every N updates")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = Settings.from_env()
    conn = psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        dbname=settings.db_name,
    )
    schema = settings.db_schema

    ticker_clause = "AND ticker = %(ticker)s" if args.ticker else ""
    select_sql = _SELECT.format(schema=schema, ticker_clause=ticker_clause)
    update_sql = _UPDATE.format(schema=schema)

    read_cur = conn.cursor()
    read_cur.execute(select_sql, {"ticker": args.ticker} if args.ticker else {})
    rows = read_cur.fetchall()  # ~6K rows incl. profiles — fits in memory

    write_cur = conn.cursor()
    scanned = filled = still_none = skipped_thin = 0
    pending = 0
    for row_id, ticker, spot, profile in rows:
        scanned += 1
        if not profile or spot is None:
            skipped_thin += 1
            continue
        flip = compute_gex_flip(profile, float(spot))
        if flip is None:
            still_none += 1
            continue
        flip_obj = {
            "strike": flip,
            "gamma": 0.0,
            "distance": round(flip - float(spot), 2),
            "distance_pct": round((flip - float(spot)) / float(spot) * 100, 2),
        }
        filled += 1
        if args.dry_run:
            continue
        write_cur.execute(update_sql, (json.dumps(flip_obj), row_id))
        pending += 1
        if pending >= args.batch:
            conn.commit()
            pending = 0
            logger.info("progress: scanned=%d filled=%d (%s)", scanned, filled, ticker)
    if not args.dry_run and pending:
        conn.commit()
    conn.close()
    logger.info(
        "done%s: scanned=%d filled=%d no_crossing=%d thin=%d",
        " (dry-run)" if args.dry_run else "",
        scanned,
        filled,
        still_none,
        skipped_thin,
    )


if __name__ == "__main__":
    main()
