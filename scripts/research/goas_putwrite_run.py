#!/usr/bin/env python
"""GOAS put-write delta sweep — real-data run.

Loads SPY (spot) + VIX (ATM IV) daily closes 2006→ directly from the
market-warehouse lake (`bronze/asset_class={equity,volatility}/symbol={SPY,VIX}/
1d.parquet` — the same source that feeds uw_scan.vol_index_daily, read here without
Postgres so the research run is fully local + reproducible). Calibrates the downside
skew to GOAS's published 96.2%/0.7% 1-month quote at the 2026-05-05 VIX, runs the
delta×tenor sweep under BOTH flat and skew pricing, and writes CSV traces + a
findings note under docs/research/goas-putwrite/.

Reproduce:
  uv run python scripts/research/goas_putwrite_run.py
  (reads ~/market-warehouse/data-lake by default; override with MARKET_WAREHOUSE_LAKE)
"""

from __future__ import annotations

import csv
import os
import pathlib
from datetime import date

import pyarrow.parquet as pq

from uw_scan.reports.goas_putwrite_account import GoasConfig, simulate_putwrite
from uw_scan.reports.goas_putwrite_pricing import (
    GOAS_AS_OF,
    GOAS_DTE_DAYS,
    GOAS_PREMIUM_FRAC,
    GOAS_STRIKE_FRAC,
    calibrate_skew,
)
from uw_scan.reports.goas_putwrite_sweep import run_sweep
from uw_scan.reports.vrp_macro_drawdown import _build_loaded

OUT = pathlib.Path("docs/research/goas-putwrite")
STAMP = "2026-06-23"
R = 0.04  # flat risk-free for BS (matches settings.vrp_risk_free_rate default)
START = date(2006, 1, 1)


def _lake_root() -> pathlib.Path:
    return pathlib.Path(
        os.environ.get(
            "MARKET_WAREHOUSE_LAKE",
            str(pathlib.Path.home() / "market-warehouse" / "data-lake"),
        )
    )


def _daily_closes(asset: str, sym: str) -> dict[date, float]:
    p = (
        _lake_root()
        / "bronze"
        / f"asset_class={asset}"
        / f"symbol={sym}"
        / "1d.parquet"
    )
    t = pq.read_table(str(p), columns=["trade_date", "close"])
    out: dict[date, float] = {}
    for d, c in zip(t.column("trade_date").to_pylist(), t.column("close").to_pylist()):
        if d is None or c is None:
            continue
        dd = d.date() if hasattr(d, "date") else d
        if dd >= START:
            out[dd] = float(c)
    return out


def _asof(series: dict[date, float], target: date) -> tuple[date, float]:
    if target in series:
        return target, series[target]
    prior = [d for d in series if d <= target]
    d = max(prior)
    return d, series[d]


