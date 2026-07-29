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

WHY NOT JUST ADD THEM TO THE WATCHLIST
--------------------------------------
`watchlist` membership enlists a ticker in every per-ticker scheduled job, so 37
names would permanently raise the DAILY UW burn — for a one-off study. The cohort
lives in `uw_scan.research_universe` instead (migration 110) and only this script
iterates it.

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
from datetime import timedelta

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_surface_capture import _build_ticker_rows

log = logging.getLogger("surface_research_backfill")

COHORT = "liquid_sector_balanced_v1"
SOURCE = (
    "uw_stock_screener, pooled marketcap-desc + total_open_interest-desc pages; "
    "Common Stock, marketcap>=$30B AND total_open_interest>=200k; "
    "top 5 per sector by OI, deduped against the watchlist"
)
SELECTED_ON = _date(2026, 7, 29)

# UW serves ~180 calendar days of history. Anything older cannot be backfilled at
# any price, which is why the nightly capture matters.
UW_HISTORY_DAYS = 180
MAX_DTE = 60

# Measured on the existing grid: 1 greek_exposure_by_expiry call plus one greeks
# call per expiry, ~7.6 expiries per ticker-session at <=60 DTE.
CALLS_PER_TICKER_SESSION = 8.6

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


def weekly_sessions(*, today: _date, weekday: int = 2) -> list[_date]:
    """Weekly sample dates inside UW's history window, oldest first.

    Wednesday by default: far enough from both weekend edges that a market
    holiday rarely lands on it, so the sample stays evenly spaced rather than
    clustering around the dates that happened to be open.
    """
    earliest = today - timedelta(days=UW_HISTORY_DAYS)
    d = today - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    out: list[_date] = []
    while d >= earliest:
        out.append(d)
        d -= timedelta(days=7)
    out.reverse()
    return out


def backfill(
    *,
    repo: Repository,
    client: UwClient,
    sessions: list[_date],
    tickers: list[str],
    max_calls: int | None,
    max_dte: int | None = MAX_DTE,
) -> int:
    """Backfill, stopping cleanly once ~`max_calls` UW requests have been spent.

    The budget is tracked PER RUN, estimated at CALLS_PER_TICKER_SESSION per
    ticker fetched, rather than read from `client.rate_limit.daily_count`.
    That counter is populated from UW response headers, so it is None until the
    first successful response and unreliable across error paths — a guard keyed
    on it either never fires or fires on the first request depending on where the
    account counter already sits. Measured 2026-07-29: the account was at
    109,089/120,000 by midday, so a guard that silently no-ops here is the
    difference between a research job and an outage of the live pool.

    Approximate by construction (the real cost is 1 + n_expiries, unknown until
    fetched), so it is a bound rather than a meter — deliberately erring toward
    stopping early.
    """
    written = 0
    spent = 0.0
    for market_date in sessions:
        date_iso = market_date.isoformat()
        with repo.conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker FROM {repo._schema}.option_surface_grid_daily "
                "WHERE market_date=%s GROUP BY ticker",
                (market_date,),
            )
            done = {r[0].upper() for r in cur.fetchall()}
        todo = [t for t in tickers if t.upper() not in done]
        if not todo:
            log.info(
                "%s: already captured for all %d cohort tickers", date_iso, len(tickers)
            )
            continue
        log.info("%s: %d/%d tickers to fetch", date_iso, len(todo), len(tickers))
        for ticker in todo:
            if max_calls is not None and spent >= max_calls:
                log.warning(
                    "run budget reached (~%.0f of %d calls) — stopping cleanly at "
                    "%s. Re-run to resume; already-captured tickers are skipped.",
                    spent,
                    max_calls,
                    date_iso,
                )
                return written
            spent += CALLS_PER_TICKER_SESSION
            run_id = None
            try:
                run_id = repo.insert_scan_run(
                    ticker, notes="option_surface_research_backfill"
                )
                rows = _build_ticker_rows(
                    client=client,
                    repo=repo,
                    run_id=run_id,
                    ticker=ticker,
                    market_date=market_date,
                    date_iso=date_iso,
                    max_dte=max_dte,
                )
                # spot=None deliberately — see KNOWN GAP in the module docstring.
                n = repo.upsert_option_surface_grid(ticker, market_date, None, rows)
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
                written += n
            except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the run
                repo.conn.rollback()
                log.warning("%s/%s skipped: %s", date_iso, ticker, repr(exc))
                if run_id is not None:
                    repo.finish_scan_run(run_id, status="failed")
    return written


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
        est = len(sessions) * len(tickers) * CALLS_PER_TICKER_SESSION
        log.info(
            "%d sessions x %d tickers, <=%s DTE — est. ~%.0f UW calls",
            len(sessions),
            len(tickers),
            args.max_dte,
            est,
        )

        repo = Repository(conn, schema=settings.db_schema)
        # api_key is a SecretStr and the FIRST positional arg. Passing `settings`
        # here type-checks fine and fails at the wire: the whole Settings object
        # stringifies into the Authorization header and UW answers 431 for every
        # request. Keyword args so that mistake cannot recur silently.
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
        )
        written = backfill(
            repo=repo,
            client=client,
            sessions=sessions,
            tickers=tickers,
            max_calls=args.max_calls,
            max_dte=args.max_dte,
        )
    log.info("wrote %d surface-grid rows", written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
