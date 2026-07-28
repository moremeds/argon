#!/usr/bin/env python
"""Replay Theta Harvester candidates over history, then score their markouts.

MANDATORY after first deploy or any wipe. The nightly markout job only SCORES
existing candidate rows — without this backfill the markout table stays empty
for weeks and every read looks like "no signal" rather than "no data". The
skew engine shipped with exactly this gap; do not repeat it.

Coverage floor is `option_surface_grid_daily` alone (2025-12-26 on the mini as
of 2026-07-29), NOT its intersection with `exposures_by_expiry_strike`.
Requiring GEX would drop the replay from 116 usable entry sessions to 24,
because the strike-level GEX feed only starts 2026-05 — and the dealer-support
gate is non-critical by default (`ScoreWeights.dealer_gate_critical=False`)
precisely so that history is not thrown away for an unvalidated gate. Sessions
without GEX still score; they record `dealer_support='UNKNOWN'` and a failed
`gate_dealer_support`, which the sweep can filter on if it wants to.

Reproduce:
    uv run python scripts/backfill/theta_harvester_backfill.py \
        --start 2025-12-26 --end 2026-07-27
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.theta_harvester_markout import run_theta_markout
from uw_scan.storage.repository import Repository
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository
from uw_scan.worker.jobs.theta_harvester import theta_harvester_scan

log = logging.getLogger("theta_backfill")

# The IV grid's first session. GEX is deliberately NOT part of the floor.
DEFAULT_START = date(2025, 12, 26)


def _eligible_pairs(
    conn: psycopg.Connection, schema: str, start: date, end: date
) -> dict[date, list[str]]:
    """(session -> tickers) that have an IV surface capture and are watchlisted.

    Per-ticker, not per-date: a date-level EXISTS check would qualify a whole
    session because one ticker happened to have data, and every other ticker
    would then be scanned against nothing.

    GEX is intentionally NOT required — see the module docstring. A ticker with
    no GEX on the session scores with dealer_support='UNKNOWN'.

    SURVIVORSHIP CAVEAT, stated because it cannot be fixed here: the universe
    is intersected against today's `watchlist WHERE removed_at IS NULL`. Names
    removed from the watchlist during the replay window are absent, and names
    added recently are replayed over sessions when they were not being tracked.
    argon does not store watchlist membership history, so this is a bias the
    backfill carries, not one it can correct. It runs in the optimistic
    direction: a name removed after a drawdown is exactly the kind of row whose
    losses are missing. The resolved universe is logged so the measurement can
    be re-read later against a frozen list.
    """
    sql = f"""
        SELECT g.market_date, g.ticker
          FROM (
              SELECT DISTINCT market_date, ticker
                FROM {schema}.option_surface_grid_daily
               WHERE market_date BETWEEN %s AND %s
          ) g
          JOIN {schema}.watchlist w
            ON w.ticker = g.ticker AND w.removed_at IS NULL
         ORDER BY 1, 2
    """
    out: dict[date, list[str]] = {}
    for d, tk in conn.execute(sql, (start, end)).fetchall():
        out.setdefault(d, []).append(tk)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--ticker", action="append", dest="tickers")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        th = ThetaHarvesterRepository(conn, schema=settings.db_schema)
        pairs = _eligible_pairs(conn, settings.db_schema, args.start, args.end)
        sessions = sorted(pairs)
        if not sessions:
            log.error(
                "no (ticker, session) pairs with surface coverage in %s..%s",
                args.start,
                args.end,
            )
            return 1
        universe = sorted({t for v in pairs.values() for t in v})
        log.info(
            "%d covered sessions: %s .. %s (%d ticker-sessions, %d distinct tickers)",
            len(sessions),
            sessions[0],
            sessions[-1],
            sum(len(v) for v in pairs.values()),
            len(universe),
        )
        # Logged in full so the replay universe is recoverable later — the
        # survivorship caveat above is only auditable if the list is recorded.
        log.info("resolved universe: %s", ",".join(universe))
        if args.dry_run:
            for d in sessions[:3] + sessions[-3:]:
                log.info("  %s -> %d eligible tickers", d, len(pairs[d]))
            return 0

        total = 0
        for session in sessions:
            eligible = pairs[session]
            if args.tickers:
                wanted = {t.upper() for t in args.tickers}
                eligible = [t for t in eligible if t in wanted]
                if not eligible:
                    continue
            out = theta_harvester_scan(
                repo=repo, settings=settings, as_of=session, tickers=eligible
            )
            total += out["candidates_written"]
            log.info(
                "%s scanned=%d written=%d harvest=%d",
                session,
                out["tickers_scanned"],
                out["candidates_written"],
                out["harvest_count"],
            )

        marks = run_theta_markout(repo=th)
        log.info("backfill complete: %d candidates, %s", total, marks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
