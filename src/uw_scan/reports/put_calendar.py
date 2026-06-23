"""Two-expiry put-calendar engine for the RUT study (IWM spot + RVX vol proxy).

A long put calendar = SHORT a near-dated put + LONG a longer-dated put. The
daily-roll variant sells a fresh 0/1DTE put each session against a standing
long put, then closes & re-establishes the long put when it nears expiry.

`vrp_structure` can't price this: its structures price both legs off one `T`.
Here the short leg lives at front-`T` (→0) while the long leg sits at residual
`T`. This module adds the two-expiry mark and a daily-return simulator.

MODEL-PRICED off RVX — the only daily Russell vol we have. There are NO
historical RUT option chains, so every premium here is Black-Scholes, not an
observed fill. The front leg's IV is the strategy's whole edge and is the one
thing we cannot observe at daily resolution, so it is an explicit knob:

    front_iv = (RVX/100) * front_vol_mult * skew_bump(K/S)
    long_iv  = (RVX/100) * long_vol_mult  * skew_bump(K/S)

Read every result as "edge *conditional on* front_vol_mult" — the sweep reports
the breakeven richness, not a point Sharpe. See docs/research/rut-calendar/.

Daily-resolution caveat: 0DTE and 1DTE both bear exactly one close-to-close
move, so they differ here only in entry time-value and assumed front IV. The
real intraday 0DTE dynamics (gamma path, no overnight gap) are not modelable
from daily bars — a headline gap, not a bug.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as _date
from statistics import fmean, pstdev
from typing import Any

from uw_scan.reports.vrp_structure import CostModel, bs_price, strike_for_delta

TRADING_DAYS = 252.0

# Risk budget: a calendar's daily MTM swings ~tens of % of its bare debit (it's
# vega/gamma-levered), so normalizing returns by the bare debit makes the equity
# path explode. We instead size the position to RISK_FRAC of a notional account
# (debit = RISK_FRAC of capital) so drawdowns are account-relative and readable.
# Sharpe is scale-free, so this only rescales the equity curve, never the Sharpe.
RISK_FRAC = 0.02


def skew_bump(moneyness: float, skew_k: float) -> float:
    """Put-skew multiplier on IV. OTM puts (K<S → moneyness<1) get richer IV.
    ATM/ITM → 1.0. skew_k=0.5 ⇒ a 10%-OTM put carries +5% relative IV."""
    return 1.0 + skew_k * max(0.0, 1.0 - moneyness)


def leg_iv(
    rvx_frac: float, K: float, S: float, vol_mult: float, skew_k: float
) -> float:
    """Per-leg IV from the RVX anchor, a richness multiplier, and put-skew.
    Floored just above zero so bs_price never sees sigma<=0 for a live leg."""
    iv = rvx_frac * vol_mult * skew_bump(K / S, skew_k)
    return max(iv, 1e-4)


@dataclass(frozen=True)
class CalendarConfig:
    """One put-calendar configuration. Defined-risk by construction: the short
    strike can never sit above the long strike (capped in `simulate`)."""

    front_dte: int = 1  # 0 or 1; daily resolution can't truly separate them
    long_dte: int = 30  # trading days to the long-leg expiry
    short_delta: float = 0.20  # OTM put delta the short leg is struck at
    long_delta: float = 0.20  # diagonal long-leg delta (ignored if calendar)
    # 'calendar'  : same strike, short pinned to the (near-money) long strike.
    # 'diagonal'  : long lifted to its own long_delta strike; short re-struck daily.
    # 'decoupled' : iteration 2 — long held at the near-money anchor (like calendar)
    #               but typically long_dte; short re-struck daily off its own delta,
    #               capped at the long strike. The two legs are NOT a unit.
    mode: str = "calendar"
    front_vol_mult: float = 1.0  # THE edge knob: front IV vs RVX
    long_vol_mult: float = 1.0  # long IV vs RVX
    skew_k: float = 0.5  # put-skew steepness, applied to both legs
    min_residual_days: int = 5  # close & re-establish the long leg here
    r: float = 0.04

    def __post_init__(self) -> None:
        if self.front_dte not in (0, 1):
            raise ValueError("front_dte must be 0 or 1")
        if self.mode not in ("calendar", "diagonal", "decoupled"):
            raise ValueError("mode must be 'calendar', 'diagonal' or 'decoupled'")
        if self.long_dte <= self.min_residual_days:
            raise ValueError("long_dte must exceed min_residual_days")


def _front_T(front_dte: int) -> float:
    """Entry time-to-expiry for the short leg. 0DTE ≈ half a session."""
    return (0.5 if front_dte == 0 else 1.0) / TRADING_DAYS


def long_put_mark(
    S: float, K: float, residual_days: float, cfg: CalendarConfig, rvx_frac: float
) -> float:
    """Mark-to-model value of the standing long put (per share)."""
    T = max(residual_days, 0.0) / TRADING_DAYS
    iv = leg_iv(rvx_frac, K, S, cfg.long_vol_mult, cfg.skew_k)
    return bs_price(S, K, T, cfg.r, iv, is_call=False)


def simulate(
    loaded: Any,
    cfg: CalendarConfig,
    cost: CostModel,
    *,
    min_date: _date | None = None,
    contracts: int = 1,
) -> dict:
    """Run the daily-roll calendar over a `_Loaded` (spot + RVX-as-iv) series.

    Returns a dict with the daily-return series and headline metrics. Returns
    are normalized by each cycle's long-leg debit (capital-at-risk), so Sharpe
    is the risk-adjusted edge per unit of premium tied up in the hedge.
    """
    dates = [d for d, _ in loaded.adj]
    spots = [s for _, s in loaded.adj]
    iv_by_date = {r["market_date"]: r["iv"] for r in loaded.rows}
    rvx = [iv_by_date.get(d) for d in dates]

    mult = cost.multiplier * contracts
    daily_ret: list[float] = []  # one entry per settled day, across all cycles
    short_ret: list[float] = []  # decomposed: short-leg-only daily return
    long_ret: list[float] = []  # decomposed: long-leg-only daily return
    daily_dt: list[_date] = []
    short_itm = 0
    short_count = 0
    premiums: list[float] = []
    long_decays: list[float] = []

    n = len(dates)
    i = 0
    if min_date is not None:
        while i < n and dates[i] < min_date:
            i += 1

    while i < n - 1:
        if rvx[i] is None:
            i += 1
            continue
        # --- establish the long leg at day i ---
        S0, v0 = spots[i], rvx[i]
        T_long = cfg.long_dte / TRADING_DAYS
        # Strike off the SHORT (front) expiry so the daily short collects real
        # premium (~short_delta on its own 1-day expiry, ≈near-money). The long
        # leg then sits near-money on the back expiry — that is the real
        # strategy. Anchoring to the 30-day delta makes the 1-day short ~5σ OTM
        # and worthless. Calendar = same strike; diagonal lifts the long strike.
        front_T = _front_T(cfg.front_dte)
        K_short_anchor = strike_for_delta(
            S0, front_T, cfg.r, v0 * cfg.front_vol_mult, cfg.short_delta, is_call=False
        )
        if cfg.mode in ("calendar", "decoupled"):
            K_long = K_short_anchor  # near-money; decoupled just holds it longer
        else:
            K_long = strike_for_delta(
                S0, T_long, cfg.r, v0 * cfg.long_vol_mult, cfg.long_delta, is_call=False
            )
            K_long = max(K_long, K_short_anchor)  # long must cover short
        long_open = long_put_mark(S0, K_long, cfg.long_dte, cfg, v0)
        if long_open <= 0:
            i += 1
            continue
        # Post the debit (max loss, since long ≥ short intrinsic) as RISK_FRAC of
        # the account → account-relative returns.
        capital = long_open * mult / RISK_FRAC

        prev_long = long_open
        cycle_start = i
        # write day i's short (settles day i+1)
        pend_strike, pend_prem = _write_short(spots[i], rvx[i], K_long, cfg)

        j = i + 1
        while j < n and (cfg.long_dte - (j - cycle_start)) >= cfg.min_residual_days:
            if rvx[j] is None:
                break
            residual = cfg.long_dte - (j - cycle_start)
            long_now = long_put_mark(spots[j], K_long, residual, cfg, rvx[j])
            long_change = long_now - prev_long
            long_decays.append(prev_long - long_now)  # +ve = decay cost

            # short written yesterday settles against today's spot
            payoff = max(pend_strike - spots[j], 0.0)
            short_pnl = pend_prem - payoff
            premiums.append(pend_prem)
            short_count += 1
            if payoff > 0:
                short_itm += 1

            # Cost split per leg (one slippage side each: the short is written &
            # cash-settles at expiry → no closing trade; long entry charged once).
            short_cost = cost.total((pend_prem,), contracts) / 2.0
            long_cost = (
                cost.total((long_open,), contracts) / 2.0
                if j == cycle_start + 1
                else 0.0
            )
            short_pnl_d = short_pnl * mult - short_cost
            long_pnl_d = long_change * mult - long_cost
            short_ret.append(short_pnl_d / capital)
            long_ret.append(long_pnl_d / capital)
            daily_ret.append((short_pnl_d + long_pnl_d) / capital)
            daily_dt.append(dates[j])

            prev_long = long_now
            # roll: write a new short for tomorrow
            pend_strike, pend_prem = _write_short(spots[j], rvx[j], K_long, cfg)
            j += 1

        # close the long leg on the last cycle day (cost already counted at open;
        # add the exit half-turn). MTM already captured day-by-day above.
        i = j  # next cycle starts where this one ended

    return _metrics(
        daily_ret,
        daily_dt,
        premiums,
        long_decays,
        short_itm,
        short_count,
        cfg,
        short_ret=short_ret,
        long_ret=long_ret,
    )


def _write_short(
    S: float, rvx_frac: float, K_long: float, cfg: CalendarConfig
) -> tuple[float, float]:
    """Strike + premium for today's short put. Strike capped at K_long so the
    long leg always covers it (defined risk). Same-strike in calendar mode."""
    T = _front_T(cfg.front_dte)
    iv_atm = rvx_frac * cfg.front_vol_mult
    if cfg.mode == "calendar":
        K = K_long
    else:
        K = strike_for_delta(S, T, cfg.r, iv_atm, cfg.short_delta, is_call=False)
        K = min(K, K_long)  # never sell a strike above the long put
    iv = leg_iv(rvx_frac, K, S, cfg.front_vol_mult, cfg.skew_k)
    prem = bs_price(S, K, T, cfg.r, iv, is_call=False)
    return K, prem


def _metrics(
    daily_ret: list[float],
    daily_dt: list[_date],
    premiums: list[float],
    long_decays: list[float],
    short_itm: int,
    short_count: int,
    cfg: CalendarConfig,
    *,
    short_ret: list[float] | None = None,
    long_ret: list[float] | None = None,
) -> dict:
    if not daily_ret:
        return {"n_days": 0, "sharpe": None}
    mu = fmean(daily_ret)
    sd = pstdev(daily_ret) if len(daily_ret) > 1 else 0.0
    sharpe = (mu / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else None
    # equity curve for maxDD
    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for r in daily_ret:
        eq += r
        peak = max(peak, eq)
        maxdd = min(maxdd, eq - peak)
    # per-year sharpe
    by_year: dict[int, list[float]] = {}
    for d, r in zip(daily_dt, daily_ret, strict=True):
        by_year.setdefault(d.year, []).append(r)
    year_sharpe = {
        y: (fmean(v) / pstdev(v) * math.sqrt(TRADING_DAYS))
        for y, v in by_year.items()
        if len(v) > 1 and pstdev(v) > 0
    }
    worst_year = min(year_sharpe.values()) if year_sharpe else None

    # Per-leg decomposition ("treat them not as a group"): is the short income
    # stream actually financing the long hedge's carry?
    def _leg(series: list[float] | None) -> dict:
        if not series:
            return {"sharpe": None, "ann_return": None, "total": None}
        m = fmean(series)
        s = pstdev(series) if len(series) > 1 else 0.0
        return {
            "sharpe": (m / s * math.sqrt(TRADING_DAYS)) if s > 0 else None,
            "ann_return": m * TRADING_DAYS,
            "total": sum(series),
        }

    short_leg = _leg(short_ret)
    long_leg = _leg(long_ret)
    return {
        "n_days": len(daily_ret),
        "start": daily_dt[0],
        "end": daily_dt[-1],
        "ann_return": mu * TRADING_DAYS,
        "ann_vol": sd * math.sqrt(TRADING_DAYS),
        "sharpe": sharpe,
        "maxdd_frac": maxdd,
        "win_rate": sum(1 for r in daily_ret if r > 0) / len(daily_ret),
        "worst_day": min(daily_ret),
        "short_itm_rate": short_itm / short_count if short_count else None,
        "mean_short_prem": fmean(premiums) if premiums else None,
        "mean_long_decay": fmean(long_decays) if long_decays else None,
        "net_theta": (fmean(premiums) - fmean(long_decays))
        if premiums and long_decays
        else None,
        "worst_year_sharpe": worst_year,
        "year_sharpe": year_sharpe,
        "short_leg_sharpe": short_leg["sharpe"],
        "short_leg_ann_return": short_leg["ann_return"],
        "short_leg_total": short_leg["total"],
        "long_leg_ann_return": long_leg["ann_return"],
        "long_leg_total": long_leg["total"],
        "daily_ret": daily_ret,
        "daily_dt": daily_dt,
    }
