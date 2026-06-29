"""Backfill the spot (SPY) price line onto market_tide_snapshots.

UW's market-tide feed has no price, and the live worker only stamps spot on the
bars it captures in real time — so backfilled/historical sessions have a NULL
`spot` column and the chart's gold SPY line is missing. This joins Apex's
EOD-synced SPY 5-min closes onto those bars by exact UTC instant and UPDATEs the
column. Idempotent: only touches rows where spot IS NULL. Persists per session.

Apex (not UW) is the source — set APEX_API_URL to override (default = mini over
Tailscale). Today's live bars are NOT backfilled here (the worker stamps those
from the WS feed); Apex has no live bars anyway.

Reproduce (all sessions with a NULL spot):
  uv run python scripts/backfill/market_tide_spot_backfill.py

  # limit to recent sessions / a different overlay ticker:
  uv run python scripts/backfill/market_tide_spot_backfill.py --sessions 5 --ticker SPY
"""

from __future__ import annotations

import argparse
import logging
from datetime import timezone

import psycopg

from uw_scan.config import Settings
from uw_scan.sources import apex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_tide_spot_backfill")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ticker", default="SPY", help="overlay price ticker (default SPY)"
    )
    ap.add_argument(
        "--sessions",
        type=int,
        default=0,
        help="only the N most recent sessions with a NULL spot (0 = all)",
    )
    args = ap.parse_args()

    settings = Settings.from_env()
    schema = settings.db_schema
    conn = psycopg.connect(settings.db_dsn())
    total_updated = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT data_date FROM {schema}.market_tide_snapshots "
                f"WHERE spot IS NULL ORDER BY data_date DESC"
            )
            dates = [r[0] for r in cur.fetchall()]
        if args.sessions > 0:
            dates = dates[: args.sessions]
        if not dates:
            logger.info("nothing to backfill — no sessions with a NULL spot")
            return 0

        for d in dates:
            closes = apex.fetch_intraday_closes(d, ticker=args.ticker)
            if not closes:
                logger.info("no apex bars for %s — leaving spot NULL", d)
                continue
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, ts FROM {schema}.market_tide_snapshots "
                    f"WHERE data_date = %s AND spot IS NULL",
                    (d,),
                )
                rows = cur.fetchall()
                updated = 0
                for row_id, ts in rows:
                    inst = ts.astimezone(timezone.utc)
                    close = closes.get(inst)
                    if close is None:
                        continue
                    cur.execute(
                        f"UPDATE {schema}.market_tide_snapshots "
                        f"SET spot = %s, spot_ticker = %s WHERE id = %s",
                        (close, args.ticker.upper(), row_id),
                    )
                    updated += 1
            conn.commit()
            total_updated += updated
            logger.info("%s: matched %d/%d bars", d, updated, len(rows))

        logger.info("backfill complete: %d bars stamped with spot", total_updated)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
