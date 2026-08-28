"""Per-print earnings reaction compute (spec §5-ii).

Turns the durable earnings calendar (migration 144) into a measured price
reaction per print: what did the stock actually do, in percent, around its
report date. Pure warm-store compute over `earnings_calendar` x `daily_ohlc`
— zero UW/IB spend, idempotent (insert-or-skip), safe to re-run.

Reaction windows (session drives which close counts as "before" vs "after"
the print — see the module CLAUDE.md entry for the worked examples):

- `premarket` print on day D: before = last close < D; after = first close >= D.
  The report lands before the open, so D's own close already reflects it.
- `afterhours` print on day D: before = last close <= D; after = first close > D.
  The report lands after the close, so D's own close is still the "before" state.
- `session` NULL: before = last close < D; after = first close > D. This is
  the ~2% of names UW leaves unclassified (see earnings_calendar.py) — NULL
  spans both possible windows deliberately, trading a slightly wider window
  for never guessing a session that was never observed.

`source='statement_obs'` calendar rows are EXCLUDED entirely (branch-fix-p2,
I1), never computed as a NULL-session reaction. Those rows carry a FILING
date (`fundamental_statement_obs.filing_published_at`), not a print date —
see `storage/earnings_calendar.py`'s module docstring and `worker/jobs/
fundamental_ingest_daily.FILING_LOOKBACK_DAYS` for the measured gap between
the two: one-directional (a filing lands on or after its print) and
fat-tailed (25 days observed), not a small bounded window. A close-price
window computed around a filing date is not a reaction to anything; it is a
two-day drift measurement wearing an earnings-reaction's label.
`excluded_statement_obs` counts how many prints this run skipped for that
reason, so the gap in coverage is visible to an operator rather than
silently absorbed into `skipped_incomplete`.

`close_before` / `close_after` are resolved by querying what `daily_ohlc`
actually holds for the ticker, NEVER by date arithmetic (`D - 1 day` breaks on
weekends, holidays, and per-ticker OHLC gaps). A print is skipped — not
written with a null — when either side of the window has no close yet; the
calendar row persists, so the same print is picked up again on tomorrow's
run once the missing close lands. `skipped_incomplete` in the return dict is
how an operator sees prints waiting on a price, rather than the job going
silently quiet.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg

from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.earnings_reactions import EarningsReactionsRepository

log = logging.getLogger(__name__)


def earnings_reactions_compute(
    conn: psycopg.Connection,
    *,
    as_of: date,
    lookback_days: int = 10,
    schema: str = "uw_scan",
) -> dict[str, int]:
    """Compute reactions for every calendar print in
    `[as_of - lookback_days, as_of]` (inclusive, matching
    `prints_between`'s BETWEEN semantics) that isn't already resolved."""
    cal = EarningsCalendarRepository(conn, schema=schema)
    repo = EarningsReactionsRepository(conn, schema=schema)
    prints = cal.prints_between(as_of - timedelta(days=lookback_days), as_of)
    rows: list[dict] = []
    skipped = 0
    excluded_statement_obs = 0
    with conn.cursor() as cur:
        for p in prints:
            if p["source"] == "statement_obs":
                # Branch-fix-p2, I1: this row's date is a FILING date, not a
                # print date — see the module docstring. Never compute a
                # reaction against it.
                excluded_statement_obs += 1
                continue
            d, session = p["report_date"], p["session"]
            before_op = "<" if session != "afterhours" else "<="
            after_op = ">=" if session == "premarket" else ">"
            cur.execute(
                f"""SELECT date, close FROM {schema}.daily_ohlc
                     WHERE ticker = %s AND date {before_op} %s
                     ORDER BY date DESC LIMIT 1""",
                (p["ticker"], d),
            )
            before = cur.fetchone()
            cur.execute(
                f"""SELECT date, close FROM {schema}.daily_ohlc
                     WHERE ticker = %s AND date {after_op} %s
                     ORDER BY date ASC LIMIT 1""",
                (p["ticker"], d),
            )
            after = cur.fetchone()
            if not before or not after:
                skipped += 1
                continue
            rows.append(
                {
                    "ticker": p["ticker"],
                    "report_date": d,
                    "session": session,
                    "close_before_date": before[0],
                    "close_before": before[1],
                    "close_after_date": after[0],
                    "close_after": after[1],
                    "pct_move": float(after[1]) / float(before[1]) - 1.0,
                }
            )
    written = repo.upsert_rows(rows)
    result = {
        "prints": len(prints),
        "written": written,
        "skipped_incomplete": skipped,
        "excluded_statement_obs": excluded_statement_obs,
    }
    log.info(
        "earnings_reactions_compute: %d prints, %d written, %d skipped (no close "
        "yet), %d excluded (statement_obs, filing date not a print date)",
        result["prints"],
        result["written"],
        result["skipped_incomplete"],
        result["excluded_statement_obs"],
    )
    return result
