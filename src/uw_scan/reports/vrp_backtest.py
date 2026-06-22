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

from uw_scan.reports.vrp_gate import (
    passes_gate,
    sellable_asset_classes,
    sellable_single_name_sectors,
)
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
    return flag_holdout(trades)


def flag_holdout(trades: list[TradeResult]) -> list[TradeResult]:
    """Tag the latest HOLDOUT_FRAC of trades (by entry_date) as the honest holdout.

    Returns a fresh list with `in_holdout` set; the input is not mutated. Recompute
    this whenever the trade SET changes (e.g. after entry-spacing) so the holdout
    headline reflects the trades you would actually have taken.
    """
    n = len(trades)
    if not n:
        return list(trades)
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    return [
        TradeResult(**{**t.__dict__, "in_holdout": i >= cut})
        for i, t in enumerate(sorted(trades, key=lambda x: x.entry_date))
    ]


def select_non_overlapping(trades: list[TradeResult]) -> list[TradeResult]:
    """Entry-spacing: keep only the trades you could hold one-at-a-time per name.

    The naive backtest opens a condor on EVERY RICH day, so a name that stays rich
    for weeks contributes dozens of overlapping positions — inflating trade counts
    and total P&L into something untradeable. This greedy "trade only when flat"
    pass walks the candidate trades by entry_date and keeps one only if it opens
    strictly AFTER the prior kept trade's expiry. The result is a realistic
    sequential equity curve for a single name (positions across DIFFERENT names may
    still overlap — that is a real portfolio of condors). Holdout flags are
    recomputed on the surviving set.
    """
    kept: list[TradeResult] = []
    last_expiry: _date | None = None
    for t in sorted(trades, key=lambda x: x.entry_date):
        if last_expiry is None or t.entry_date > last_expiry:
            kept.append(t)
            last_expiry = t.expiry_date
    return flag_holdout(kept)


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


# Historical name kept for the research notebook's import.
_sellable_sectors = sellable_single_name_sectors


def run_vrp_backtest(*, repo, settings, hold_days: int | None = None) -> dict[str, Any]:
    today = _date.today()
    hd = hold_days or settings.vrp_hold_days
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    sellable_sectors = sellable_single_name_sectors(repo)
    sellable_classes = sellable_asset_classes(repo, hold_days=hd)
    repo.clear_vrp_backtest_results()
    repo.clear_vrp_backtest_trades()
    by_bucket: dict[str, list[TradeResult]] = defaultdict(list)
    n_units = 0
    for ticker in repo.fetch_distinct_vrp_tickers():
        # Gate: single_name → sellable sector + earnings calendar;
        # index_macro/sector_etf/credit → sellable asset-class at this horizon.
        gate = passes_gate(
            repo,
            ticker,
            sellable_sectors=sellable_sectors,
            sellable_classes=sellable_classes,
        )
        if gate is None:
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
            by_bucket[gate.bucket_key].extend(trades)
        except Exception as exc:  # noqa: BLE001
            log.exception("vrp_backtest ticker %s failed: %s", ticker, repr(exc))
    with repo.conn.transaction():
        for bucket, trades in by_bucket.items():
            for scope in ("full", "holdout"):
                repo.upsert_vrp_backtest_result(
                    unit_type="bucket",
                    unit_key=bucket,
                    hold_days=hd,
                    as_of=today,
                    **summarize(trades, scope=scope),
                )
    repo.conn.commit()
    return {
        "units": n_units,
        "hold_days": hd,
        "sellable_sectors": sorted(sellable_sectors),
        "sellable_classes": sorted(sellable_classes),
    }
