"""Model-repriced iron-condor backtest (hold-to-expiry).

For each RICH day with an earnings-clear forward window, build a flat-vol condor
at that day's spot+IV, then settle it against the corporate-action-adjusted
realized price `hold_days` trading days forward. Reports a full-history
characterization AND an honest latest-40%-holdout headline (HOLDOUT_FRAC). The
bucket verdict (vrp_harvest_by_sector) is a per-ticker GATE; rows are per ticker
and per sector. Full-rewrite; commits at the end.

LOOKAHEAD NOTE: scope='full' gates on the FINAL bucket verdict over the same
window it backtests → mild lookahead; scope='holdout' is the headline. Documented
in the plan (§Known limitations).

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from statistics import median
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout import RICH_Z, _events_overlap, _load_vrp_series
from uw_scan.reports.vrp_markout_core import HOLDOUT_FRAC, apply_split_adjustment
from uw_scan.reports.vrp_structure import (
    CostModel,
    build_iron_condor,
    condor_expiry_pnl,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeResult:
    ticker: str
    entry_date: _date
    expiry_date: _date
    spot_entry: float
    spot_exit: float
    iv_entry: float
    entry_credit: float
    max_loss: float
    gross_pnl: float
    net_pnl: float
    return_on_risk: float
    breached: bool
    in_holdout: bool


def single_trade_pnl(condor, S_T: float, *, cost: CostModel, contracts: int):
    """(net_dollars, return_on_risk, breached) for one condor held to expiry."""
    gross_per_share = condor_expiry_pnl(condor, S_T)
    gross = gross_per_share * cost.multiplier * contracts
    costs = cost.total(condor.leg_premiums, contracts)
    net = gross - costs
    risk = condor.max_loss * cost.multiplier * contracts
    ror = net / risk if risk > 0 else 0.0
    breached = S_T < condor.short_put or S_T > condor.short_call
    return net, ror, breached


def backtest_ticker(
    repo,
    ticker: str,
    *,
    hold_days: int,
    short_delta: float,
    wing_delta: float,
    r: float,
    cost_model: CostModel,
    contracts: int = 1,
) -> list[TradeResult]:
    rows = _load_vrp_series(repo, ticker)
    if not rows:
        return []
    adj = apply_split_adjustment(
        repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
    )
    if not adj:
        return []
    pidx = {d: k for k, (d, _v) in enumerate(adj)}
    events = repo.fetch_earnings_events(ticker)
    t_years = hold_days / 252.0
    ordered = sorted(rows, key=lambda x: x["market_date"])
    trades: list[TradeResult] = []
    for row in ordered:
        z = row["vrp_z_20"]
        iv = row["iv"]
        if z is None or iv is None or float(iv) <= 0 or float(z) < RICH_Z:
            continue  # iv<=0 collapses all strikes to spot (zero-width condor) — skip
        t = row["market_date"]
        pi = pidx.get(t)
        if pi is None or pi + hold_days >= len(adj):
            continue
        expiry_date, S_T = adj[pi + hold_days]
        # earnings-clear over the holding window (reuse the buffered overlap test)
        if _events_overlap(t, expiry_date, events):
            continue
        S0 = adj[pi][1]
        if S0 <= 0:
            continue
        condor = build_iron_condor(
            S0, float(iv), t_years, r, short_delta=short_delta, wing_delta=wing_delta
        )
        net, ror, breached = single_trade_pnl(
            condor, S_T, cost=cost_model, contracts=contracts
        )
        trades.append(
            TradeResult(
                ticker=ticker,
                entry_date=t,
                expiry_date=expiry_date,
                spot_entry=S0,
                spot_exit=S_T,
                iv_entry=float(iv),
                entry_credit=condor.credit,
                max_loss=condor.max_loss,
                gross_pnl=net + cost_model.total(condor.leg_premiums, contracts),
                net_pnl=net,
                return_on_risk=ror,
                breached=breached,
                in_holdout=False,
            )
        )
    # flag the latest HOLDOUT_FRAC of trades by entry_date as the honest holdout
    n = len(trades)
    if n:
        cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
        trades = [
            TradeResult(**{**t.__dict__, "in_holdout": i >= cut})
            for i, t in enumerate(sorted(trades, key=lambda x: x.entry_date))
        ]
    return trades


def summarize(trades: list[TradeResult], *, scope: str) -> dict[str, Any]:
    sel = trades if scope == "full" else [t for t in trades if t.in_holdout]
    n = len(sel)
    if n == 0:
        return {
            "scope": scope,
            "n_trades": 0,
            "n_wins": 0,
            "win_rate": None,
            "mean_net": None,
            "median_net": None,
            "total_net": None,
            "mean_return_on_risk": None,
            "breach_rate": None,
            "mean_credit": None,
        }
    nets = [t.net_pnl for t in sel]
    wins = sum(1 for x in nets if x > 0)
    return {
        "scope": scope,
        "n_trades": n,
        "n_wins": wins,
        "win_rate": wins / n,
        "mean_net": sum(nets) / n,
        "median_net": median(nets),
        "total_net": sum(nets),
        "mean_return_on_risk": sum(t.return_on_risk for t in sel) / n,
        "breach_rate": sum(1 for t in sel if t.breached) / n,
        "mean_credit": sum(t.entry_credit for t in sel) / n,
    }


def _sellable_sectors(repo) -> set[str]:
    """Sectors whose RICH single-name bucket is HARVEST_SELLABLE (the gate)."""
    out: set[str] = set()
    for r in repo.fetch_vrp_harvest_by_sector():
        if r["deviation_class"] == "RICH" and r["verdict"] == "HARVEST_SELLABLE":
            out.add(r["sector"])
    return out


def run_vrp_backtest(*, repo, settings, hold_days: int | None = None) -> dict[str, Any]:
    today = _date.today()
    hd = hold_days or settings.vrp_hold_days
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    sellable = _sellable_sectors(repo)
    repo.clear_vrp_backtest_results()
    repo.clear_vrp_backtest_trades()
    by_sector: dict[str, list[TradeResult]] = defaultdict(list)
    n_units = 0
    for ticker in repo.fetch_distinct_vrp_tickers():
        sector = repo.fetch_watchlist_sector(ticker)
        ac = asset_class_baseline(ticker, sector=sector)["asset_class"]
        # v1 gate: ONLY the validated single-name-by-sector edge is tradable.
        # index_macro / sector_etf / credit have no studied sector bucket → skip.
        if ac != "single_name":
            continue
        if (sector or "unknown") not in sellable:
            continue
        # ISSUE-6: a single name with no earnings calendar cannot honor the
        # (entry, expiry] earnings exclusion → would manufacture a SELLABLE edge.
        # Mirrors run_vrp_markout's single_name skip-guard.
        if not repo.fetch_historical_earnings_dates(ticker):
            continue
        try:
            trades = backtest_ticker(
                repo,
                ticker,
                hold_days=hd,
                short_delta=settings.vrp_short_delta,
                wing_delta=settings.vrp_wing_delta,
                r=settings.vrp_risk_free_rate,
                cost_model=cost,
            )
            if not trades:
                continue
            # SAVEPOINT per ticker: one bad ticker's upsert cannot abort the whole
            # full-rewrite (psycopg3 conn.transaction() nests as a savepoint).
            with repo.conn.transaction():
                for t in trades:
                    repo.upsert_vrp_backtest_trade(
                        ticker=t.ticker,
                        entry_date=t.entry_date,
                        hold_days=hd,
                        expiry_date=t.expiry_date,
                        spot_entry=t.spot_entry,
                        spot_exit=t.spot_exit,
                        iv_entry=t.iv_entry,
                        entry_credit=t.entry_credit,
                        max_loss=t.max_loss,
                        gross_pnl=t.gross_pnl,
                        net_pnl=t.net_pnl,
                        return_on_risk=t.return_on_risk,
                        breached=t.breached,
                        in_holdout=t.in_holdout,
                    )
                for scope in ("full", "holdout"):
                    repo.upsert_vrp_backtest_result(
                        unit_type="ticker",
                        unit_key=ticker,
                        hold_days=hd,
                        as_of=today,
                        **summarize(trades, scope=scope),
                    )
            n_units += 1
            if sector:
                by_sector[sector].extend(trades)
        except Exception as exc:  # noqa: BLE001
            log.exception("vrp_backtest ticker %s failed: %s", ticker, repr(exc))
    with repo.conn.transaction():
        for sector, trades in by_sector.items():
            for scope in ("full", "holdout"):
                repo.upsert_vrp_backtest_result(
                    unit_type="bucket",
                    unit_key=sector,
                    hold_days=hd,
                    as_of=today,
                    **summarize(trades, scope=scope),
                )
    repo.conn.commit()
    return {"units": n_units, "hold_days": hd, "sellable_sectors": sorted(sellable)}
