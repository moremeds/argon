"""VRP tradable-layer worker jobs: candidate refresh, backtest refresh, paper
ledger open/mark/close. Each loop commits per ticker/position and rolls back on a
per-item except (scheduler _repo() does not commit on close; one bad row must not
poison the rest — InFailedSqlTransaction). Mirrors corporate_actions_jobs.

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from typing import Any

from uw_scan.reports.vrp_backtest import run_vrp_backtest
from uw_scan.reports.vrp_candidates import run_vrp_candidates
from uw_scan.reports.vrp_markout_core import apply_split_adjustment
from uw_scan.reports.vrp_structure import IronCondor, condor_expiry_pnl

log = logging.getLogger(__name__)
_MULT = 100


def vrp_candidates_refresh(*, repo, settings) -> dict[str, Any]:
    return run_vrp_candidates(repo=repo, settings=settings)


def vrp_backtest_refresh(*, repo, settings) -> dict[str, Any]:
    return run_vrp_backtest(repo=repo, settings=settings)


def vrp_paper_open(*, repo, settings, as_of: _date | None = None) -> dict[str, Any]:
    """Open a paper position for each of today's candidates (idempotent via the
    (ticker, opened_on) unique key). expiry_on is a FUTURE date (hold_days trading
    days ≈ calendar days); the mark job settles only once the realized price series
    actually reaches it — so a position can never close the same day it opens
    (ISSUE-1)."""
    today = as_of or _date.today()
    candidates = repo.fetch_vrp_candidates(as_of=today)
    opened = 0
    for c in candidates:
        try:
            expiry_on = c["as_of"] + timedelta(days=int(round(c["hold_days"] * 7 / 5)))
            pid = repo.open_vrp_paper_position(
                ticker=c["ticker"],
                opened_on=c["as_of"],
                hold_days=c["hold_days"],
                expiry_on=expiry_on,
                short_put=c["short_put"],
                long_put=c["long_put"],
                short_call=c["short_call"],
                long_call=c["long_call"],
                entry_credit=c["entry_credit"],
                max_loss=c["max_loss"],
                entry_cost=c.get("entry_cost"),
                contracts=c["contracts"],
                spot_entry=c["spot"],
                iv_entry=c["iv"],
            )
            repo.conn.commit()
            if pid is not None:
                opened += 1
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            log.exception("vrp_paper_open failed for %s: %s", c["ticker"], repr(exc))
    return {"opened": opened, "as_of": today.isoformat()}


def _latest_iv_spot(repo, ticker: str, on: _date):
    """Latest vrp_daily IV AND corp-action-adjusted spot on/before `on` — no future
    leak (ISSUE-3). Returns (iv, spot, full_adj_series)."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT iv FROM {repo._schema}.vrp_daily WHERE ticker=%s AND market_date<=%s "
            "ORDER BY market_date DESC LIMIT 1",
            (ticker, on),
        )
        ivr = cur.fetchone()
    adj = apply_split_adjustment(
        repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
    )
    asof = [(d, v) for d, v in adj if d <= on]
    spot = asof[-1][1] if asof else None
    iv = float(ivr[0]) if ivr and ivr[0] is not None else None
    return iv, spot, adj


def _condor_of(p) -> IronCondor:
    return IronCondor(
        short_put=float(p["short_put"]),
        long_put=float(p["long_put"]),
        short_call=float(p["short_call"]),
        long_call=float(p["long_call"]),
        credit=float(p["entry_credit"]),
        put_width=float(p["short_put"]) - float(p["long_put"]),
        call_width=float(p["long_call"]) - float(p["short_call"]),
        max_loss=float(p["max_loss"]),
        leg_premiums=(0.0, 0.0, 0.0, 0.0),  # marks need no entry premia
    )


def vrp_paper_mark(*, repo, settings, as_of: _date | None = None) -> dict[str, Any]:
    """Mark each open position. CLOSE only when today >= expiry_on AND the realized
    price series has a trading close on/after expiry_on (settle at that exact row —
    no adj[-1] fallback, ISSUE-1/3); else crude intrinsic-at-spot unrealized mark.
    Both realized and unrealized P&L are NET of the modeled entry_cost (ISSUE-4)."""
    today = as_of or _date.today()
    marked = closed = 0
    for p in repo.fetch_open_vrp_paper_positions():
        try:
            _iv, spot, adj = _latest_iv_spot(
                repo, p["ticker"], today
            )  # _iv: v2 BS mark
            condor = _condor_of(p)
            entry_cost = float(p["entry_cost"] or 0.0)
            settle = next(((d, v) for d, v in adj if d >= p["expiry_on"]), None)
            if today >= p["expiry_on"] and settle is not None:
                S_T = settle[1]
                gross = condor_expiry_pnl(condor, S_T) * _MULT * p["contracts"]
                repo.close_vrp_paper_position(
                    p["position_id"],
                    closed_on=settle[0],
                    exit_value=S_T,
                    realized_pnl=gross - entry_cost,
                )
                closed += 1
            elif spot is not None:
                gross = condor_expiry_pnl(condor, spot) * _MULT * p["contracts"]
                repo.update_vrp_paper_mark(
                    p["position_id"],
                    last_mark_on=today,
                    mark_value=spot,
                    unrealized_pnl=gross - entry_cost,
                    mark_source="model",
                )
                marked += 1
            repo.conn.commit()
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            log.exception("vrp_paper_mark failed for %s: %s", p["ticker"], repr(exc))
    return {"marked": marked, "closed": closed, "as_of": today.isoformat()}
