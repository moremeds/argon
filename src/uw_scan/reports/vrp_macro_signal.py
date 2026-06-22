"""Macro short-vol signal — the promoted winner config + its laddered/sized
backtest + a current-week readout for (manual or automated) execution.

The 20-yr SPX+VIX sweep (docs/research/vrp/macro-short-vol-verdict.md, reproduced
by scripts/_vrp_macro_param_sweep.py) found the dominant lever is **sizing by how
rich vol is**, not the structure or the entry-spacing. The winner:

    bull put spread · short_delta 0.25 / wing 0.125 · ~30 trading-day hold ·
    weekly entry · `ramp+` vrp-z sizing (0 at z<=0, full at z>=0.5) · hold to expiry

→ SPX monthly-ROR Sharpe ~1.65 (in-sample-tuned; discount to ~1.3-1.6 live),
and the *same* config rescues QQQ from 0.27 to 1.00 out-of-sample — i.e. the edge
is structural index-VRP, not SPX-overfit.

This module makes that config first-class engine code instead of script-only:
`WINNER` is the canonical default, `backtest_laddered` is the tested engine that
reproduces the note's headline Sharpe, and `current_macro_signal` emits the
actionable weekly readout (vrp_z → size weight → strikes/credit/max-loss).

Research/engine layer: like `vrp_macro_drawdown`, it returns results rather than
persisting them. Wiring `current_macro_signal` to a nightly job + table (so the
weekly readout lands in Postgres and the UI) is the deploy step, deliberately
left out of this slice.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from math import sqrt
from statistics import fmean, pstdev
from typing import Any

from uw_scan.reports.vrp_macro_drawdown import _Loaded, load_index_vol
from uw_scan.reports.vrp_macro_harvest import _settle
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread


@dataclass(frozen=True)
class MacroSignalConfig:
    """The promoted winner. Defaults ARE the canonical config; override per call
    only for research. `wing_delta = short_delta * wing_frac` keeps the long wing
    strictly inside the short strike (0 < wing < short < 0.5)."""

    short_delta: float = 0.25
    wing_frac: float = 0.5  # → wing_delta 0.125
    hold_days: int = 30  # ~30 trading days ≈ 40-45 calendar DTE (VIX is 30d IV)
    cadence: int = 5  # weekly entry (5 trading days)
    sizing: str = "ramp+"  # the dominant lever; see size_weight()
    ramp_full_z: float = 0.5  # full size at vrp_z >= this; 0 at z <= 0
    structure: str = "bull_put_spread"

    @property
    def wing_delta(self) -> float:
        return self.short_delta * self.wing_frac


WINNER = MacroSignalConfig()


def size_weight(z: float | None, cfg: MacroSignalConfig = WINNER) -> float:
    """vrp-z → position-size multiplier in [0, 1]. `always` ignores the signal;
    every gated rule treats an undefined z (insufficient history) as skip (0).
        gate0 : 1 if z>=0 else 0
        ramp  : 1 at z>=0, linear→0 at z=-ramp_full_z, 0 below
        ramp+ : 0 at z<=0, linear→1 at z>=ramp_full_z   (the winner)"""
    if cfg.sizing == "always":
        return 1.0
    if z is None:
        return 0.0
    if cfg.sizing == "gate0":
        return 1.0 if z >= 0 else 0.0
    if cfg.sizing == "ramp":
        return 1.0 if z >= 0 else max(0.0, (z + cfg.ramp_full_z) / cfg.ramp_full_z)
    if cfg.sizing == "ramp+":
        return min(1.0, max(0.0, z / cfg.ramp_full_z))
    raise ValueError(f"unknown sizing rule {cfg.sizing!r}")


def _sharpe_maxdd(monthly: dict) -> tuple[float, float, float]:
    """Zero-fill the contiguous month span; return (annualized Sharpe, maxDD of the
    cumulative curve, annualized mean return). ROR excludes the risk-free rate (it is
    earned on collateral), so monthly ROR is already an excess return."""
    if not monthly:
        return float("nan"), 0.0, 0.0
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    series: list[float] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        series.append(monthly.get((y, m), 0.0))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    sd = pstdev(series)
    sharpe = fmean(series) / sd * sqrt(12) if sd > 0 else float("nan")
    cum = peak = mdd = 0.0
    for x in series:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return sharpe, mdd, fmean(series) * 12


def _cost_model(settings) -> CostModel:
    return CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )


def backtest_laddered(
    loaded: _Loaded,
    settings,
    cfg: MacroSignalConfig = WINNER,
    *,
    min_date: _date | None = None,
) -> dict[str, Any]:
    """Weekly-laddered, vrp-z-sized bull-put-spread backtest — the engine version of
    the research sweep's winning cell. Constant-risk (slot-account): each month's
    book return is the size-weighted sum of rung RORs exiting that month, divided by
    the number of concurrent slots (≈ hold_days / cadence). Returns monthly-ROR
    Sharpe, maxDD, Calmar and the per-month series (so sleeves can be composed)."""
    if cfg.structure != "bull_put_spread":
        raise ValueError(
            f"backtest_laddered only supports bull_put_spread, got {cfg.structure!r}"
        )
    adj = loaded.adj
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    z_map = {row["market_date"]: row["vrp_z_20"] for row in loaded.rows}
    cost = _cost_model(settings)
    r = settings.vrp_risk_free_rate
    n = len(adj)
    max_slots = max(1, round(cfg.hold_days / cfg.cadence))
    by_month: dict[tuple[int, int], float] = defaultdict(float)
    nrung = 0
    for pi in range(0, n - cfg.hold_days, cfg.cadence):
        d, s0 = adj[pi]
        if min_date and d < min_date:
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        w = size_weight(z_map.get(d), cfg)
        if w <= 0:
            continue
        try:
            st = build_bull_put_spread(
                s0,
                float(iv),
                cfg.hold_days / 252.0,
                r,
                short_delta=cfg.short_delta,
                wing_delta=cfg.wing_delta,
            )
        except ValueError:
            continue
        _net, ror, _breached, exit_date, _spot = _settle(
            st, pi, cfg.hold_days, adj, iv_map, r, cost=cost, contracts=1
        )
        by_month[(exit_date.year, exit_date.month)] += w * ror
        nrung += 1
    monthly = {k: v / max_slots for k, v in by_month.items()}
    sharpe, maxdd, annror = _sharpe_maxdd(monthly)
    return {
        "n": nrung,
        "sharpe": sharpe,
        "maxdd": maxdd,
        "annror": annror,
        "calmar": (annror / abs(maxdd)) if maxdd < 0 else float("inf"),
        "monthly": monthly,
    }


@dataclass(frozen=True)
class MacroSignal:
    """The actionable weekly readout. `action` is TRADE iff `weight > 0`; on SKIP the
    structure fields are None. Strikes/credit/max_loss are flat-vol modeled (the real
    put-skew credit is >= this), so treat `credit` as a conservative floor."""

    name: str
    as_of: _date
    spot: float
    iv: float
    rv20: float | None
    vrp: float | None
    vrp_z: float | None
    weight: float
    action: str  # "TRADE" | "SKIP"
    short_put: float | None
    long_put: float | None
    credit: float | None
    max_loss: float | None
    put_width: float | None
    hold_days: int
    short_delta: float
    wing_delta: float


def current_macro_signal(
    repo,
    settings,
    name: str = "SPX",
    cfg: MacroSignalConfig = WINNER,
    *,
    as_of: _date | None = None,
    lake_root=None,
) -> MacroSignal:
    """Compute this week's signal for `name` (default SPX) as of `as_of` (default the
    latest available close). Picks the most recent row with usable IV+spot on or
    before the cutoff, maps vrp_z → size weight, and (if trading) builds the modeled
    bull put spread to quote strikes/credit/max-loss for a manual or automated fill."""
    loaded = load_index_vol(repo, name, lake_root=lake_root)
    spot_map = dict(loaded.adj)
    chosen: dict | None = None
    for row in reversed(loaded.rows):
        d = row["market_date"]
        if as_of is not None and d > as_of:
            continue
        iv = row["iv"]
        if iv is None or iv <= 0 or spot_map.get(d, 0.0) <= 0:
            continue
        chosen = row
        break
    if chosen is None:
        raise ValueError(f"no usable {name} vol row on or before {as_of or 'latest'}")
    d = chosen["market_date"]
    spot = spot_map[d]
    iv = float(chosen["iv"])
    z = chosen["vrp_z_20"]
    w = size_weight(z, cfg)
    common = dict(
        name=name,
        as_of=d,
        spot=spot,
        iv=iv,
        rv20=chosen.get("rv"),
        vrp=chosen.get("vrp"),
        vrp_z=z,
        hold_days=cfg.hold_days,
        short_delta=cfg.short_delta,
        wing_delta=cfg.wing_delta,
    )
    if w <= 0:
        return MacroSignal(
            weight=0.0,
            action="SKIP",
            short_put=None,
            long_put=None,
            credit=None,
            max_loss=None,
            put_width=None,
            **common,
        )
    st = build_bull_put_spread(
        spot,
        iv,
        cfg.hold_days / 252.0,
        settings.vrp_risk_free_rate,
        short_delta=cfg.short_delta,
        wing_delta=cfg.wing_delta,
    )
    return MacroSignal(
        weight=w,
        action="TRADE",
        short_put=st.short_put,
        long_put=st.long_put,
        credit=st.credit,
        max_loss=st.max_loss,
        put_width=st.put_width,
        **common,
    )
