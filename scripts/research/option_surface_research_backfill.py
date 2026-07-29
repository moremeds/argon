#!/usr/bin/env python
"""Backfill the option-surface grid for a sector-balanced research cohort.

WHY THIS EXISTS
---------------
The theta-harvester studies all run on `option_surface_grid_daily`, which covers
exactly the 114 watchlist tickers. That watchlist is AI/semiconductor heavy, and
the 2026-07-29 loss-anatomy study showed the consequence: 79% of the measured
loss came from 31% of the trades, all expressing one theme, while the other 54%
of trades were flat (+0.00002/trade over 7,374 trades). Every conclusion drawn so
far is therefore partly a statement about watchlist composition.

This backfill adds a cohort chosen to counterweight that: 37 names that are BOTH
large ($30B+) and genuinely liquid in options (200k+ open interest), deduped
against the watchlist and spread over 10 sectors. See the SELECTION comment on
RESEARCH_UNIVERSE for why both filters are required.

    uv run python scripts/research/option_surface_research_backfill.py --seed-only
    uv run python scripts/research/option_surface_research_backfill.py

RUNNING THIS BY HAND IS USUALLY UNNECESSARY
-------------------------------------------
`option_surface_research_catchup` (03:20 ET) does the same fill automatically, a
bounded batch per night, and stops when the window is complete. This script is
the manual lever: seeding a new cohort, or filling the window in one sitting
rather than over ~6 nights. Both share the same core, so they cannot drift.

WHY NOT JUST ADD THEM TO THE WATCHLIST
--------------------------------------
`watchlist` membership enlists a ticker in every per-ticker scheduled job, so 37
names would permanently raise the DAILY UW burn — roughly +32% on a ~114-name
watchlist — to buy a one-time backfill. It would also hand the cohort to the data
gap healer, whose denominator is "watchlist tickers x sessions" and which fetches
the FULL chain every session: ~78,600 calls against ~7,950 here. The healer is
right to do that — its job is a complete dataset, not a sampled study. The cohort
lives in `uw_scan.research_universe` (migration 110) precisely so research
sampling cannot silently promote itself to production completeness.

COST
----
One UW call per (ticker, expiry) plus one per (ticker, session). Measured on the
existing grid: ~17.3 expiries per ticker-session unclipped, ~7.6 capped at 60 DTE.

    37 tickers x 25 weekly sessions x ~8.6 calls  ~=  7,950 UW calls

against a 120k/day account budget. Two deliberate economies:

* WEEKLY sampling, not daily. With ~30-day holds consecutive daily entries
  overlap ~95% and are not independent observations — the weight sweep already
  equal-weights by month for exactly this reason. Weekly costs a fifth and loses
  little.
* DTE CAP of 60. The strategy trades 7-45 DTE; the rest of the term structure is
  paid for and unused.

`--max-calls` is a PER-RUN budget (default 8000) that stops cleanly and resumes on
the next invocation, because already-captured tickers are skipped. It is
deliberately not keyed on UW's daily counter: that value comes from response
headers, is None until the first success, and sits wherever the account already
happens to be — measured 109,089/120,000 by midday on 2026-07-29. A guard on it
either never fires or fires immediately.

CHECK THE ACCOUNT BUDGET BEFORE A FULL RUN. The account counter resets 20:00 ET:

    SELECT max(official_daily_count), max(official_daily_limit)
      FROM uw_scan.external_api_requests
     WHERE provider='uw' AND request_started_at > now() - interval '24 hours';

KNOWN GAP CARRIED FORWARD
-------------------------
Like the watchlist backfill, this writes `underlying_spot = NULL` — UW's greeks
payload does not carry the underlying, and `daily_ohlc` is back-adjusted while
the strikes are as-traded, so filling it from OHLC would inject the very scale
seam the entry guard exists to reject. Downstream `load_spot` already handles the
NULL via its strike-range guard. Do not "fix" this by joining daily_ohlc.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date as _date

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_surface_research_catchup import (
    CALLS_PER_TICKER_SESSION,
    MAX_DTE,
    fill_pairs,
    missing_pairs,
    weekly_sessions,
)

log = logging.getLogger("surface_research_backfill")

COHORT = "liquid_sector_balanced_v1"
SOURCE = (
    "uw_stock_screener, pooled marketcap-desc + total_open_interest-desc pages; "
    "Common Stock, marketcap>=$30B AND total_open_interest>=200k; "
    "top 5 per sector by OI, deduped against the watchlist"
)
SELECTED_ON = _date(2026, 7, 29)

# SELECTION — why both filters, and why neither alone works.
#
# Ranking large caps by MARKET CAP alone produced a cohort whose options are
# untradeable: EQIX 18k / SHW 25k / RY 32k total OI against a watchlist median of
# 657k, i.e. 20-35x thinner. A short-premium study there would be measuring
# instruments you could not get filled in, and bid-ask is already the largest
# unmodelled cost in these studies.
#
# Ranking by OPTION OI alone swapped one bias for another: the top of that list
# is retail/meme names (GME, BYND, HTZ, PLUG, RIVN) — liquid, but no more
# representative than the AI complex it was meant to counterweight.
#
# So: marketcap >= $30B AND total_open_interest >= 200k, then top 5 per sector by
# OI. 37 names over 10 sectors.
#
# REAL ESTATE IS ABSENT AND THAT IS A RESULT, NOT AN OMISSION. No REIT clears both
# bars at any size — liquid single-name real-estate options effectively do not
# exist. If the sector must be represented, it has to be via XLRE, which is an
# index bet rather than a single-name one and does not belong in this cohort.
#
# Market caps and OI are as of SELECTED_ON and drift; they are stored for
# provenance, not used as a live filter.
RESEARCH_UNIVERSE: tuple[tuple[str, str, int, int], ...] = (
    ("FCX", "Basic Materials", 88611190079, 1067064),
    ("NEM", "Basic Materials", 96433916642, 493643),
    ("GOOG", "Communication Services", 1879382770000, 1715539),
    ("NFLX", "Communication Services", 301427593146, 5446552),
    ("T", "Communication Services", 168979830129, 1116687),
    ("VZ", "Communication Services", 201220183873, 1093013),
    ("WBD", "Communication Services", 64207770938, 2651201),
    ("BKNG", "Consumer Cyclical", 154441021079, 605793),
    ("CCL", "Consumer Cyclical", 38665194629, 909405),
    ("CMG", "Consumer Cyclical", 42984416340, 646895),
    ("CVNA", "Consumer Cyclical", 47325173597, 1106068),
    ("F", "Consumer Cyclical", 58551054688, 1832343),
    ("KHC", "Consumer Defensive", 32371729517, 376416),
    ("PEP", "Consumer Defensive", 194988407976, 379776),
    ("CCJ", "Energy", 37867425767, 348271),
    ("ET", "Energy", 69511417395, 897459),
    ("SLB", "Energy", 74722981897, 723843),
    ("BRKB", "Financial Services", 592100194133, 500825),
    ("C", "Financial Services", 225937779229, 1068687),
    ("NU", "Financial Services", 56269510671, 1642206),
    ("PYPL", "Financial Services", 49890478172, 1795833),
    ("V", "Financial Services", 608433063972, 439207),
    ("BMY", "Healthcare", 129875731309, 635192),
    ("BSX", "Healthcare", 68461519545, 869174),
    ("MRK", "Healthcare", 325572254385, 424345),
    ("BA", "Industrials", 175114381631, 774833),
    ("DAL", "Industrials", 58771770191, 379121),
    ("UPS", "Industrials", 78786779042, 371603),
    ("VRT", "Industrials", 103540372441, 382419),
    ("ADBE", "Technology", 99049050000, 657316),
    ("CSCO", "Technology", 455551018581, 853387),
    ("NOW", "Technology", 114381080000, 1394812),
    ("SHOP", "Technology", 158887015937, 759282),
    ("UBER", "Technology", 143998274180, 1170906),
    ("NEE", "Utilities", 186220508714, 438318),
    ("PCG", "Utilities", 47652364619, 1341298),
    ("VST", "Utilities", 50118802044, 402884),
)


def seed_cohort(conn: psycopg.Connection, schema: str) -> int:
    """Upsert the cohort. Idempotent; re-running refreshes tags in place."""
    sql = f"""
        INSERT INTO {schema}.research_universe
               (cohort, ticker, sector, marketcap, option_oi, source, selected_on)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cohort, ticker) DO UPDATE
           SET sector = EXCLUDED.sector,
               marketcap = EXCLUDED.marketcap,
               option_oi = EXCLUDED.option_oi,
               source = EXCLUDED.source,
               selected_on = EXCLUDED.selected_on
    """
    with conn.cursor() as cur:
        for ticker, sector, cap, oi in RESEARCH_UNIVERSE:
            cur.execute(sql, (COHORT, ticker, sector, cap, oi, SOURCE, SELECTED_ON))
    conn.commit()
    return len(RESEARCH_UNIVERSE)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument(
        "--seed-only", action="store_true", help="write the cohort, fetch nothing"
    )
    p.add_argument(
        "--max-calls",
        type=int,
        default=8000,
        help="per-run UW call budget; stops cleanly and is resumable (default 8000)",
    )
    p.add_argument("--max-dte", type=int, default=MAX_DTE)
    p.add_argument(
        "--max-sessions",
        type=int,
        default=None,
        help="cap sessions processed this run, oldest first (resumable)",
    )
    args = p.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        n = seed_cohort(conn, settings.db_schema)
        log.info("seeded cohort %s: %d tickers", COHORT, n)
        if args.seed_only:
            return 0

        sessions = weekly_sessions(today=_date.today())
        if args.max_sessions is not None:
            sessions = sessions[: args.max_sessions]
        tickers = [t for t, _, _, _ in RESEARCH_UNIVERSE]

        repo = Repository(conn, schema=settings.db_schema)
        pending = missing_pairs(repo=repo, sessions=sessions, tickers=tickers)
        log.info(
            "%d sessions x %d tickers, <=%s DTE — %d pairs missing, "
            "est. ~%.0f UW calls (budget %d)",
            len(sessions),
            len(tickers),
            args.max_dte,
            len(pending),
            len(pending) * CALLS_PER_TICKER_SESSION,
            args.max_calls,
        )
        if not pending:
            log.info("nothing to backfill — history already complete")
            return 0

        # api_key is a SecretStr and the FIRST positional arg. Passing `settings`
        # here type-checks fine and fails at the wire: the whole Settings object
        # stringifies into the Authorization header and UW answers 431 for every
        # request. Keyword args so that mistake cannot recur silently.
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
        )
        written, done = fill_pairs(
            repo=repo,
            client=client,
            pairs=pending,
            max_calls=args.max_calls,
            max_dte=args.max_dte,
            notes="option_surface_research_backfill",
        )
    log.info("filled %d/%d pairs -> %d surface-grid rows", done, len(pending), written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
