"""Nightly implied-move snapshot (spec §5-iii): what the options market
currently implies the next print will do.

Reads `option_surface_grid_daily` (tonight's `market_date` rows only) for
every ticker with a known print in `earnings_calendar` (Task 4) within the
next `LOOKAHEAD_DAYS` calendar days, and derives the Brenner-Subrahmanyam
ATM-straddle approximation:

    implied_move_pct = 0.7979 * atm_iv * sqrt(T)
    implied_move_usd = implied_move_pct * spot

`atm_iv` is the mean of `call_iv`/`put_iv` at the strike nearest
`underlying_spot` on the COVERING EXPIRY (the first expiry on tonight's grid
that is >= the print's reaction day); `T` is calendar days from `market_date`
to that expiry, divided by 365. One-sided IV (only a call or only a put
quoted at that strike) is allowed and used as-is — `iv_basis` records which
side, never interpolated from the other and never dropped.

Reaction day differs by session (see `_reaction_day`): getting this wrong
shifts the covering-expiry pick for an entire class of prints in one
constant direction that never averages out.

COVERAGE IS HONEST: a ticker gets NO row when tonight's grid has no rows for
it, when no expiry on tonight's grid covers the reaction day, or when the
nearest strike carries neither `call_iv` nor `put_iv` — never a zero, never
an interpolation, never a nearest-other-date fallback. `not_covered` is
counted and logged so a silent widening of the gap is visible, not capped
away.

`source='statement_obs'` calendar rows are EXCLUDED entirely (branch-fix-p2,
I1), never derived against. Those rows carry a FILING date, not a print
date, and the gap between the two is one-directional and fat-tailed — a
filing lands on or after its print, never before, but the observed gap has
run as wide as 25 days (see `storage/earnings_calendar.py` and `worker/jobs/
fundamental_ingest_daily.FILING_LOOKBACK_DAYS`) — so neither `_reaction_day`
nor the covering-expiry pick can target a real print for them — an
implied-move number computed against a filing date is not implying anything
about a print. `excluded_statement_obs` counts how many upcoming rows this
run skipped for that reason.

Pure warm-store read + compute — zero UW/IB spend, safe to re-run (each
night's row is an overwrite of that same night's prior attempt, see
`ImpliedMoveRepository.upsert_rows`).

COUNTER GRAIN: `prints_upcoming`, `covered`, and `not_covered` are all
counted at the same per-print grain (`covered + not_covered ==
prints_upcoming` always). A ticker carrying two prints inside the window
(never observed in practice for quarterly earnings) is counted twice, once
per print — only the write is deduped to the first (soonest) print, since
the table's PK is (ticker, market_date) and a second write would collide.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import psycopg

from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.implied_move import ImpliedMoveRepository

log = logging.getLogger(__name__)

# How far out a print may be and still get a nightly snapshot. 21 calendar
# days comfortably covers a monthly options cycle's worth of run-up without
# scanning every future print on file (most of which are too far out for the
# surface to carry a covering expiry at all).
LOOKAHEAD_DAYS = 21

# Brenner-Subrahmanyam (1988) ATM-straddle-as-fraction-of-spot approximation:
# straddle ≈ 0.7979 * sigma_atm * sqrt(T). Documented here (not just in the
# migration comment) because this module is the formula's one call site.
BRENNER_SUBRAHMANYAM_CONSTANT = 0.7979


def _reaction_day(report_date: date, session: str | None) -> date:
    """The day the market has actually digested the print by:

    - `premarket`: the report lands before the open, so `report_date`'s own
      close already reflects it -> reaction day IS report_date.
    - `afterhours`: the report lands after the close, so the market only
      reacts starting the NEXT session -> reaction day is report_date + 1.
    - `None` (the ~2% UW leaves unclassified, see earnings_calendar.py): we
      don't know which session it was, so we take the more conservative
      (later) of the two -> report_date + 1, same as afterhours. Assuming
      premarket here would silently pick a covering expiry one day too
      early for a name that actually reported afterhours.
    """
    if session == "premarket":
        return report_date
    return report_date + timedelta(days=1)


def prints_within_lookahead(
    cal: EarningsCalendarRepository,
    *,
    as_of: date,
    lookahead_days: int = LOOKAHEAD_DAYS,
) -> list[dict]:
    """Calendar prints in `[as_of, as_of + lookahead_days]`, inclusive on
    both ends. The ONE call site for the horizon filter (branch-fix-p2, I2)
    — `implied_move_snapshot` and the backfill's dry-run branch both call
    this rather than each carrying their own copy of `<= horizon`, so a
    change to the boundary can't drift between the two."""
    horizon = as_of + timedelta(days=lookahead_days)
    return [
        p for p in cal.next_prints(on_or_after=as_of) if p["report_date"] <= horizon
    ]


