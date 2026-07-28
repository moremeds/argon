#!/usr/bin/env python
"""Is the VCG calm gate anything more than a VIX filter?

`2026-07-29-vrp-vcg-calm-gate-walkforward.md` showed the calm gate survives
walk-forward on the VRP macro book. It did NOT show that the *credit* leg of
VCG is doing the work. VCG is built from VIX/VVIX versus credit, so on a calm
day VIX is low — and low VIX predicting low forward vol is the single most
well-known fact in the field. The gate's win may be an expensive restatement
of "VIX is low".

That is a confound, not a footnote: if a plain VIX filter reproduces the
result, you should trade the cheap version — fewer inputs, no HYG capture
dependency, no 63-session normalisation to maintain.

This script settles it by adding two arms to the same walk-forward harness:

    vix_low   vrp_z >= 0 AND trailing-252 VIX percentile < p   (the cheap rival)
    resid     vrp_z >= 0 AND |VCG residualised on VIX| < t     (VCG's own content)

`resid` regresses vcg_z on VIX **inside each training window only**, applies
those coefficients out-of-sample, and standardises by the training residual
std. What survives is the part of VCG that VIX cannot explain.

Reading the outcome:
  * resid survives, vix_low does not  -> credit divergence is real; VCG earns its keep
  * vix_low matches or beats calm     -> VCG is an expensive way to read VIX
  * neither survives                  -> the original calm win was the VIX level

The VIX percentile is strictly causal: rank within the trailing 252 sessions
*before* the entry date, never including it. Getting that wrong would hand the
cheap rival a look-ahead advantage and invert the conclusion.

Ladder/pricing logic is duplicated from `vrp_vcg_calm_gate_walkforward.py`
rather than imported — that file is a script, not a module, and the committed
result there must stay reproducible independent of edits here.

Reproduce (reads the mac mini, read-only; writes only the research doc):

    PGPASSWORD=… UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    UW_SCAN_DB_USER=argon_app UW_SCAN_ALLOW_DB_MISMATCH=1 UW_SCAN_API_KEY=x \\
    uv run python scripts/research/vrp_vcg_vs_vix_walkforward.py
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import date as _date

import numpy as np
import psycopg

from uw_scan.backtest.metrics import monthly_summary
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread
from uw_scan.storage.repository import Repository

CALM_THRESHOLDS: list[float | None] = [None, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
# "Keep the trade if VIX sits below this percentile of its trailing year."
VIX_PERCENTILES: list[float | None] = [None, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

GRID = [(0.20, 20), (0.25, 20), (0.25, 30), (0.30, 20)]
MIN_TRAIN_TRADES = 20
FIRST_TEST_YEAR = 2013
VIX_RANK_WINDOW = 252

ARMS = ("always", "gate0", "calm", "vix_low", "resid")


def load_vcg(host, db, user, password) -> dict[_date, float]:
    sql = """
        SELECT DISTINCT ON (data_date) data_date, vcg_score::float8
          FROM uw_scan.vcg_snapshots
         WHERE basis = 'eod' AND credit_proxy = 'HYG' AND vcg_score IS NOT NULL
         ORDER BY data_date, scanned_at DESC
    """
    with (
        psycopg.connect(
            host=host, dbname=db, user=user, password=password, connect_timeout=15
        ) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(sql)
        return {r[0]: r[1] for r in cur.fetchall()}


def load_vix(host, db, user, password) -> dict[_date, float]:
    sql = """
        SELECT trade_date, close::float8
          FROM uw_scan.vol_index_daily
         WHERE symbol = 'VIX' AND close IS NOT NULL
         ORDER BY trade_date
    """
    with (
        psycopg.connect(
            host=host, dbname=db, user=user, password=password, connect_timeout=15
        ) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(sql)
        return {r[0]: r[1] for r in cur.fetchall()}


def vix_ranks(vix: dict[_date, float]) -> dict[_date, float]:
    """Trailing-252 percentile rank of VIX, STRICTLY PRIOR to each date.

    The window excludes the date being ranked. Including it would leak the very
    observation the filter is deciding on — small, but it biases the cheap rival
    upward, which is exactly the arm this script is trying not to flatter.
    """
    days = sorted(vix)
    out: dict[_date, float] = {}
    for i, d in enumerate(days):
        if i < VIX_RANK_WINDOW:
            continue
        window = [vix[x] for x in days[i - VIX_RANK_WINDOW : i]]  # excludes i
        v = vix[d]
        out[d] = sum(1 for w in window if w < v) / len(window)
    return out


def fit_residuals(
    vcg: dict[_date, float], vix: dict[_date, float], train_hi: _date
) -> tuple[float, float, float] | None:
    """OLS vcg_z ~ a + b*VIX on the training window. Returns (a, b, resid_std).

    Fitted on train dates ONLY; the caller applies it to unseen dates. This is
    the whole point — a residual fitted on the full sample would smuggle the
    test years back into the "VIX cannot explain this" claim.
    """
    xs, ys = [], []
    for d, z in vcg.items():
        if d <= train_hi and d in vix:
            xs.append(vix[d])
            ys.append(z)
    if len(xs) < 100:
        return None
    x = np.asarray(xs)
    y = np.asarray(ys)
    b, a = np.polyfit(x, y, 1)
    resid = y - (a + b * x)
    sd = float(resid.std())
    if sd <= 0:
        return None
    return float(a), float(b), sd


def ladder(
    ctx,
    *,
    keep,
    short_delta: float,
    hold_days: int,
    lo: _date | None,
    hi: _date | None,
) -> tuple[dict[tuple[int, int], float], int]:
    """One-at-a-time bull-put-spread ladder. `keep(date) -> bool` is the filter.

    Identical pricing across arms, so any gap is the filter and not a
    re-implementation.
    """
    adj, iv_map, z_map, cost, r, universe = ctx
    mult = cost.multiplier
    by_month: dict[tuple[int, int], float] = defaultdict(float)
    n = 0
    last_exit = -1

    for pi in range(0, len(adj) - hold_days):
        if pi <= last_exit:
            continue
        d, S0 = adj[pi]
        if (lo and d < lo) or (hi and d > hi):
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or S0 <= 0:
            continue
        if d not in universe:
            continue
        if not keep(d):
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
        by_month[(dx.year, dx.month)] += net / (st.max_loss * mult)
        n += 1
        last_exit = pi + hold_days

    return by_month, n


def make_keep(ctx, vcg, vixr, arm, *, calm_thr=None, vix_thr=None, resid=None):
    """Build the per-arm entry filter. A missing input never passes."""
    z_map = ctx[2]

    def vrp_ok(d):
        v = z_map.get(d)
        return v is not None and v >= 0

    if arm == "always":
        return lambda d: True
    if arm == "gate0":
        return vrp_ok
    if arm == "calm":
        if calm_thr is None:
            return vrp_ok
        return lambda d: (
            vrp_ok(d) and (vcg.get(d) is not None and abs(vcg[d]) < calm_thr)
        )
    if arm == "vix_low":
        if vix_thr is None:
            return vrp_ok
        return lambda d: vrp_ok(d) and (vixr.get(d) is not None and vixr[d] < vix_thr)
    if arm == "resid":
        if calm_thr is None or resid is None:
            return vrp_ok
        a, b, sd, vix = resid

        def keep(d):
            if not vrp_ok(d):
                return False
            if d not in vcg or d not in vix:
                return False
            return abs((vcg[d] - (a + b * vix[d])) / sd) < calm_thr

        return keep
    raise ValueError(arm)


def pick(ctx, menu, build, *, short_delta, hold_days, train_hi):
    """Choose a threshold on the TRAINING window only, by train Sharpe."""
    best, best_s = None, float("-inf")
    for t in menu:
        bm, n = ladder(
            ctx,
            keep=build(t),
            short_delta=short_delta,
            hold_days=hold_days,
            lo=None,
            hi=train_hi,
        )
        if n < MIN_TRAIN_TRADES:
            continue
        s = monthly_summary(bm)["sharpe"]
        if s == s and s > best_s:
            best_s, best = s, t
    return best


def summarize(by_month, n) -> dict:
    s = monthly_summary(by_month)
    ar, dd = s["annror"], s["maxdd"]
    return dict(
        n=n,
        sharpe=s["sharpe"],
        annror=ar,
        maxdd=dd,
        calmar=(ar / abs(dd)) if dd < 0 else float("inf"),
    )


def table(rows) -> list[str]:
    """ROR/maxDD are in units of ONE max-loss, not percent."""
    out = [
        "| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, m in rows:
        out.append(
            f"| {label} | {m['n']:,} | {m['sharpe']:.2f} | {m['annror']:.2f} | "
            f"{m['maxdd']:.2f} | {m['calmar']:.2f} |"
        )
    return out


def run_config(ctx, vcg, vix, vixr, short_delta, hold_days, years):
    acc = {arm: (defaultdict(float), 0) for arm in ARMS}
    folds = []

    for y in years:
        train_hi = _date(y - 1, 12, 31)
        lo, hi = _date(y, 1, 1), _date(y, 12, 31)

        calm_t = pick(
            ctx,
            CALM_THRESHOLDS,
            lambda t: make_keep(ctx, vcg, vixr, "calm", calm_thr=t),
            short_delta=short_delta,
            hold_days=hold_days,
            train_hi=train_hi,
        )
        vix_t = pick(
            ctx,
            VIX_PERCENTILES,
            lambda t: make_keep(ctx, vcg, vixr, "vix_low", vix_thr=t),
            short_delta=short_delta,
            hold_days=hold_days,
            train_hi=train_hi,
        )
        fit = fit_residuals(vcg, vix, train_hi)
        rspec = (*fit, vix) if fit else None
        resid_t = (
            pick(
                ctx,
                CALM_THRESHOLDS,
                lambda t: make_keep(ctx, vcg, vixr, "resid", calm_thr=t, resid=rspec),
                short_delta=short_delta,
                hold_days=hold_days,
                train_hi=train_hi,
            )
            if rspec
            else None
        )

        builders = {
            "always": make_keep(ctx, vcg, vixr, "always"),
            "gate0": make_keep(ctx, vcg, vixr, "gate0"),
            "calm": make_keep(ctx, vcg, vixr, "calm", calm_thr=calm_t),
            "vix_low": make_keep(ctx, vcg, vixr, "vix_low", vix_thr=vix_t),
            "resid": make_keep(ctx, vcg, vixr, "resid", calm_thr=resid_t, resid=rspec),
        }
        folds.append(
            {
                "year": y,
                "calm": calm_t,
                "vix": vix_t,
                "resid": resid_t,
                "b": fit[1] if fit else None,
            }
        )
        for arm, keep in builders.items():
            bm, n = ladder(
                ctx,
                keep=keep,
                short_delta=short_delta,
                hold_days=hold_days,
                lo=lo,
                hi=hi,
            )
            dbm, dn = acc[arm]
            for k, v in bm.items():
                dbm[k] += v
            acc[arm] = (dbm, dn + n)

    return {arm: summarize(*acc[arm]) for arm in ARMS}, folds


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--index", default="SPX")
    p.add_argument(
        "--out", default="docs/research/2026-07-29-vcg-vs-vix-walkforward.md"
    )
    a = p.parse_args()

    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    loaded = load_index_vol(repo, a.index)
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    pw = os.environ.get("PGPASSWORD", settings.db_password)
    vcg = load_vcg(settings.db_host, settings.db_name, settings.db_user, pw)
    vix = load_vix(settings.db_host, settings.db_name, settings.db_user, pw)
    vixr = vix_ranks(vix)

    # Same universe for every arm: a day needs a VRP quote, a VCG score, and a
    # VIX rank. Letting arms see different day sets would make the comparison
    # meaningless.
    universe = {d for d in vcg if d in vixr}
    ctx = (
        loaded.adj,
        {row["market_date"]: row["iv"] for row in loaded.rows},
        {row["market_date"]: row["vrp_z_20"] for row in loaded.rows},
        cost,
        settings.vrp_risk_free_rate,
        universe,
    )

    dates = [d for d, _ in loaded.adj if d in universe]
    years = list(range(FIRST_TEST_YEAR, max(dates).year + 1))

    # Plain correlation, for context on how much of VCG is VIX at all.
    common = sorted(set(vcg) & set(vix))
    corr = float(np.corrcoef([vcg[d] for d in common], [vix[d] for d in common])[0, 1])

    L: list[str] = []
    w = L.append
    w("# Is the VCG calm gate anything more than a VIX filter?")
    w("")
    w(
        f"**Index**: {a.index}. **Universe**: {len(dates):,} sessions with a VRP "
        f"quote, a VCG score and a trailing-252 VIX rank, {min(dates)} → "
        f"{max(dates)}. **OOS span**: {years[0]}–{years[-1]} ({len(years)} folds)."
    )
    w("")
    w(
        "The walk-forward result "
        "(`2026-07-29-vrp-vcg-calm-gate-walkforward.md`) showed the calm gate "
        "survives OOS. It did **not** show the credit leg was doing the work. "
        "VCG is built from VIX/VVIX versus credit, so a calm VCG day is a low-VIX "
        "day, and low VIX predicting low forward vol is the best-known fact in "
        "the field. This script asks whether anything survives once VIX is "
        "given its own arm."
    )
    w("")
    w(
        f"Raw correlation of `vcg_z` with the VIX level over {len(common):,} shared "
        f"sessions: **{corr:+.3f}**."
    )
    w("")
    w("| arm | rule |")
    w("|---|---|")
    w("| `always` | no gate |")
    w("| `gate0` | `vrp_z >= 0` |")
    w("| `calm` | `gate0` AND `abs(vcg_z) < t` — t re-fit per fold |")
    w(
        "| `vix_low` | `gate0` AND trailing-252 VIX percentile `< p` — p re-fit per fold |"
    )
    w(
        "| `resid` | `gate0` AND `abs(vcg_z residualised on VIX) < t` — OLS fit on train only |"
    )
    w("")
    w(
        "The VIX percentile is ranked within the 252 sessions **strictly before** "
        "the entry date. `resid` fits `vcg_z ~ a + b*VIX` on the training window "
        "only and applies those coefficients out-of-sample, so it measures the "
        "part of VCG that VIX cannot explain."
    )
    w("")

    verdict_at = len(L)
    cells, all_folds = [], {}

    for sd, hd in GRID:
        w(f"## {a.index} · {sd:.2f}Δ short · {hd}-day hold")
        w("")
        res, folds = run_config(ctx, vcg, vix, vixr, sd, hd, years)
        cells.append(res)
        all_folds[(sd, hd)] = folds
        L.extend(table([(arm, res[arm]) for arm in ARMS]))
        w("")

    w("## What each training window chose (0.25Δ/20d)")
    w("")
    anchor = all_folds[(0.25, 20)]
    w("| test year | calm |z| | VIX pct | resid |z| | OLS slope b |")
    w("|---|---|---|---|---:|")
    for f in anchor:
        fmt = lambda v: "none" if v is None else f"{v}"  # noqa: E731
        w(
            f"| {f['year']} | {fmt(f['calm'])} | {fmt(f['vix'])} | "
            f"{fmt(f['resid'])} | {f['b']:+.3f} |"
        )
    w("")

    # ── Verdict, computed ────────────────────────────────────────────────────
    n = len(cells)
    calm_v_gate0 = sum(1 for c in cells if c["calm"]["sharpe"] > c["gate0"]["sharpe"])
    vix_v_gate0 = sum(1 for c in cells if c["vix_low"]["sharpe"] > c["gate0"]["sharpe"])
    resid_v_gate0 = sum(1 for c in cells if c["resid"]["sharpe"] > c["gate0"]["sharpe"])
    calm_v_vix = sum(1 for c in cells if c["calm"]["sharpe"] > c["vix_low"]["sharpe"])
    resid_v_vix = sum(1 for c in cells if c["resid"]["sharpe"] > c["vix_low"]["sharpe"])
    calm_m = ", ".join(f"{c['calm']['sharpe']:.2f}" for c in cells)
    vix_m = ", ".join(f"{c['vix_low']['sharpe']:.2f}" for c in cells)
    res_m = ", ".join(f"{c['resid']['sharpe']:.2f}" for c in cells)
    g_m = ", ".join(f"{c['gate0']['sharpe']:.2f}" for c in cells)

    if resid_v_gate0 >= n - 1 and calm_v_vix >= n - 1:
        head = "## Verdict — VCG carries content VIX does not"
    elif vix_v_gate0 >= n - 1 and calm_v_vix <= 1:
        head = "## Verdict — the cheap VIX filter reproduces it; VCG is not earning its keep"
    else:
        head = "## Verdict — mixed; neither arm cleanly dominates"

    v = [
        head,
        "",
        f"Sharpe by arm across the {n} grid cells:",
        "",
        f"- `gate0`: {g_m}",
        f"- `calm`: {calm_m}",
        f"- `vix_low`: {vix_m}",
        f"- `resid`: {res_m}",
        "",
        f"**1. Does the cheap rival work?** `vix_low` beats `gate0` in "
        f"**{vix_v_gate0}/{n}** cells. If this matches `calm`'s "
        f"**{calm_v_gate0}/{n}**, the calm gate was reading the VIX level.",
        "",
        f"**2. Head to head.** `calm` beats `vix_low` in **{calm_v_vix}/{n}** cells. "
        "This is the question — a tie means prefer VIX: fewer inputs, no HYG "
        "capture dependency, no 63-session normalisation to maintain.",
        "",
        f"**3. What survives orthogonalisation?** `resid` — VCG with VIX regressed "
        f"out — beats `gate0` in **{resid_v_gate0}/{n}** cells and `vix_low` in "
        f"**{resid_v_vix}/{n}**. This is the strictest test of whether the credit "
        "leg carries independent information.",
        "",
        f"**4. How much of VCG is VIX?** Raw correlation **{corr:+.3f}**. The "
        "per-fold OLS slopes in the table above show how stable that relationship "
        "is across training windows.",
        "",
        "### Limits",
        "",
        "Flat-vol pricing with no skew. One-at-a-time ladder. SPX only. The VIX "
        "arm gets a trailing-252 percentile, which is one reasonable "
        "specification among several — a different lookback or an absolute VIX "
        "level might do better or worse, so 'VIX does not work here' is weaker "
        "than 'VIX cannot work'. The residual is linear in the VIX level only; a "
        "non-linear or VVIX-inclusive control could absorb more.",
        "",
    ]
    L[verdict_at:verdict_at] = v

    text = "\n".join(L) + "\n"
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"[written] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
