"""Laddered, constant-size, cash-secured SPY put-writing account on a daily NAV
curve. Always-on (no vol gate). Held to expiry; expiry SETTLEMENT and realized
P&L are intrinsic (model-free). Open positions are marked daily at FAIR VALUE
(BS at the current ATM vol + same skew) so theta is earned gradually and
selloffs draw the curve down properly — NO entry-day premium front-loading
(at entry, fair value ≈ credit → unrealized ≈ 0). Two ledgers (realized_gross,
realized_cost) → gross + post-cost curves; the management fee is a downstream
drag (see goas_putwrite_sweep.apply_fee_to_curve).

GOAS's 4–5 week ramp-in is realized by NATURAL laddered accumulation: the book
fills to ~dte_days/cadence_days concurrent puts over the first ~dte_days.
Design: docs/superpowers/specs/2026-06-23-goas-putwrite-delta-sweep-design.md
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from statistics import fmean, pstdev

from uw_scan.reports.goas_putwrite_pricing import PutSkew, build_csp_skew
from uw_scan.reports.vrp_macro_harvest import _Loaded
from uw_scan.reports.vrp_structure import CostModel, bs_price

log = logging.getLogger(__name__)

_DEFAULT_COST = CostModel(
    per_contract=0.65, slippage_frac=0.01, slippage_min=0.05, round_trip=True
)


@dataclass(frozen=True)
class GoasConfig:
    short_delta: float
    dte_days: int
    cadence_days: int = 5
    capital: float = 1_000_000.0
    skew: PutSkew | None = None
    r: float = 0.04
    cost: CostModel | None = None
    multiplier: int = 100
    # No mgmt-fee field — the fee is a deterministic downstream NAV drag
    # (apply_fee_to_curve on the post-cost curve), swept over FEE_GRID.

    @property
    def cost_model(self) -> CostModel:
        return self.cost if self.cost is not None else _DEFAULT_COST


@dataclass
class PutWriteTrade:
    entry_date: _date
    expiry_date: _date
    strike: float
    credit: float
    iv_entry: float
    contracts: float
    intrinsic: float
    net_pnl: float
    return_on_risk: float
    breached: bool


@dataclass
class PutWriteResult:
    equity_curve_gross: list[tuple[_date, float]]  # pre-cost, pre-fee (TRUE gross)
    equity_curve_costed: list[tuple[_date, float]]  # post-cost, pre-fee
    trades: list[PutWriteTrade]
    span: tuple[str, str]


def simulate_putwrite(loaded: _Loaded, cfg: GoasConfig) -> PutWriteResult:
    adj = loaded.adj
    n = len(adj)
    iv_at = {row["market_date"]: row["iv"] for row in loaded.rows}
    cost = cfg.cost_model
    mult = cfg.multiplier
    slots = max(1, round(cfg.dte_days / cfg.cadence_days))
    collateral_per_put = cfg.capital / slots
    t_years = cfg.dte_days / 252.0
    daily_rf = cfg.r / 252.0  # cash collateral (cash-secured) earns the risk-free

    # open positions: list of dicts with expiry_index, strike, credit, contracts.
    # Two ledgers: realized_gross (pre-cost) and realized_cost (transaction costs).
    open_pos: list[dict] = []
    trades: list[PutWriteTrade] = []
    realized_gross = 0.0
    realized_cost = 0.0
    curve_gross: list[tuple[_date, float]] = []
    curve_costed: list[tuple[_date, float]] = []

    for i in range(n):
        d, S = adj[i]
        # 1) settle expiries due today
        still_open: list[dict] = []
        for p in open_pos:
            if p["expiry_index"] == i:
                _, s_exp = adj[i]
                intrinsic = max(0.0, p["strike"] - s_exp)
                gross = (p["credit"] - intrinsic) * mult * p["contracts"]
                trade_cost = cost.total((p["credit"],), p["contracts"])
                net = gross - trade_cost
                realized_gross += gross
                realized_cost += trade_cost
                risk = (p["strike"] - p["credit"]) * mult * p["contracts"]
                trades.append(
                    PutWriteTrade(
                        entry_date=p["entry_date"],
                        expiry_date=d,
                        strike=p["strike"],
                        credit=p["credit"],
                        iv_entry=p["iv_entry"],
                        contracts=p["contracts"],
                        intrinsic=intrinsic,
                        net_pnl=net,
                        return_on_risk=(net / risk if risk > 0 else 0.0),
                        breached=(s_exp < p["strike"]),
                    )
                )
            else:
                still_open.append(p)
        open_pos = still_open

        # 2) open a new put on cadence days when there is room before history ends
        iv = iv_at.get(d)
        if (
            i % cfg.cadence_days == 0
            and iv is not None
            and float(iv) > 0
            and S > 0
            and i + cfg.dte_days < n
        ):
            try:
                csp = build_csp_skew(
                    S,
                    float(iv),
                    t_years,
                    cfg.r,
                    short_delta=cfg.short_delta,
                    skew=cfg.skew,
                )
                contracts = collateral_per_put / (csp.short_put * mult)
                open_pos.append(
                    {
                        "entry_index": i,
                        "expiry_index": i + cfg.dte_days,
                        "entry_date": d,
                        "strike": csp.short_put,
                        "credit": csp.credit,
                        "iv_entry": float(iv),
                        "contracts": contracts,
                    }
                )
            except ValueError as exc:  # degenerate / un-bracketable strike — skip entry
                log.debug("putwrite entry skipped %s: %s", d, repr(exc))

        # 3) mark NAV: realized + unrealized(open marked at FAIR VALUE) − costs.
        # Fair-value marks earn theta gradually and draw down on selloffs; at entry
        # value ≈ credit so the mark adds ≈ 0 (no premium front-load). Falls back to
        # intrinsic only if the day's IV is missing or the position is at expiry.
        atm_t = iv_at.get(d)
        unrealized = 0.0
        for p in open_pos:
            t_rem = (p["expiry_index"] - i) / 252.0
            if atm_t is not None and float(atm_t) > 0 and t_rem > 0:
                iv_mark = (
                    cfg.skew.iv(float(atm_t), S, p["strike"])
                    if cfg.skew
                    else float(atm_t)
                )
                val = bs_price(S, p["strike"], t_rem, cfg.r, iv_mark, is_call=False)
            else:
                val = max(0.0, p["strike"] - S)
            unrealized += (p["credit"] - val) * mult * p["contracts"]
        # cash-secured collateral earns the risk-free (CBOE PUT-index convention):
        # without it a ~3% premium harvest is penalized vs a 4% rf it actually earns.
        collateral = (
            cfg.capital * (1.0 + daily_rf) ** i
        )  # i=0 → capital (no day-0 interest)
        nav_gross = collateral + realized_gross + unrealized
        nav_costed = collateral + realized_gross - realized_cost + unrealized
        curve_gross.append((d, nav_gross))
        curve_costed.append((d, nav_costed))

    span = (adj[0][0].isoformat(), adj[-1][0].isoformat()) if adj else ("", "")
    return PutWriteResult(curve_gross, curve_costed, trades, span)


def curve_metrics(curve: list[tuple[_date, float]], *, r: float = 0.04) -> dict:
    """Risk metrics from a daily NAV curve. Sharpe = arithmetic mean daily EXCESS
    return / daily vol, annualized ×√252 (ann_return stays geometric CAGR for
    reporting); CVaR is the mean of the worst 5% daily returns; worst_month is the
    min calendar-month compounded return."""
    navs = [v for _, v in curve]
    n = len(navs)
    if n < 2 or navs[0] <= 0:
        return {
            "ann_return": 0.0,
            "ann_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "cvar5": 0.0,
            "worst_month": 0.0,
            "n_days": n,
        }
    rets = [
        (navs[i] / navs[i - 1] - 1.0) if navs[i - 1] > 0 else 0.0 for i in range(1, n)
    ]
    years = (n - 1) / 252.0  # n NAV points → n-1 daily return intervals
    ann_return = (navs[-1] / navs[0]) ** (1.0 / years) - 1.0 if navs[-1] > 0 else -1.0
    ann_vol = pstdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    daily_rf = r / 252.0
    _sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (
        (fmean([x - daily_rf for x in rets]) / _sd) * math.sqrt(252) if _sd > 0 else 0.0
    )
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1.0)
    calmar = ann_return / abs(max_dd) if max_dd < 0 else 0.0
    k = max(1, int(len(rets) * 0.05))
    cvar5 = fmean(sorted(rets)[:k]) if rets else 0.0
    by_month: dict[tuple[int, int], list[float]] = defaultdict(list)
    for (d, _), ret in zip(curve[1:], rets, strict=True):
        by_month[(d.year, d.month)].append(ret)
    monthly = [math.prod(1.0 + x for x in v) - 1.0 for v in by_month.values()]
    worst_month = min(monthly) if monthly else 0.0
    return {
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "cvar5": cvar5,
        "worst_month": worst_month,
        "n_days": n,
    }


def putwrite_metrics(result: PutWriteResult, *, r: float = 0.04) -> dict:
    # base tier = post-cost/pre-fee (costed); gross (pre-cost) nested under "gross".
    # Fee tiers are derived downstream (apply_fee_to_curve over FEE_GRID).
    gross = curve_metrics(result.equity_curve_gross, r=r)
    costed = curve_metrics(result.equity_curve_costed, r=r)
    tr = result.trades
    n = len(tr)
    return {
        **costed,
        "gross": gross,
        "win_rate": (sum(1 for t in tr if t.net_pnl > 0) / n) if n else 0.0,
        "breach_rate": (sum(1 for t in tr if t.breached) / n) if n else 0.0,
        "mean_credit": (fmean([t.credit for t in tr]) if n else 0.0),
        "n_trades": n,
    }


def spy_buy_hold(
    loaded: _Loaded, *, capital: float = 1_000_000.0, r: float = 0.04
) -> dict:
    """Price-return SPY benchmark (lake has no dividends → understates total return)."""
    if not loaded.adj:
        return curve_metrics([], r=r)
    s0 = loaded.adj[0][1]
    curve = [(d, capital * (s / s0)) for d, s in loaded.adj]
    return curve_metrics(curve, r=r)