def implied_move_snapshot(
    conn: psycopg.Connection, *, as_of: date, schema: str = "uw_scan"
) -> dict[str, int]:
    cal = EarningsCalendarRepository(conn, schema=schema)
    repo = ImpliedMoveRepository(conn, schema=schema)

    all_prints = prints_within_lookahead(cal, as_of=as_of)
    excluded_statement_obs = sum(
        1 for p in all_prints if p["source"] == "statement_obs"
    )
    prints = [p for p in all_prints if p["source"] != "statement_obs"]

    covered = 0
    not_covered = 0
    rows: list[dict] = []
    written_tickers: set[str] = set()
    with conn.cursor() as cur:
        for p in prints:
            ticker = p["ticker"]
            reaction_day = _reaction_day(p["report_date"], p["session"])

            cur.execute(
                f"""SELECT expiry, strike, call_iv, put_iv, underlying_spot
                      FROM {schema}.option_surface_grid_daily
                     WHERE ticker = %s AND market_date = %s
                     ORDER BY expiry, strike""",
                (ticker, as_of),
            )
            grid = cur.fetchall()
            if not grid:
                not_covered += 1
                continue

            covering_expiries = sorted({r[0] for r in grid if r[0] >= reaction_day})
            if not covering_expiries:
                not_covered += 1
                continue
            covering_expiry = covering_expiries[0]

            candidates = [r for r in grid if r[0] == covering_expiry]
            # M4: `underlying_spot` can be NULL on a mixed subset of a
            # ticker's rows for one night (a real, observed shape — see
            # TSLA 2026-03-03 in test_implied_move.py, all-NULL there but
            # mixed cases are not ruled out). This first `spot` is only a
            # reference point for the nearest-strike sort below; with
            # `ORDER BY expiry, strike` the pick is at least deterministic
            # rather than whatever order Postgres happened to return.
            spot = candidates[0][4]
            if spot is None:
                not_covered += 1
                continue
            # Nearest strike to spot; ties broken by strike ascending for a
            # deterministic pick.
            candidates.sort(key=lambda r: (abs(r[1] - spot), r[1]))
            _, strike, call_iv, put_iv, spot = candidates[0]
            if spot is None:
                # M4: the WINNING row's own spot can differ from the
                # reference row's (mixed-NULL underlying_spot) — re-check
                # after the rebind rather than trusting the first lookup.
                not_covered += 1
                continue

            if call_iv is not None and put_iv is not None:
                atm_iv, basis = (call_iv + put_iv) / 2, "both"
            elif call_iv is not None:
                atm_iv, basis = call_iv, "call_only"
            elif put_iv is not None:
                atm_iv, basis = put_iv, "put_only"
            else:
                not_covered += 1
                continue

            t_years = (covering_expiry - as_of).days / 365.0
            if t_years <= 0:
                # M5: reachable when the covering expiry equals `as_of`
                # itself (a premarket print today with an expiry listed
                # today). sqrt(0) makes implied_move_pct a real, persisted
                # ZERO -- exactly what migration 146's "never a zero"
                # coverage contract forbids. A zero-DTE straddle has no
                # meaningful Brenner-Subrahmanyam approximation; treat it as
                # a coverage failure, not a value.
                not_covered += 1
                continue
            implied_move_pct = (
                BRENNER_SUBRAHMANYAM_CONSTANT * float(atm_iv) * math.sqrt(t_years)
            )
            implied_move_usd = implied_move_pct * float(spot)
            covered += 1

            if ticker in written_tickers:
                # PK is (ticker, market_date) -- one row per ticker per
                # night. A ticker carrying two prints inside the window
                # (never observed in practice for quarterly earnings) is
                # still counted in `covered` above, at the SAME per-print
                # grain as `prints_upcoming` -- but only the FIRST (soonest,
                # since `prints` is sorted by report_date) gets a row
                # written; a second write would collide on the PK and
                # silently overwrite the first. Dedup is a write concern
                # only, never a counting concern.
                continue
            written_tickers.add(ticker)
            rows.append(
                {
                    "ticker": ticker,
                    "market_date": as_of,
                    "report_date": p["report_date"],
                    "expiry": covering_expiry,
                    "strike": strike,
                    "atm_iv": atm_iv,
                    "iv_basis": basis,
                    "spot": spot,
                    "implied_move_pct": implied_move_pct,
                    "implied_move_usd": implied_move_usd,
                }
            )

    repo.upsert_rows(rows)
    result = {
        "prints_upcoming": len(prints),
        "covered": covered,
        "not_covered": not_covered,
        "excluded_statement_obs": excluded_statement_obs,
    }
    log.info(
        "implied_move_snapshot as_of=%s: %d prints upcoming, %d covered, "
        "%d not_covered, %d excluded (statement_obs, filing date not a print date)",
        as_of,
        result["prints_upcoming"],
        result["covered"],
        result["not_covered"],
        result["excluded_statement_obs"],
    )
    return result
