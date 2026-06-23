"""Delta×tenor×fee sweep for the GOAS put-write, with regime slices and a
sweet-spot ranking. Caller runs it once per pricing mode (flat vs calibrated
skew) by passing skew=None or the calibrated PutSkew. Fee tiers are derived
analytically from the post-cost NAV curve (no re-simulation).
Design: docs/superpowers/specs/2026-06-23-goas-putwrite-delta-sweep-design.md
"""

from __future__ import annotations

from datetime import date as _date

from uw_scan.reports.goas_putwrite_account import (
    GoasConfig,
    curve_metrics,
    putwrite_metrics,
    simulate_putwrite,
    spy_buy_hold,
)
from uw_scan.reports.goas_putwrite_pricing import PutSkew
from uw_scan.reports.vrp_macro_harvest import _Loaded

DELTAS: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
DTES: tuple[int, ...] = (21, 30, 42, 63)
FEE_GRID: tuple[float, ...] = (0.0, 0.005, 0.010, 0.015)
RANK_FEE: float = (
    0.010  # management-fee basis for the sweet-spot ranking (GOAS-like 1%/yr)
)
PRICING_MODES: tuple[str, ...] = ("flat", "skew")
# (label, start, end) — stress windows + a full-history marker (None,None → all).
# "calm" (full minus the stress windows) is added per cell in run_sweep.
REGIMES: tuple[tuple[str, _date | None, _date | None], ...] = (
    ("full", None, None),
    ("gfc_2008", _date(2008, 1, 1), _date(2009, 6, 30)),
    ("covid_2020", _date(2020, 2, 15), _date(2020, 4, 30)),
    ("bear_2022", _date(2022, 1, 1), _date(2022, 12, 31)),
)
_STRESS = tuple((s, e) for _label, s, e in REGIMES if s is not None)


def apply_fee_to_curve(curve, mgmt_fee_annual: float):
    """Daily management-fee drag: net[t] = net[t-1]·(1 + pre-fee return_t)·(1 − fee/252).
    No fee on the seed point (day 0); compounds on the prior NET NAV (not gross)."""
    if not curve:
        return []
    daily = mgmt_fee_annual / 252.0
    out = [curve[0]]
    prev_src, prev_net = curve[0][1], curve[0][1]
    for d, v in curve[1:]:
        r_t = (v / prev_src - 1.0) if prev_src > 0 else 0.0
        net = prev_net * (1.0 + r_t) * (1.0 - daily)
        out.append((d, net))
        prev_src, prev_net = v, net
    return out


def slice_curve(curve, start: _date | None, end: _date | None):
    return [
        (d, v)
        for d, v in curve
        if (start is None or d >= start) and (end is None or d <= end)
    ]


def _calm_slice(curve):
    """Full history minus the named stress windows."""
    return [(d, v) for d, v in curve if not any(s <= d <= e for s, e in _STRESS)]


def run_sweep(
    loaded: _Loaded,
    *,
    skew: PutSkew | None,
    fee_grid=FEE_GRID,
    rank_fee: float = RANK_FEE,
    r: float = 0.04,
) -> dict:
    """All cells for ONE pricing mode (skew=None → flat; a PutSkew → skew). Fee tiers
    derived from the post-cost curve; ranking + regimes measured net-of-fee at rank_fee."""
    pricing = "skew" if skew is not None else "flat"
    cells: list[dict] = []
    for delta in DELTAS:
        for dte in DTES:
            cfg = GoasConfig(short_delta=delta, dte_days=dte, skew=skew, r=r)
            res = simulate_putwrite(loaded, cfg)
            base = putwrite_metrics(res, r=r)  # post-cost/pre-fee; "gross" nested
            fees = {
                f: curve_metrics(apply_fee_to_curve(res.equity_curve_costed, f), r=r)
                for f in fee_grid
            }
            rank_curve = apply_fee_to_curve(res.equity_curve_costed, rank_fee)
            rank_metric = curve_metrics(rank_curve, r=r)
            regimes = {
                label: curve_metrics(slice_curve(rank_curve, s, e), r=r)
                for label, s, e in REGIMES
            }
            regimes["calm"] = curve_metrics(_calm_slice(rank_curve), r=r)
            cells.append(
                {
                    "delta": delta,
                    "dte": dte,
                    "pricing": pricing,
                    "n_trades": base["n_trades"],
                    "span": res.span,
                    "gross": base["gross"],
                    "costed": {k: v for k, v in base.items() if k != "gross"},
                    "fees": fees,
                    "rank": rank_metric,
                    "regimes": regimes,
                }
            )
    benchmark = spy_buy_hold(loaded, r=r)
    return {
        "cells": cells,
        "benchmark": benchmark,
        "rank_fee": rank_fee,
        "ranking": rank_cells(cells),
    }


def rank_cells(cells: list[dict]) -> list[dict]:
    """Rank by net-of-fee Sharpe (measured at RANK_FEE), DROPPING any cell that
    catastrophically degrades in a stress regime (per-regime gate, AC-F4 style):
    a stress-window Sharpe below −1.0 disqualifies."""

    def survives(c: dict) -> bool:
        for label in ("gfc_2008", "covid_2020", "bear_2022"):
            reg = c["regimes"].get(label, {})
            if reg.get("n_days", 0) > 5 and reg.get("sharpe", 0.0) < -1.0:
                return False
        return True

    ranked = sorted(
        (c for c in cells if survives(c)),
        key=lambda c: c["rank"]["sharpe"],
        reverse=True,
    )
    return [
        {
            "delta": c["delta"],
            "dte": c["dte"],
            "pricing": c["pricing"],
            "sharpe": c["rank"]["sharpe"],
            "ann_return": c["rank"]["ann_return"],
            "max_drawdown": c["rank"]["max_drawdown"],
            "calmar": c["rank"]["calmar"],
        }
        for c in ranked
    ]
