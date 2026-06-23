"""Reproduces the parameter-sweep numbers in docs/research/vrp/_iterations/macro-short-vol-verdict.md
(sections "Experiment results", "Does it extend to QQQ/IWM", "Deployable entry/exit
signal"). Research scaffolding — not wired into the worker/API.

Run (MacBook local, reads option_wizard_local):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=chenxi UW_SCAN_API_KEY=x \
  uv run python scripts/_vrp_macro_param_sweep.py

All P&L is in monthly-ROR Sharpe units (one-at-a-time always-on SPX 0.25Δ/20-DTE ≈ 0.92,
the anchor against the committed reports/vrp_macro_drawdown.py). The bull put spread is
priced flat-vol (VIX/100 = IV) and settled model-free at the realized close; the long
wing is the stop. vrp_z = trailing-252 z-score of (IV − RV20). Sizing rules:
  always : 1                              gate0 : 1 if z>=0 else 0
  ramp   : 1 at z>=0, linear→0 at z=-0.5  ramp+ : 0 at z<=0, linear→1 at z>=0.5
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as _date
from math import sqrt
from statistics import fmean, pstdev

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread
from uw_scan.storage.repository import Repository

SHORT_DELTAS = (0.10, 0.16, 0.20, 0.25, 0.30, 0.35)
HOLD_DAYS = (7, 14, 20, 30, 45)


def make_sizer(name: str):
    if name == "always":
        return lambda z: 1.0
    if name == "gate0":
        return lambda z: 1.0 if (z is not None and z >= 0) else 0.0
    if name == "ramp":
        return lambda z: (
            0.0 if z is None else (1.0 if z >= 0 else max(0.0, (z + 0.5) / 0.5))
        )
    if name == "ramp+":
        return lambda z: 0.0 if z is None else min(1.0, max(0.0, z / 0.5))
    raise ValueError(name)


def _sharpe_maxdd(monthly: dict) -> tuple[float, float, float]:
    """Zero-fill the contiguous month span; return (annualized Sharpe, maxDD on the
    cumulative curve, annualized mean return)."""
    if not monthly:
        return float("nan"), 0.0, 0.0
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    series, y, m = [], y0, m0
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


def build_ctx(repo, settings, name: str):
    loaded = load_index_vol(repo, name)
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    return (
        loaded.adj,
        {row["market_date"]: row["iv"] for row in loaded.rows},
        {row["market_date"]: row["vrp_z_20"] for row in loaded.rows},
        cost,
        settings.vrp_risk_free_rate,
    )


def run_cfg(
    ctx, *, short_delta, hold_days, cadence, sizing, min_date=None, one_at_a_time=False
):
    adj, iv_map, z_map, cost, r = ctx
    mult = cost.multiplier
    n = len(adj)
    sizer = make_sizer(sizing)
    max_slots = 1 if one_at_a_time else max(1, round(hold_days / cadence))
    step = 1 if one_at_a_time else cadence
    by_month: dict = defaultdict(float)
    nrung = 0
    last_exit = -1
    for pi in range(0, n - hold_days, step):
        if one_at_a_time and pi <= last_exit:
            continue
        d, S0 = adj[pi]
        if min_date and d < min_date:
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or S0 <= 0:
            continue
        w = sizer(z_map.get(d))
        if w <= 0:
            continue
        try:
            st = build_bull_put_spread(
                S0,
                float(iv),
                hold_days / 252.0,
                r,
                short_delta=short_delta,
                wing_delta=short_delta * 0.5,
            )
        except ValueError:
            continue
        dx, S_T = adj[pi + hold_days]
        net = (st.credit - st.value(S_T, 0.0, r, 0.0)) * mult - cost.total(
            st.leg_premiums, 1
        )
        by_month[(dx.year, dx.month)] += w * net / (st.max_loss * mult)
        nrung += 1
        last_exit = pi + hold_days
    monthly = {k: v / max_slots for k, v in by_month.items()}
    sh, dd, ar = _sharpe_maxdd(monthly)
    return dict(
        n=nrung,
        sharpe=sh,
        maxdd=dd,
        annror=ar,
        calmar=(ar / abs(dd)) if dd < 0 else float("inf"),
        monthly=monthly,
    )


def main() -> None:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    spx = build_ctx(repo, settings, "SPX")
    print(
        f"DB={settings.db_name}  (monthly-ROR Sharpe; anchor: one-at-a-time SPX 0.25/20 always-on)\n"
    )

    # 1) delta x DTE sweep (one-at-a-time, always-on) — the sweet horizon
    print("=== delta x DTE (one-at-a-time, always-on) ===")
    print(f"{'Δ':>5} {'DTE':>4} {'n':>4} {'SHARPE':>7} {'maxDD':>7} {'meanann':>8}")
    for sd in SHORT_DELTAS:
        for hd in HOLD_DAYS:
            o = run_cfg(
                spx,
                short_delta=sd,
                hold_days=hd,
                cadence=5,
                sizing="always",
                one_at_a_time=True,
            )
            print(
                f"{sd:>5.2f} {hd:>4} {o['n']:>4} {o['sharpe']:>7.2f} {o['maxdd']:>7.2f} {o['annror']:>+8.3f}"
            )

    # 2) synthesis grid (weekly ladder x vrp-z sizing) — the lever
    print("\n=== synthesis: weekly ladder x vrp-z sizing (SPX, full history) ===")
    print(
        f"{'Δ':>5} {'DTE':>4} {'sizing':>7} {'n':>5} {'SHARPE':>7} {'maxDD':>7} {'Calmar':>7}"
    )
    grid = []
    for sd in (0.25, 0.30, 0.35):
        for hd in (20, 30):
            for sizing in ("always", "gate0", "ramp", "ramp+"):
                o = run_cfg(spx, short_delta=sd, hold_days=hd, cadence=5, sizing=sizing)
                grid.append((sd, hd, sizing, o))
                print(
                    f"{sd:>5.2f} {hd:>4} {sizing:>7} {o['n']:>5} {o['sharpe']:>7.2f} {o['maxdd']:>7.2f} {o['calmar']:>7.2f}"
                )
    grid.sort(
        key=lambda x: x[3]["sharpe"] if x[3]["sharpe"] == x[3]["sharpe"] else -9,
        reverse=True,
    )
    bsd, bhd, bsizing, _ = grid[0]
    print(f"\nwinner: Δ{bsd:.2f} DTE{bhd} {bsizing}")

    # 3) extend the winner to QQQ/IWM (OOS) over a common window + portfolios
    print("\n=== winner extended to QQQ/IWM (common 2011+) ===")
    common = _date(2011, 1, 1)
    print(f"{'name':>5} {'SHARPE':>7} {'maxDD':>7} {'Calmar':>7}   (vs always 0.25/20)")
    series = {}
    for name in ("SPX", "QQQ", "IWM"):
        ctx = spx if name == "SPX" else build_ctx(repo, settings, name)
        won = run_cfg(
            ctx,
            short_delta=bsd,
            hold_days=bhd,
            cadence=5,
            sizing=bsizing,
            min_date=common,
        )
        base = run_cfg(
            ctx,
            short_delta=0.25,
            hold_days=20,
            cadence=5,
            sizing="always",
            min_date=common,
        )
        series[name] = won["monthly"]
        print(
            f"{name:>5} {won['sharpe']:>7.2f} {won['maxdd']:>7.2f} {won['calmar']:>7.2f}   (Sharpe {base['sharpe']:.2f})"
        )
    for names in (("SPX", "QQQ"), ("SPX", "QQQ", "IWM")):
        keys = set().union(*(series[nm] for nm in names))
        port = {
            k: sum(series[nm].get(k, 0.0) for nm in names) / len(names) for k in keys
        }
        sh, dd, ar = _sharpe_maxdd(port)
        print(
            f"  portfolio {'+'.join(names):12s}: Sharpe {sh:.2f}  maxDD {dd:+.2f}  Calmar {(ar / abs(dd)) if dd < 0 else 0:.2f}"
        )
    conn.close()


if __name__ == "__main__":
    main()
