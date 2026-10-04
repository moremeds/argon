#!/usr/bin/env python
"""Backfill sector_rs_daily over a date range.

This is the §6 research trace, and the heal for this table: the table is not
healer-enrolled (spec 2026-09-26 §5). It uses the same core as the nightly job
(worker/jobs/sector_rs_daily.run_sector_rs), so a backfilled row and a nightly
row for one session are the same row.

Resumable: sessions already holding rows of a group_kind are skipped unless
--force. Work is chunked (--chunk-sessions, default 125, about 6 months) and
every chunk commits, so an interrupted run resumes at the first missing chunk.
Cost: the full default range is about 7,000 sessions (1998-12-22 → present).
Each chunk makes one bulk call for SPY plus three for the ~514 other symbols
(503 S&P names + 11 ETFs, 200 per call), so about 56 chunks × 4 calls at the
default --chunk-sessions 125. Each call spans the chunk plus a 400-day
lookback; the apex session measured about 4 s per 200 symbols over a year.
Zero UW spend.

SURVIVORSHIP, by ruling (spec §4): gics membership is the vendored CURRENT
S&P 500 list (src/uw_scan/sources/data/sp500_members.json, copied from
livewire presets/sp500.json) applied to every historical session. apex's
point-in-time membership is defective and not used. Former members are
therefore absent from n_members, and a delisted name has no adjusted bars
(apex files it under `missing`), so it is unpriced. Breadth history describes
today's index, not the index of the day. Chain rows likewise carry TODAY's
watchlist_chain membership (no history exists). The run's log line repeats
this next to its n_priced / n_members totals.

ETF history (livewire #157, 2026-09-27): the nine 1998 funds start
1998-12-22, XLRE 2015-10-08, XLC 2018-06-19. rs_12m is NULL and the row
degraded for each fund's first 252 sessions, by construction. Breadth on the
current list also thins going back (survivorship); the §6 probe's
effective-start rule handles that.

PRE-FLIGHT: when the range reaches back before the 2021-05-18 seed and the
gics kind is requested, the script first asks apex for adjusted bars for
1999-01-04..08 for each of the nine 1998 funds. It aborts naming the funds
with none, because Silver has not yet published their #157 history (on
2026-09-27 that was XLK XLY XLB XLU XLE; livewire is fixing the seam cut).

Reproduce (on the mini, after migration 152 and the nightly Silver rebuild):
    uv run python scripts/backfill/sector_rs_backfill.py --start 1998-12-22 --end 2026-09-25
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone
from functools import partial

import httpx
import psycopg

from uw_scan.config import Settings
from uw_scan.sources.apex import fetch_bars, fetch_bulk_daily_closes
from uw_scan.storage.repository import Repository
from uw_scan.storage.sector_rs import SectorRsRepository
from uw_scan.worker.jobs.sector_rs_daily import (
    BENCHMARK,
    GROUP_KINDS,
    load_closes,
    run_sector_rs,
)

log = logging.getLogger("sector_rs_backfill")

#: First bronze bar of the nine 1998 SPDR funds after livewire #157 (spec §4).
DEFAULT_START = date(1998, 12, 22)
#: The ETF seed before #157 (XLF 2021-05-18). A range starting on or after it
#: does not need the pre-flight.
PRE_157_SEED = date(2021, 5, 18)
_PREFLIGHT_START = date(1999, 1, 4)
_PREFLIGHT_END = datetime(1999, 1, 8, 23, 59, 59, tzinfo=timezone.utc)
#: The nine funds launched 1998-12-16; XLRE and XLC start later and are not checked.
_FUNDS_1998: tuple[str, ...] = (
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
)


def pending_sessions(
    sessions: list[date], present: set[date], force: bool
) -> list[date]:
    """Sessions still to compute: all of them with --force, else the absent ones."""
    return list(sessions) if force else [s for s in sessions if s not in present]


def chunked(items: list[date], size: int) -> list[list[date]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


def preflight_etf_history(base_url: str, client: httpx.Client | None = None) -> None:
    """Abort unless apex serves ADJUSTED bars for the first week of 1999 for
    every 1998 fund.

    Silver, which price_mode=adjusted reads, cut five of the nine funds back to
    2021-06-11 on its first #157 rebuild (spec §4). Before the fix lands, a
    backfill would write about 5,600 gics sessions with NULL rs and
    degraded=true for those sectors, and they would look like data. fetch_bars
    sends price_mode=adjusted for equity. An apex outage raises
    SourceUnavailable out of here, so it aborts too.
    """
    missing = [
        s
        for s in _FUNDS_1998
        if not fetch_bars(
            s,
            "1d",
            _PREFLIGHT_START,
            base_url=base_url,
            end=_PREFLIGHT_END,
            client=client,
        )
    ]
    if missing:
        raise SystemExit(
            "Silver has not published the #157 history yet (apex returned no adjusted "
            f"bars for 1999-01-04..08 for {' '.join(missing)}); run after livewire's fix"
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(description="Backfill uw_scan.sector_rs_daily")
    p.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--group-kind", choices=GROUP_KINDS, action="append", dest="kinds")
    p.add_argument(
        "--force", action="store_true", help="recompute sessions already present"
    )
    p.add_argument("--chunk-sessions", type=int, default=125)
    args = p.parse_args()
    kinds = tuple(args.kinds or GROUP_KINDS)

    settings = Settings.from_env()
    if "gics" in kinds and args.start < PRE_157_SEED:
        preflight_etf_history(settings.apex_api_url)

    fetch_closes = partial(fetch_bulk_daily_closes, base_url=settings.apex_api_url)
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        spy, _ = load_closes(
            repo,
            [BENCHMARK],
            start=args.start,
            end=args.end,
            fetch_closes=fetch_closes,
        )
        sessions = [d for d, _ in spy.get(BENCHMARK, []) if args.start <= d <= args.end]
        if not sessions:
            log.error(
                "no %s sessions in %s..%s; nothing to do",
                BENCHMARK,
                args.start,
                args.end,
            )
            return 1
        store = SectorRsRepository(conn, schema=settings.db_schema)
        for kind in kinds:
            todo = pending_sessions(
                sessions, store.dates_present(kind, args.start, args.end), args.force
            )
            log.info("%s: %d of %d sessions to compute", kind, len(todo), len(sessions))
            for chunk in chunked(todo, args.chunk_sessions):
                counters = run_sector_rs(
                    repo=repo,
                    schema=settings.db_schema,
                    dates=chunk,
                    group_kinds=(kind,),
                    fetch_closes=fetch_closes,
                )
                log.info("%s %s..%s %s", kind, chunk[0], chunk[-1], counters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
