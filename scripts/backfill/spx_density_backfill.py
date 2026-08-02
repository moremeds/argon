"""Seed origin='reconstructed' spx_density_forecast history (spec §5: in-sample rows,
badged and tallied separately from prospective).

Each historical as_of reuses compute_forecast's as_of truncation, so the seed is the
v13 panel-index convention — bit-faithful to what the model would have issued that night.
Settles all rows at the end.

Usage:
  uv run python scripts/backfill/spx_density_backfill.py --sessions 60 [--dry-run]
Persists to Postgres (uw_scan.spx_density_forecast) — the durable trace IS the table.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from typing import AbstractSet, Sequence

import psycopg

from uw_scan.config import Settings
from uw_scan.density.constants import PANEL_FIRST_DATE
from uw_scan.density.forecast import (
    PanelMismatchError,
    compute_forecast,
    result_to_db_rows,
)
from uw_scan.storage.spx_density_repository import SpxDensityRepository
from uw_scan.worker.jobs.spx_density_forecast import _settle_pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("spx_density_backfill")


def select_sessions(
    candidates: Sequence[date],
    *,
    existing: AbstractSet[date],
    prospective: AbstractSet[date],
) -> list[date]:
    """Which candidate sessions this backfill may write.

    `existing` is empty under --force, which is the point of the flag: recompute rows we
    already have. `prospective` is NOT, ever. upsert_rows updates `origin` on conflict, so
    recomputing a session the nightly job issued forward would rewrite it to
    'reconstructed' and move a genuinely out-of-sample cone into the in-sample tally —
    quietly inflating the only honest hit-rate number on the page. A row the model
    published forward is not something a backfill may relabel.
    """
    return [d for d in candidates if d not in existing and d not in prospective]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help=(
            "Recompute sessions that already have rows. Needed after a migration adds "
            "a column derived from the same run (e.g. 112's density_bins_jsonb left "
            "every existing row NULL). Deterministic: seed_for(i) is panel-index "
            "arithmetic, so a recompute reproduces the identical cone. Sessions the "
            "nightly job issued prospectively are skipped even under --force."
        ),
    )
    args = ap.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        sdr = SpxDensityRepository(conn, schema=settings.db_schema)
        bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
        if len(bars) < 2:
            log.error(
                "no SPX series in vol_index_daily — run vol_index_lake_sync first"
            )
            return 1

        existing = (
            set() if args.force else set(sdr.fetch_recent_as_ofs(args.sessions + 10))
        )
        prospective = sdr.fetch_as_ofs_with_origin("prospective")
        # candidates: the last N session dates, excluding the freshest (that one is the
        # nightly job's prospective anchor, never the backfill's)
        candidates = [d for d, _ in bars[-(args.sessions + 1) : -1]]
        writable = select_sessions(
            candidates, existing=existing, prospective=prospective
        )
        skipped = len(candidates) - len(writable)
        wrote = 0
        for as_of in writable:
            try:
                result = compute_forecast(bars, as_of=as_of)
            except PanelMismatchError as exc:
                log.error("REFUSING (%s): %s", as_of, exc)
                return 1
            if args.dry_run:
                log.info("would write %s (fallback=%s)", as_of, result.fallback_used)
                continue
            sdr.upsert_rows(result_to_db_rows(result, origin="reconstructed"))
            wrote += 1
            log.info(
                "wrote %s seed=%d fallback=%s", as_of, result.seed, result.fallback_used
            )

        settled = 0 if args.dry_run else _settle_pass(sdr)
        log.info("done: wrote=%d skipped=%d settled=%d", wrote, skipped, settled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
