"""Forward markout for Theta Harvester strangles.

Re-prices the exact contracts a candidate row recorded, using
option_surface_grid_daily IV on a later session. Entry and marks therefore
share one pricing basis; mixing an IB NBBO entry with grid-IV marks would bake
a constant bid-ask bias into every P&L and read as alpha.

Sign convention: the position is SHORT the strangle, so
pnl = entry_credit_theo - position_value. Positive means the credit was kept.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from uw_scan.reports.vrp_structure import bs_price

log = logging.getLogger(__name__)

HORIZONS: tuple[int, ...] = (5, 10, 20, 30)

# The terminal (at-expiry) mark, stored under a sentinel horizon so it shares
# the markouts table. A short strangle's entire loss distribution lives at and
# near expiry: the intermediate horizons above all still carry time value and
# will read positive in almost every window. WITHOUT this row the markout
# cannot observe the loss the strategy exists to be paid for, and the series is
# structurally truncated above.
TERMINAL_HORIZON = -1

# Snapping a horizon forward past a weekend or a missed capture is correct;
# snapping it three weeks forward because the ticker fell out of the surface is
# not — it would mark a T+5 against a completely different market. Beyond this
# many calendar days the horizon is left unscored instead.
MAX_SNAP_DAYS = 7

# Settlement comes from daily_ohlc, which is back-adjusted; the strikes come
# from the as-traded grid. A split BETWEEN entry and expiry therefore settles a
# raw-scale position against a rescaled close — KORU's 20-for-1 would book the
# put as 20x in-the-money and record a catastrophic loss that never happened.
# The entry-side strike-range guard in load_spot cannot see this: at entry the
# two sources still agreed.
#
# A 4x move inside a <=45-day window is a split signature, not a market move,
# for the liquid names in this universe. Bias is stated rather than hidden: on
# the rare occasion a real 4x move is dropped, it would have been a large LOSS,
# so this trims the left tail and is optimistic. It is logged, never silent.
#
# KNOWN GAP — this is a magnitude heuristic standing in for data argon already
# has. `uw_scan.corporate_actions` records the exact (ticker, event_date,
# split_ratio), and joining it would classify splits exactly instead of
# inferring them from the move size. The heuristic cannot see a 2:1 or 3:1
# split at all: those settle an as-traded strike against a back-adjusted close
# and book a large FABRICATED LOSS that this guard passes through. Because the
# published verdict is "loses money held to expiry", any such row manufactures
# the very conclusion the measurement reports — the bias runs pessimistic here,
# opposite to the optimistic direction claimed for the >4x drops. Replace with
# a corporate_actions join before the numbers are quoted again.
MAX_SETTLEMENT_MOVE = 4.0


def _settlement_scale_ok(
    ticker: str, expiry: date, *, entry_spot: float, settle_close: float
) -> bool:
    """False when settlement and entry are on different price scales.

    See MAX_SETTLEMENT_MOVE. Returns True (scores the row) whenever the inputs
    are unusable for the comparison rather than guessing, because a missing
    entry spot is a different problem from a split.
    """
    if entry_spot <= 0 or settle_close <= 0:
        return True
    ratio = settle_close / entry_spot
    # Strict, not inclusive. An exact 4:1 split lands on ratio == 0.25 and an
    # inclusive bound admits it — CRWD's 2026-07-02 4:1 is exactly that case,
    # so the one split this threshold was chosen to sit above slipped under it.
    if 1.0 / MAX_SETTLEMENT_MOVE < ratio < MAX_SETTLEMENT_MOVE:
        return True
    log.warning(
        "theta markout: dropping terminal mark for %s exp=%s — settlement close "
        "%.4f is %.1fx the entry spot %.4f, which is a corporate-action scale "
        "break rather than a market move",
        ticker,
        expiry,
        settle_close,
        ratio,
        entry_spot,
    )
    return False


def mark_position(
    *,
    spot: float,
    put_strike: float,
    call_strike: float,
    put_iv: float,
    call_iv: float,
    dte_remaining: int,
    r: float,
) -> tuple[float, float, float]:
    """(put_mark, call_mark, position_value) — cost to buy the strangle back."""
    t_years = max(dte_remaining, 0) / 365.0
    put = bs_price(spot, put_strike, t_years, r, put_iv, is_call=False)
    call = bs_price(spot, call_strike, t_years, r, call_iv, is_call=True)
    return put, call, put + call


def _row(
    *,
    ticker: str,
    as_of: date,
    horizon: int,
    mark_date: date,
    spot: float,
    put_iv: float | None,
    call_iv: float | None,
    put_mark: float,
    call_mark: float,
    put_strike: float,
    call_strike: float,
    entry_credit: float,
    expired: bool,
) -> dict[str, Any]:
    value = put_mark + call_mark
    pnl = entry_credit - value
    return {
        "ticker": ticker,
        "as_of": as_of,
        "horizon_days": horizon,
        "mark_date": mark_date,
        "spot": spot,
        "put_iv": put_iv,
        "call_iv": call_iv,
        "put_mark": put_mark,
        "call_mark": call_mark,
        "position_value": value,
        "pnl": pnl,
        "pnl_pct_of_credit": (pnl / entry_credit * 100.0 if entry_credit > 0 else None),
        "breached": spot <= put_strike or spot >= call_strike,
        "expired": expired,
    }


def run_theta_markout(*, repo: Any) -> dict[str, Any]:
    """Score every candidate whose horizons have come due and are unscored."""
    pending = repo.load_candidates_needing_marks(HORIZONS)
    rows: list[dict[str, Any]] = []

    for cand in pending:
        as_of: date = cand["as_of"]
        expiry: date = cand["expiry"]
        entry_credit = float(cand["entry_credit_theo"])
        put_strike = float(cand["put_strike"])
        call_strike = float(cand["call_strike"])

        for horizon in HORIZONS:
            requested = as_of + timedelta(days=horizon)
            if requested >= expiry:
                # Past expiry there is no grid row to read — the contract is
                # gone from the chain. The terminal mark below covers it.
                continue
            grid = repo.load_marks_for(
                cand["ticker"],
                expiry,
                put_strike,
                call_strike,
                requested,
                max_snap_days=MAX_SNAP_DAYS,
            )
            if grid is None:
                continue  # session not reached, or no surface capture in range

            # The ACTUAL session the grid resolved to, not the requested date.
            # Using `requested` here would date the row to a Saturday and price
            # it with the wrong dte_remaining.
            mark_date = grid["market_date"]
            spot = float(grid["spot"])
            put_iv = float(grid["put_iv"])
            call_iv = float(grid["call_iv"])
            put_mark, call_mark, _ = mark_position(
                spot=spot,
                put_strike=put_strike,
                call_strike=call_strike,
                put_iv=put_iv,
                call_iv=call_iv,
                dte_remaining=max((expiry - mark_date).days, 0),
                r=float(cand["risk_free_rate"]),
            )
            rows.append(
                _row(
                    ticker=cand["ticker"],
                    as_of=as_of,
                    horizon=horizon,
                    mark_date=mark_date,
                    spot=spot,
                    put_iv=put_iv,
                    call_iv=call_iv,
                    put_mark=put_mark,
                    call_mark=call_mark,
                    put_strike=put_strike,
                    call_strike=call_strike,
                    entry_credit=entry_credit,
                    expired=False,
                )
            )

        # ------------------------------------------------------------ terminal
        # Settlement is the only observation that sees the strategy's real risk.
        # Priced as intrinsic off the underlying close on expiry (daily_ohlc,
        # not the grid — the contract has left the chain by then).
        # ponytail: European-style settlement on American options. Early
        # assignment (dividends, deep-ITM puts) would have closed the short leg
        # sooner and usually WORSE than this row shows, so the terminal P&L is
        # an optimistic bound on the loss, not a neutral one. Model assignment
        # only if the loss distribution turns out to matter at the margin.
        settle = (
            repo.load_settlement_close(cand["ticker"], expiry)
            if repo.has_session_after(cand["ticker"], expiry)
            else None
        )
        if settle is not None and not _settlement_scale_ok(
            cand["ticker"],
            expiry,
            entry_spot=float(cand["underlying_spot"]),
            settle_close=settle[1],
        ):
            settle = None
        if settle is not None:
            settle_date, spot = settle
            rows.append(
                _row(
                    ticker=cand["ticker"],
                    as_of=as_of,
                    horizon=TERMINAL_HORIZON,
                    # The session actually used, which is the last bar at or
                    # BEFORE expiry — never the nominal expiry when that day
                    # had no bar.
                    mark_date=settle_date,
                    spot=spot,
                    put_iv=None,
                    call_iv=None,
                    put_mark=max(0.0, put_strike - spot),
                    call_mark=max(0.0, spot - call_strike),
                    put_strike=put_strike,
                    call_strike=call_strike,
                    entry_credit=entry_credit,
                    expired=True,
                )
            )

    written = repo.upsert_markouts(rows)
    log.info(
        "theta_harvester_markout: %d candidates -> %d marks",
        len(pending),
        written,
    )
    return {"candidates_scored": len(pending), "marks_written": written}
