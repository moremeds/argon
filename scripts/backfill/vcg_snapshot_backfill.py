#!/usr/bin/env python
"""Backfill `vcg_snapshots` (basis='eod') across the full aligned lake history.

VCG needs no external API — `scanners/vcg.run(as_of=...)` reads VIX/VVIX and the
credit proxy straight out of `vol_index_daily`. So every session for which those
three series align can be scored offline, at zero UW/API cost.

Depth is bounded by the shortest input series: HYG starts 2007-04-11 (VVIX 2006,
VIX 1990), and scoring needs MIN_BARS = OLS_WINDOW + Z_WINDOW + 10 = 94 aligned
bars of warmup, so the first scoreable date lands ~94 sessions after the proxy's
first bar.

**Chunked by year on purpose.** `scanners/vcg.recover_recent_gaps` rolls back on
a per-date exception but `run()` never commits, so across thousands of dates one
late failure would silently discard every earlier insert while still reporting
them as filled. Committing per year bounds that blast radius to one year and
makes the per-chunk counts an honest progress record.

Idempotent: `recover_recent_gaps` skips dates that already have a snapshot, so
re-running only fills genuine holes.

Reproduce:
    uv run python scripts/backfill/vcg_snapshot_backfill.py                # all proxies present in the lake
    uv run python scripts/backfill/vcg_snapshot_backfill.py --proxy HYG
    uv run python scripts/backfill/vcg_snapshot_backfill.py --since 2020-01-01 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.scanners import vcg
from uw_scan.storage.vol_index_repository import VolIndexRepository

log = logging.getLogger("vcg_backfill")


def aligned_span(
    conn: psycopg.Connection, proxy: str, schema: str
) -> tuple[date, date, int] | None:
    """(first, last, count) of dates where VIX, VVIX and `proxy` all have a bar."""
    repo = VolIndexRepository(conn, schema=schema)
    common = (
        repo.fetch_dates_for("VIX")
        & repo.fetch_dates_for("VVIX")
        & repo.fetch_dates_for(proxy)
    )
    if not common:
        return None
    days = sorted(common)
    return days[0], days[-1], len(days)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="HYG", help="credit proxy (default HYG)")
    ap.add_argument("--since", help="earliest date to fill, YYYY-MM-DD")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report the span and existing coverage, write nothing",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    settings = Settings.from_env()
    proxy = args.proxy.upper()
    schema = settings.db_schema

    with psycopg.connect(settings.db_dsn()) as conn:
        span = aligned_span(conn, proxy, schema)
        if span is None:
            log.error("no aligned VIX/VVIX/%s dates in vol_index_daily", proxy)
            return 1
        first, last, n = span
        log.info("aligned span for %s: %s -> %s (%d sessions)", proxy, first, last, n)

        floor = date.fromisoformat(args.since) if args.since else first
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(DISTINCT data_date) FROM {schema}.vcg_snapshots "
                "WHERE basis = 'eod' AND credit_proxy = %s",
                (proxy,),
            )
            have = cur.fetchone()[0]
        log.info("existing eod snapshot dates for %s: %d", proxy, have)

        if args.dry_run:
            log.info("dry-run: would fill from %s to %s", floor, last)
            return 0

        total_filled = total_skipped = 0
        # One chunk per calendar year, committed independently.
        for year in range(floor.year, last.year + 1):
            # lookback_days is measured back from the LATEST aligned date, so
            # widen the window to this year's start and let the already-have
            # filter drop everything newer that is already done.
            lookback = (last - max(floor, date(year, 1, 1))).days
            if lookback <= 0:
                continue
            try:
                res = vcg.recover_recent_gaps(
                    conn, schema=schema, proxy=proxy, lookback_days=lookback
                )
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                log.error("chunk %d failed, rolled back: %r", year, exc)
                continue
            total_filled += res["filled"]
            total_skipped += res["skipped"]
            log.info(
                "chunk %d: checked=%d filled=%d skipped=%d",
                year,
                res["checked"],
                res["filled"],
                res["skipped"],
            )

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(DISTINCT data_date), min(data_date), max(data_date) "
                f"FROM {schema}.vcg_snapshots "
                "WHERE basis = 'eod' AND credit_proxy = %s",
                (proxy,),
            )
            dates, lo, hi = cur.fetchone()
        log.info(
            "done proxy=%s filled=%d skipped=%d | now %d dates %s -> %s",
            proxy,
            total_filled,
            total_skipped,
            dates,
            lo,
            hi,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
