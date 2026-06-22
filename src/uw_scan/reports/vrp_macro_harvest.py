"""Macro systematic short-vol harvest — does any defined-risk structure convert
the macro VRP into positive risk-adjusted P&L?

Each macro name carries a DIRECTION; the sweep tries the structures admissible for
it (bullish → bull put spread + cash-secured put; neutral → iron condor) across a
grid of entry gate × short-delta × horizon. Pure backtest: flat-vol model-repriced,
hold-to-expiry, entry-spaced (one position per name at a time), honest holdout.
Summary persisted to vrp_macro_sweep_results.

The single-name iron condor did NOT clear costs + the breach tail
(docs/research/vrp/single-name-condor-verdict.md). This asks whether matching the
structure to a directional view, on the tighter-spread macro names where the VRP is
well-sampled and durable, changes that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from statistics import median
from typing import Any

from uw_scan.reports.vrp_backtest import TradeResult, select_non_overlapping
from uw_scan.reports.vrp_markout import _events_overlap, _load_vrp_series
from uw_scan.reports.vrp_markout_core import apply_split_adjustment
from uw_scan.reports.vrp_structure import (
    CostModel,
    build_bull_put_spread,
    build_cash_secured_put,
    build_iron_condor,
)

log = logging.getLogger(__name__)

# Name → direction. "bullish" sells the downside only; "neutral" sells both sides.
DEFAULT_MACRO_DIRECTION: dict[str, str] = {
    "SPY": "bullish",
    "SPX": "bullish",
    "QQQ": "bullish",
    "IWM": "all",  # user: test IWM on condor + bull put spread + CSP
}
STRUCTURES_BY_DIRECTION: dict[str, tuple[str, ...]] = {
    "bullish": ("bull_put_spread", "cash_secured_put"),
    "neutral": ("iron_condor",),
    "all": ("iron_condor", "bull_put_spread", "cash_secured_put"),
}
# gate label → minimum vrp_z to enter (None = always-on, the purest systematic short)
GATES: dict[str, float | None] = {
    "always_on": None,
    "z>=0": 0.0,
    "z>=0.5": 0.5,
    "z>=1.0": 1.0,
}
SHORT_DELTAS: tuple[float, ...] = (0.16, 0.25, 0.30)
HORIZONS: tuple[int, ...] = (5, 20, 45)
WING_FRAC = 0.5  # wing_delta = short_delta * WING_FRAC → always 0 < wing < short < 0.5


@dataclass
class _Loaded:
    adj: list[tuple[_date, float]]
    pidx: dict[_date, int]
    rows: list[dict[str, Any]]
    events: list


def _load(repo, ticker: str) -> _Loaded | None:
    rows = _load_vrp_series(repo, ticker)
    adj = apply_split_adjustment(
        repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
    )
    if not rows or not adj:
        return None
    pidx = {d: k for k, (d, _v) in enumerate(adj)}
    return _Loaded(
        adj=adj, pidx=pidx, rows=rows, events=repo.fetch_earnings_events(ticker)
    )


def _build(kind: str, S: float, sigma: float, T: float, r: float, short_delta: float):
    wing = short_delta * WING_FRAC
    if kind == "iron_condor":
        return build_iron_condor(
            S, sigma, T, r, short_delta=short_delta, wing_delta=wing
        )
    if kind == "bull_put_spread":
        return build_bull_put_spread(
            S, sigma, T, r, short_delta=short_delta, wing_delta=wing
        )
    if kind == "cash_secured_put":
        return build_cash_secured_put(S, sigma, T, r, short_delta=short_delta)
    raise ValueError(f"unknown structure {kind!r}")


def _settle(
    structure,
    pi: int,
    hold_days: int,
    adj: list[tuple],
    iv_map: dict,
    r: float,
    *,
    cost: CostModel,
    contracts: int = 1,
    profit_take: float | None = None,
):
    """Path-aware exit. `profit_take=None` → hold to expiry, settle at intrinsic
    (model-free). `profit_take=f` → close the first day the cost-to-close falls to
    (1−f)·credit (i.e. f of max credit captured); the defined-risk wing is the stop,
    so no separate stop. Returns (net, ror, breached, exit_date, exit_spot)."""
    mult = cost.multiplier
    credit = structure.credit
    expiry_k = pi + hold_days
    exit_k, exit_val, breached = expiry_k, None, None
    if profit_take:
        target = (1.0 - profit_take) * credit
        for k in range(pi + 1, expiry_k):  # strictly before expiry
            d, S = adj[k]
            iv = iv_map.get(d)
            if iv is None or iv <= 0:
                continue
            cur = structure.value(S, (expiry_k - k) / 252.0, r, iv)
            if cur <= target:  # captured f of the credit → take profit
                exit_k, exit_val, breached = k, cur, False
                break
    if exit_val is None:  # held to expiry → intrinsic (T=0)
        _, S_T = adj[expiry_k]
        exit_val = structure.value(S_T, 0.0, r, 0.0)
        breached = structure.breached(S_T)
    d_exit, S_exit = adj[exit_k]
    gross = (credit - exit_val) * mult * contracts
    net = gross - cost.total(structure.leg_premiums, contracts)
    risk = structure.max_loss * mult * contracts
    ror = net / risk if risk > 0 else 0.0
    return net, ror, breached, d_exit, S_exit


def _backtest(
    loaded: _Loaded,
    ticker: str,
    *,
    kind: str,
    min_z: float | None,
    short_delta: float,
    hold_days: int,
    r: float,
    cost: CostModel,
    profit_take: float | None = None,
) -> list[TradeResult]:
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    t_years = hold_days / 252.0
    trades: list[TradeResult] = []
    for row in sorted(loaded.rows, key=lambda x: x["market_date"]):
        iv = row["iv"]
        if iv is None or float(iv) <= 0:
            continue
        z = row["vrp_z_20"]
        if min_z is not None and (z is None or float(z) < min_z):
            continue
        t = row["market_date"]
        pi = loaded.pidx.get(t)
        if pi is None or pi + hold_days >= len(loaded.adj):
            continue
        expiry_date, _S_T = loaded.adj[pi + hold_days]
        if _events_overlap(t, expiry_date, loaded.events):  # macro → no events → no-op
            continue
        S0 = loaded.adj[pi][1]
        if S0 <= 0:
            continue
        try:
            st = _build(kind, S0, float(iv), t_years, r, short_delta)
        except ValueError as exc:  # degenerate strikes — skip this day
            log.debug("structure build skipped %s %s: %s", ticker, kind, repr(exc))
            continue
        net, ror, breached, exit_date, exit_spot = _settle(
            st, pi, hold_days, loaded.adj, iv_map, r, cost=cost, profit_take=profit_take
        )
        trades.append(
            TradeResult(
                ticker=ticker,
                entry_date=t,
                expiry_date=exit_date,  # actual exit (early take-profit or expiry)
                spot_entry=S0,
                spot_exit=exit_spot,
                iv_entry=float(iv),
                entry_credit=st.credit,
                max_loss=st.max_loss,
                gross_pnl=net + cost.total(st.leg_premiums, 1),
                net_pnl=net,
                return_on_risk=ror,
                breached=breached,
                in_holdout=False,
            )
        )
    return select_non_overlapping(trades)  # entry-spacing + recomputed holdout flags


def _summarize(trades: list[TradeResult], *, scope: str) -> dict[str, Any]:
    sel = trades if scope == "full" else [t for t in trades if t.in_holdout]
    n = len(sel)
    if n == 0:
        return {
            "scope": scope,
            "n_trades": 0,
            "n_wins": 0,
            "win_rate": None,
            "total_net": None,
            "mean_net": None,
            "median_net": None,
            "mean_return_on_risk": None,
            "breakeven_win_rate": None,
            "breach_rate": None,
            "mean_credit": None,
        }
    nets = [t.net_pnl for t in sel]
    wins = [t for t in sel if t.net_pnl > 0]
    losses = [t for t in sel if t.net_pnl <= 0]
    win_ror = sum(t.return_on_risk for t in wins) / len(wins) if wins else 0.0
    loss_ror = sum(t.return_on_risk for t in losses) / len(losses) if losses else 0.0
    denom = win_ror - loss_ror
    breakeven = (-loss_ror / denom) if denom > 0 else None
    return {
        "scope": scope,
        "n_trades": n,
        "n_wins": len(wins),
        "win_rate": len(wins) / n,
        "total_net": sum(nets),
        "mean_net": sum(nets) / n,
        "median_net": median(nets),
        "mean_return_on_risk": sum(t.return_on_risk for t in sel) / n,
        "breakeven_win_rate": breakeven,
        "breach_rate": sum(1 for t in sel if t.breached) / n,
        "mean_credit": sum(t.entry_credit for t in sel) / n,
    }


def run_vrp_macro_harvest(
    *,
    repo,
    settings,
    directions: dict[str, str] | None = None,
    as_of: _date | None = None,
) -> dict[str, Any]:
    today = as_of or _date.today()
    directions = directions or DEFAULT_MACRO_DIRECTION
    r = settings.vrp_risk_free_rate
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    available = set(repo.fetch_distinct_vrp_tickers())
    repo.clear_vrp_macro_sweep_results()
    cells = 0
    for ticker, direction in directions.items():
        if ticker not in available:
            log.info("vrp_macro_harvest: %s not in vrp universe — skipping", ticker)
            continue
        loaded = _load(repo, ticker)
        if loaded is None:
            continue
        for kind in STRUCTURES_BY_DIRECTION[direction]:
            for gate, min_z in GATES.items():
                for short_delta in SHORT_DELTAS:
                    for hold_days in HORIZONS:
                        trades = _backtest(
                            loaded,
                            ticker,
                            kind=kind,
                            min_z=min_z,
                            short_delta=short_delta,
                            hold_days=hold_days,
                            r=r,
                            cost=cost,
                        )
                        if not trades:
                            continue
                        with repo.conn.transaction():
                            for scope in ("full", "holdout"):
                                repo.upsert_vrp_macro_sweep_result(
                                    ticker=ticker,
                                    structure=kind,
                                    gate=gate,
                                    short_delta=short_delta,
                                    hold_days=hold_days,
                                    as_of=today,
                                    **_summarize(trades, scope=scope),
                                )
                        cells += 1
    repo.conn.commit()
    return {"cells": cells, "names": sorted(set(directions) & available)}