def _write_master_note(
    flat: dict, skewed: dict, asof_spot: float, asof_vix: float
) -> None:
    ftop = flat["ranking"][0] if flat["ranking"] else None
    stop = skewed["ranking"][0] if skewed["ranking"] else None
    agree = bool(
        ftop and stop and (ftop["delta"], ftop["dte"]) == (stop["delta"], stop["dte"])
    )
    bench = skewed["benchmark"]
    flip = (
        ""
        if agree
        else (
            " → ranking is skew-sensitive; treat the sweet spot as UNRESOLVED pending a "
            "real historical surface."
        )
    )
    lines = [
        f"# GOAS Put-Write Delta Sweep — Findings ({STAMP})",
        "",
        "**Exploratory research.** Skew shape is MODELED (calibrated to one real GOAS "
        "quote), not observed — flat-vol is the conservative floor, skew the GOAS-faithful "
        "estimate; the truth is bracketed between them.",
        "",
        f"## Sweet spot (net-of-fee Sharpe @ {int(skewed['rank_fee'] * 10000)}bps, "
        "per-regime catastrophe gate applied)",
        f"- Flat-vol top: {ftop}",
        f"- Skew top:     {stop}",
        f"- Flat & skew AGREE on top (delta, dte): **{agree}**{flip}",
        "",
        "## GOAS validation",
        f"- Calibration anchor: {GOAS_AS_OF} SPY={asof_spot:.2f} VIX={asof_vix:.2f}; "
        f"target strike {GOAS_STRIKE_FRAC:.3f}·S, premium {GOAS_PREMIUM_FRAC:.3f}·S "
        "(~7.7% annualized in GOAS's table).",
        "- Net result at ~15Δ / 1-month vs GOAS's 3–6% net: see the fee column in "
        "goas-delta-dte-sweep CSV.",
        "",
        f"## SPY buy-and-hold (price-return): Sharpe {bench['sharpe']:.2f}, "
        f"maxDD {bench['max_drawdown']:.2%}, CAGR {bench['ann_return']:.2%}",
        "",
        "## Methodology: cash-secured (defined-risk); the collateral earns the risk-free "
        f"({R:.0%}, CBOE PUT-index convention), so reported total return ≈ rf + premium "
        "harvest — the harvest ABOVE cash is (total − rf). GOAS's 3–6% net is a "
        "premium-harvest figure on leveraged (20–40%) collateral, so it is NOT directly "
        "comparable to our unlevered total return.",
        "",
        "## Caveats: constant-slope modeled skew (understates crisis put richness → "
        "premiums are a conservative floor); the sweet spot sitting at the grid edge "
        "(max delta/tenor) suggests Sharpe under-penalizes the tail — read with the "
        "drawdown/CVaR columns, not Sharpe alone; European cash-settle vs GOAS's "
        "American roll-managed book; price-return SPY benchmark (no dividends); VIX "
        "constant-maturity 30d applied across tenors.",
        "",
        f"## Honest de-rating: the headline is the best of {len(skewed['cells'])} cells "
        "× 2 pricing modes — expect favorable-corner overfit; de-rate the in-sample "
        "Sharpe and prefer the delta that wins under BOTH pricing modes and all regimes.",
        "",
        "## Reproduce:",
        "```",
        "uv run python scripts/research/goas_putwrite_run.py",
        "```",
    ]
    (OUT / f"MASTER-goas-putwrite-{STAMP}.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spy = _daily_closes("equity", "SPY")
    vix = _daily_closes("volatility", "VIX")
    loaded = _build_loaded(spy, vix, rv_window=20, z_window=252)
    _, asof_vix = _asof(vix, GOAS_AS_OF)
    _, asof_spot = _asof(spy, GOAS_AS_OF)
    skew = calibrate_skew(
        asof_spot,
        asof_vix / 100.0,
        GOAS_DTE_DAYS / 252.0,
        R,
        target_strike_frac=GOAS_STRIKE_FRAC,
        target_premium_frac=GOAS_PREMIUM_FRAC,
    )

    flat = run_sweep(loaded, skew=None, r=R)
    skewed = run_sweep(loaded, skew=skew, r=R)

    # 1) full sweep CSV (both pricing modes, every fee level)
    with (OUT / f"goas-delta-dte-sweep-{STAMP}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "pricing",
                "delta",
                "dte",
                "fee",
                "ann_return",
                "ann_vol",
                "sharpe",
                "max_drawdown",
                "calmar",
                "cvar5",
                "worst_month",
                "win_rate",
                "breach_rate",
                "mean_credit",
                "n_trades",
            ]
        )
        for out in (flat, skewed):
            for c in out["cells"]:
                for fee, m in c["fees"].items():
                    w.writerow(
                        [
                            c["pricing"],
                            c["delta"],
                            c["dte"],
                            fee,
                            m["ann_return"],
                            m["ann_vol"],
                            m["sharpe"],
                            m["max_drawdown"],
                            m["calmar"],
                            m["cvar5"],
                            m["worst_month"],
                            c["costed"]["win_rate"],
                            c["costed"]["breach_rate"],
                            c["costed"]["mean_credit"],
                            c["n_trades"],
                        ]
                    )

    # 2) skew-vs-flat at the ranking fee (ranking-flip check)
    with (OUT / f"goas-skew-vs-flat-{STAMP}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "delta",
                "dte",
                "flat_sharpe",
                "skew_sharpe",
                "flat_ann_return",
                "skew_ann_return",
            ]
        )
        fmap = {(c["delta"], c["dte"]): c for c in flat["cells"]}
        smap = {(c["delta"], c["dte"]): c for c in skewed["cells"]}
        for key in sorted(fmap):
            fc, sc = fmap[key], smap[key]
            w.writerow(
                [
                    key[0],
                    key[1],
                    fc["rank"]["sharpe"],
                    sc["rank"]["sharpe"],
                    fc["rank"]["ann_return"],
                    sc["rank"]["ann_return"],
                ]
            )

    # 3) regime CSV for the top skew cell (+ all cells for context)
    top = skewed["ranking"][0] if skewed["ranking"] else None
    with (OUT / f"goas-regime-{STAMP}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "pricing",
                "delta",
                "dte",
                "regime",
                "sharpe",
                "ann_return",
                "max_drawdown",
                "worst_month",
                "n_days",
            ]
        )
        for out in (flat, skewed):
            for c in out["cells"]:
                if top and (c["delta"], c["dte"]) != (top["delta"], top["dte"]):
                    continue
                for label, m in c["regimes"].items():
                    w.writerow(
                        [
                            c["pricing"],
                            c["delta"],
                            c["dte"],
                            label,
                            m["sharpe"],
                            m["ann_return"],
                            m["max_drawdown"],
                            m["worst_month"],
                            m["n_days"],
                        ]
                    )

    # 4) trade log for the top skew cell
    if top:
        res = simulate_putwrite(
            loaded,
            GoasConfig(short_delta=top["delta"], dte_days=top["dte"], skew=skew, r=R),
        )
        with (OUT / f"goas-trade-log-{STAMP}.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "entry_date",
                    "expiry_date",
                    "strike",
                    "credit",
                    "iv_entry",
                    "contracts",
                    "intrinsic",
                    "net_pnl",
                    "return_on_risk",
                    "breached",
                ]
            )
            for t in res.trades:
                w.writerow(
                    [
                        t.entry_date,
                        t.expiry_date,
                        t.strike,
                        t.credit,
                        t.iv_entry,
                        t.contracts,
                        t.intrinsic,
                        t.net_pnl,
                        t.return_on_risk,
                        t.breached,
                    ]
                )

    # 5) findings note
    _write_master_note(flat, skewed, asof_spot, asof_vix)
    print(
        f"GOAS put-write sweep complete → {OUT}\n"
        f"  calibrated skew slope={skew.slope:.4f} (VIX={asof_vix:.2f}, SPY={asof_spot:.2f})\n"
        f"  flat top:  {flat['ranking'][0] if flat['ranking'] else None}\n"
        f"  skew top:  {skewed['ranking'][0] if skewed['ranking'] else None}\n"
        f"  SPY buy-hold Sharpe={skewed['benchmark']['sharpe']:.2f}"
    )


if __name__ == "__main__":
    main()
