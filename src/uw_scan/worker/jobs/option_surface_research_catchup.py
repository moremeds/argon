"""Nightly catch-up that fills a research cohort's option-surface *history*.

WHY THIS EXISTS ALONGSIDE THE NIGHTLY CAPTURE
---------------------------------------------
`option_surface_research_capture` writes tonight. It has no reverse gear, so a
freshly-seeded cohort starts with an empty past and UW's ~180-day window decays
out from under it at one day per day. This job walks that window and fills what
is missing, a bounded batch per night, until there is nothing left to fill.

The pair is deliberate: capture stops the bleeding, catch-up heals the wound.

WHY NOT JUST PUT THE COHORT IN THE WATCHLIST
--------------------------------------------
The data-gap healer already backfills `option_surface_grid_daily`, and its
denominator is "eligible watchlist tickers x sessions" — so adding the cohort to
`watchlist` would indeed get it backfilled, automatically, with no new code.

It costs about ten times as much. The healer's job is to make the dataset whole:
every session, full term structure, ~17 calls per ticker-session. This job's job
is to answer one question, so it samples weekly (30-day holds make consecutive
daily entries ~95% overlapping — the extra entries are not extra information)
and clips at 60 DTE (the strategy only trades 7-45). 37 tickers over the window:
~78,600 calls the healer's way, ~7,950 this way.

Watchlist membership would also enlist all 37 names in every per-ticker job
forever — a permanent ~32% burn increase on a ~114-name watchlist — to buy a
one-time backfill. The cohort table exists precisely so research sampling cannot
silently promote itself to production completeness.

SELF-TERMINATING
----------------
Once every (ticker, session) pair in the window is present the job finds no gaps
and returns having spent nothing, every night thereafter. It does not need to be
switched off, and re-seeding a larger cohort re-arms it automatically.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta

from uw_scan.api.client import UwClient
from uw_scan.storage.repository import Repository
from uw_scan.storage.research_universe import ResearchUniverseRepository
from uw_scan.worker.jobs.option_surface_capture import _build_ticker_rows

log = logging.getLogger(__name__)

# UW serves ~180 calendar days of history. Older than that cannot be backfilled
# at any price, which is what makes the forward capture load-bearing.
UW_HISTORY_DAYS = 180
MAX_DTE = 60

# Measured on the existing grid: one greek_exposure_by_expiry call plus one
# greeks call per expiry, ~7.6 expiries per ticker-session at <=60 DTE.
CALLS_PER_TICKER_SESSION = 8.6


def weekly_sessions(
    *,
    today: _date,
    weekday: int = 2,
    history_days: int = UW_HISTORY_DAYS,
) -> list[_date]:
    """Weekly sample dates inside UW's history window, oldest first.

    Wednesday by default: far enough from both weekend edges that a market
    holiday rarely lands on it, so the sample stays evenly spaced rather than
    clustering around the dates that happened to be open.
    """
    earliest = today - timedelta(days=history_days)
    d = today - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    out: list[_date] = []
    while d >= earliest:
        out.append(d)
        d -= timedelta(days=7)
    out.reverse()
    return out


def missing_pairs(
    *,
    repo: Repository,
    sessions: list[_date],
    tickers: list[str],
) -> list[tuple[_date, str]]:
    """(session, ticker) pairs with no surface-grid rows yet, oldest session first.

    One query for the whole window rather than one per session: the window is
    ~25 sessions and this runs before every batch, so the round-trips add up.
    Oldest-first because the far end of the window is what expires next — a
    session we skip tonight may be unfetchable by the time we come back.
    """
    if not sessions or not tickers:
        return []
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT market_date, ticker FROM {repo._schema}.option_surface_grid_daily "
            "WHERE market_date = ANY(%s) GROUP BY market_date, ticker",
            (list(sessions),),
        )
        have = {(r[0], r[1].upper()) for r in cur.fetchall()}
    return [
        (session, ticker)
        for session in sessions
        for ticker in tickers
        if (session, ticker.upper()) not in have
    ]


def fill_pairs(
    *,
    repo: Repository,
    client: UwClient,
    pairs: list[tuple[_date, str]],
    max_calls: float | None,
    max_dte: int | None = MAX_DTE,
    notes: str,
) -> tuple[int, int]:
    """Fetch each pair until the call budget runs out. Returns (rows, pairs_done).

    The budget is tracked LOCALLY, estimated at CALLS_PER_TICKER_SESSION per
    pair, rather than read from `client.rate_limit.daily_count`. That counter is
    populated from UW response headers, so it is None until the first successful
    response and otherwise sits wherever the shared account already is — a guard
    keyed on it either never fires or fires on the first request, depending on
    the account, not on this run. Measured 2026-07-29: the account was at
    109,089/120,000 by midday, so a guard that silently no-ops here is the
    difference between a research job and an outage of the live pool.

    Approximate by construction (the real cost is 1 + n_expiries, unknown until
    fetched), so it is a bound rather than a meter, and errs toward stopping
    early. Stopping early is free: the next run recomputes the gaps and resumes.
    """
    rows_written = 0
    done = 0
    spent = 0.0
    for market_date, ticker in pairs:
        if max_calls is not None and spent >= max_calls:
            log.info(
                "%s: call budget reached (~%.0f of %.0f) — stopping cleanly, "
                "%d pairs left for the next run",
                notes,
                spent,
                max_calls,
                len(pairs) - done,
            )
            break
        spent += CALLS_PER_TICKER_SESSION
        run_id = None
        try:
            run_id = repo.insert_scan_run(ticker, notes=notes)
            rows = _build_ticker_rows(
                client=client,
                repo=repo,
                run_id=run_id,
                ticker=ticker,
                market_date=market_date,
                date_iso=market_date.isoformat(),
                max_dte=max_dte,
            )
            # spot=None: UW's greeks payload carries no underlying, and daily_ohlc
            # is back-adjusted against as-traded strikes. Downstream `load_spot`
            # resolves this via its strike-range guard — filling it from OHLC here
            # would inject the very scale seam that guard exists to reject.
            n = repo.upsert_option_surface_grid(ticker, market_date, None, rows)
            repo.finish_scan_run(run_id, status="ok")
            repo.conn.commit()
            rows_written += n
            done += 1
        except Exception as exc:  # noqa: BLE001 — one bad pair must not kill the run
            repo.conn.rollback()
            log.warning("%s: %s/%s skipped: %s", notes, market_date, ticker, repr(exc))
            if run_id is not None:
                repo.finish_scan_run(run_id, status="failed")
    return rows_written, done


def option_surface_research_catchup(
    *,
    repo: Repository,
    client: UwClient,
    cohort: str,
    today: _date | None = None,
    max_calls: float | None = 1500,
    max_dte: int | None = MAX_DTE,
) -> dict[str, int]:
    """Fill one bounded batch of the cohort's missing history.

    Returns {"pairs_filled", "pairs_remaining", "rows"} so the log says how many
    nights are left rather than only what happened tonight.

    `today` is the ET market date — the scheduler passes
    ``datetime.now(rth_tz).date()`` so a non-ET host cannot stamp the next day.
    """
    if today is None:
        today = _date.today()
    tickers = ResearchUniverseRepository(
        repo.conn, schema=repo._schema
    ).list_cohort_tickers(cohort)
    if not tickers:
        log.info(
            "option_surface_research_catchup: cohort %r is empty — nothing to do",
            cohort,
        )
        return {"pairs_filled": 0, "pairs_remaining": 0, "rows": 0}

    sessions = weekly_sessions(today=today)
    pending = missing_pairs(repo=repo, sessions=sessions, tickers=tickers)
    if not pending:
        log.info(
            "option_surface_research_catchup[%s]: history complete across %d "
            "sessions x %d tickers — nothing to fill",
            cohort,
            len(sessions),
            len(tickers),
        )
        return {"pairs_filled": 0, "pairs_remaining": 0, "rows": 0}

    rows, done = fill_pairs(
        repo=repo,
        client=client,
        pairs=pending,
        max_calls=max_calls,
        max_dte=max_dte,
        notes="option_surface_research_catchup",
    )
    remaining = len(pending) - done
    log.info(
        "option_surface_research_catchup[%s]: filled %d pairs -> %d rows, "
        "%d remaining (~%.0f more calls)",
        cohort,
        done,
        rows,
        remaining,
        remaining * CALLS_PER_TICKER_SESSION,
    )
    return {"pairs_filled": done, "pairs_remaining": remaining, "rows": rows}
