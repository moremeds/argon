"""Falsification: does implied-correlation richness improve the SPX short-vol edge?

Issue #226. Hypothesis: index IV richness = vol premium + CORRELATION premium. The
validated VRP-macro edge (SPX bull-put-spread, Sharpe ~1.65) sizes only on vrp-z
(IV-RV level). Implied-correlation richness is proposed as a second, near-orthogonal
axis. This script tests whether short-vol P&L is MONOTONE across implied-correlation
z-score buckets. Non-monotone -> the gate is dead -> negative result.

Primary correlation measure: CBOE COR1M (S&P 500 1-month implied correlation index,
`vol_index_daily` symbol 'COR1M', real data 2006-2026) -- the actual market-observed
implied correlation, strictly better than the noisy top-10 proxy in the issue text.
The issue's equal-weight top-10 dispersion proxy is computed on the 286-day vrp_daily
overlap ONLY as a cross-check that COR1M ~ the proxy (validates we measure the same thing).

Short-vol P&L reuses the VALIDATED machinery: build_bull_put_spread (flat-vol, VIX/100=IV),
settled model-free at the realized SPX close, per-trade net normalized by max_loss, costs
from Settings. hold=20 trading days (VIX is constant-maturity 30d => 20d is the cleanest read).

Reproduce (MacBook local, reads option_wizard_local):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x \
  uv run python scripts/research/implied_corr_gate.py

Writes full trace to docs/research/2026-07-07-implied-corr-gate-results.{json,csv}.
Read-only on the DB. No fabrication: every number derives from vol_index_daily / vrp_daily.
"""

from __future__ import annotations

import json
import math
import pathlib
from collections import defaultdict
from datetime import date as _date

import numpy as np
import psycopg

from uw_scan.backtest.metrics import monthly_summary
from uw_scan.config import Settings
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread

HOLD = 20  # trading days
SHORT_DELTA = 0.25
WING_DELTA = 0.125
ROLL = 252  # trailing z-score window
TOP10 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "LLY"]

OUT = pathlib.Path("docs/research")


def _load(cur, symbol: str) -> dict[_date, float]:
    cur.execute(
        "SELECT trade_date, close::float8 FROM uw_scan.vol_index_daily "
        "WHERE symbol=%s ORDER BY trade_date",
        (symbol,),
    )
    return {d: c for d, c in cur.fetchall()}


def _zscore_trailing(vals: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(vals)):
        if i < window:
            out.append(None)
            continue
        w = vals[i - window : i]  # strictly trailing, no look-ahead
        m = float(np.mean(w))
        sd = float(np.std(w, ddof=0))
        out.append((vals[i] - m) / sd if sd > 0 else None)
    return out


def _pearson(a, b) -> tuple[float, int]:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if len(a) < 3:
        return float("nan"), len(a)
    return float(np.corrcoef(a, b)[0, 1]), int(len(a))


def _ols_t(y, X_cols: dict[str, list]) -> dict:
    """OLS y ~ 1 + cols. Returns coef + t-stat per column (HAC-naive OLS t)."""
    names = list(X_cols)
    y = np.asarray(y, float)
    X = np.column_stack(
        [np.ones(len(y))] + [np.asarray(X_cols[n], float) for n in names]
    )
    mask = np.all(np.isfinite(X), axis=1) & np.isfinite(y)
    X, y = X[mask], y[mask]
    n, k = X.shape
    if n <= k:
        return {"n": int(n), "note": "insufficient"}
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - k
    sigma2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(sigma2 * xtx_inv))
    r2 = 1.0 - (resid @ resid) / (((y - y.mean()) ** 2).sum() + 1e-12)
    out = {"n": int(n), "r2": round(r2, 4), "intercept": round(float(beta[0]), 5)}
    for i, nm in enumerate(names, start=1):
        out[nm] = {
            "coef": round(float(beta[i]), 6),
            "t": round(float(beta[i] / se[i]), 3),
        }
    return out


def main() -> None:
    s = Settings.from_env()
    conn = psycopg.connect(
        host=s.db_host, dbname=s.db_name, user=s.db_user, password=s.db_password
    )
    cur = conn.cursor()
    spx = _load(cur, "SPX")
    vix = _load(cur, "VIX")
    cor = _load(cur, "COR1M")

    dates = sorted(set(spx) & set(vix) & set(cor))
    S = [spx[d] for d in dates]
    V = [vix[d] / 100.0 for d in dates]  # VIX -> decimal IV
    C = [cor[d] for d in dates]

    # trailing 20d realized vol from SPX log returns, annualized
    logret = [0.0] + [math.log(S[i] / S[i - 1]) for i in range(1, len(S))]
    rv20: list[float | None] = []
    for i in range(len(S)):
        if i < 20:
            rv20.append(None)
            continue
        w = logret[i - 19 : i + 1]
        rv20.append(float(np.std(w, ddof=0)) * math.sqrt(252))
    vrp = [(V[i] - rv20[i]) if rv20[i] is not None else None for i in range(len(S))]

    cor_z = _zscore_trailing(C, ROLL)
    vix_z = _zscore_trailing(V, ROLL)
    vrp_clean = [x if x is not None else float("nan") for x in vrp]
    vrp_z = _zscore_trailing(vrp_clean, ROLL)

    r = s.vrp_risk_free_rate
    cost = CostModel(
        s.vrp_cost_per_contract,
        s.vrp_slippage_frac,
        s.vrp_slippage_min,
        round_trip=s.vrp_cost_round_trip,
    )
    mult = cost.multiplier

    def trade_net(i: int) -> float | None:
        """Per-trade net return normalized by max_loss, entry at index i, expiry i+HOLD."""
        S0, iv = S[i], V[i]
        if S0 <= 0 or iv <= 0 or i + HOLD >= len(S):
            return None
        try:
            st = build_bull_put_spread(
                S0, iv, HOLD / 252.0, r, short_delta=SHORT_DELTA, wing_delta=WING_DELTA
            )
        except ValueError:
            return None
        S_T = S[i + HOLD]
        gross = st.expiry_pnl(S_T) * mult
        net = gross - cost.total(st.leg_premiums, 1)
        return net / (st.max_loss * mult)

    # ---- build per-trade records (weekly cadence for resolution) ----
    recs = []
    for i in range(ROLL, len(S) - HOLD):
        if cor_z[i] is None:
            continue
        net = trade_net(i)
        if net is None:
            continue
        recs.append(
            {
                "date": dates[i],
                "net": net,
                "cor_z": cor_z[i],
                "vix_z": vix_z[i],
                "vrp_z": vrp_z[i],
                "cor": C[i],
                "vix": V[i] * 100,
                "vrp": vrp[i],
            }
        )

    # non-overlapping subset (step=HOLD) for honest significance
    nonoverlap = []
    last = -HOLD
    for rr in recs:
        i = dates.index(rr["date"])
        if i - last >= HOLD:
            nonoverlap.append(rr)
            last = i

    def bucket_stats(records, key, n_buckets=5):
        vals = [x[key] for x in records if x[key] is not None]
        recs2 = [x for x in records if x[key] is not None]
        qs = np.quantile(vals, np.linspace(0, 1, n_buckets + 1))
        out = []
        for b in range(n_buckets):
            lo, hi = qs[b], qs[b + 1]
            if b == n_buckets - 1:
                sub = [x for x in recs2 if lo <= x[key] <= hi]
            else:
                sub = [x for x in recs2 if lo <= x[key] < hi]
            nets = [x["net"] for x in sub]
            if not nets:
                out.append({"bucket": b, "n": 0})
                continue
            m = float(np.mean(nets))
            sd = float(np.std(nets, ddof=1)) if len(nets) > 1 else float("nan")
            t = (
                m / (sd / math.sqrt(len(nets)))
                if sd and len(nets) > 1
                else float("nan")
            )
            out.append(
                {
                    "bucket": b,
                    "z_lo": round(float(lo), 3),
                    "z_hi": round(float(hi), 3),
                    "n": len(nets),
                    "mean_net": round(m, 5),
                    "std": round(sd, 5),
                    "t": round(t, 3),
                }
            )
        return out

    from scipy import stats as sps

    def monotonicity(records, key):
        b = bucket_stats(records, key)
        means = [x["mean_net"] for x in b if x.get("n", 0) > 0]
        idx = list(range(len(means)))
        rho, p = sps.spearmanr(idx, means)
        # OLS slope of net on z (trade level)
        zs = [x[key] for x in records if x[key] is not None]
        nets = [x["net"] for x in records if x[key] is not None]
        sl = _ols_t(nets, {key: zs})
        return {
            "buckets": b,
            "spearman_rho": round(float(rho), 3),
            "spearman_p": round(float(p), 3),
            "trade_ols": sl,
        }

    result = {
        "meta": {
            "hypothesis": "implied-corr richness (COR1M) improves SPX short-vol edge",
            "measure": "CBOE COR1M implied correlation index (vol_index_daily)",
            "pnl": f"bull put spread short_delta={SHORT_DELTA} wing={WING_DELTA} hold={HOLD}d flat-vol VIX/100",
            "window": [str(dates[ROLL]), str(dates[-HOLD - 1])],
            "n_trades_weekly": len(recs),
            "n_trades_nonoverlap": len(nonoverlap),
            "cost_model": [
                s.vrp_cost_per_contract,
                s.vrp_slippage_frac,
                s.vrp_slippage_min,
            ],
        }
    }

    # ---- 1. monotonicity of short-vol P&L across COR-z buckets ----
    result["cor_z_monotonicity_weekly"] = monotonicity(recs, "cor_z")
    result["cor_z_monotonicity_nonoverlap"] = monotonicity(nonoverlap, "cor_z")

    # ---- 2. confound: is COR-z just a VIX/vrp proxy? ----
    cz = [x["cor_z"] for x in recs]
    vz = [x["vix_z"] for x in recs]
    pz = [x["vrp_z"] for x in recs]
    rc_vix, _ = _pearson(cz, vz)
    rc_vrp, _ = _pearson(cz, pz)
    result["confound_correlations"] = {
        "pearson_cor_z_vix_z": round(rc_vix, 3),
        "pearson_cor_z_vrp_z": round(rc_vrp, 3),
    }
    # multivariate: does COR-z survive controlling for vrp-z and vix-z?
    nets = [x["net"] for x in recs]
    result["multivariate_ols_weekly"] = _ols_t(
        nets, {"cor_z": cz, "vrp_z": pz, "vix_z": vz}
    )
    nets_no = [x["net"] for x in nonoverlap]
    result["multivariate_ols_nonoverlap"] = _ols_t(
        nets_no,
        {
            "cor_z": [x["cor_z"] for x in nonoverlap],
            "vrp_z": [x["vrp_z"] for x in nonoverlap],
            "vix_z": [x["vix_z"] for x in nonoverlap],
        },
    )

    # ---- 3. double sort: within vrp-z terciles, does COR-z still sort? ----
    pzv = [x["vrp_z"] for x in recs if x["vrp_z"] is not None]
    tqs = np.quantile(pzv, [0, 1 / 3, 2 / 3, 1.0])
    dbl = {}
    for ti in range(3):
        lo, hi = tqs[ti], tqs[ti + 1]
        sub = [
            x
            for x in recs
            if x["vrp_z"] is not None
            and (lo <= x["vrp_z"] <= hi if ti == 2 else lo <= x["vrp_z"] < hi)
        ]
        # split sub by COR-z median
        czs = [x["cor_z"] for x in sub]
        med = float(np.median(czs))
        hi_c = [x["net"] for x in sub if x["cor_z"] >= med]
        lo_c = [x["net"] for x in sub if x["cor_z"] < med]
        dbl[f"vrp_tercile_{ti}"] = {
            "vrp_z_range": [round(float(lo), 2), round(float(hi), 2)],
            "n": len(sub),
            "high_cor_mean_net": round(float(np.mean(hi_c)), 5) if hi_c else None,
            "low_cor_mean_net": round(float(np.mean(lo_c)), 5) if lo_c else None,
            "high_minus_low": round(float(np.mean(hi_c) - np.mean(lo_c)), 5)
            if hi_c and lo_c
            else None,
        }
    result["double_sort_vrpz_x_corz"] = dbl

    # ---- 4. per-year mean net by COR-z sign (regime dependence) ----
    by_year = defaultdict(lambda: {"hi": [], "lo": []})
    for x in recs:
        y = x["date"].year
        (by_year[y]["hi"] if x["cor_z"] >= 0 else by_year[y]["lo"])[
            "_"
        ] if False else None
        (by_year[y]["hi"] if x["cor_z"] >= 0 else by_year[y]["lo"]).append(x["net"])
    yearly = {}
    for y in sorted(by_year):
        hi, lo = by_year[y]["hi"], by_year[y]["lo"]
        yearly[str(y)] = {
            "n_hi_cor": len(hi),
            "mean_hi": round(float(np.mean(hi)), 4) if hi else None,
            "n_lo_cor": len(lo),
            "mean_lo": round(float(np.mean(lo)), 4) if lo else None,
        }
    result["yearly_by_cor_sign"] = yearly

    # ---- 5. Sharpe: always-on vs COR-gate vs COR-ramp (monthly ROR) ----
    def sizer_series(sizer):
        by_month = defaultdict(float)
        last = -HOLD
        cnt = 0
        for i in range(ROLL, len(S) - HOLD):
            if cor_z[i] is None or i - last < HOLD:
                continue
            w = sizer(cor_z[i])
            if w <= 0:
                last = i
                continue
            net = trade_net(i)
            if net is None:
                continue
            dx = dates[i + HOLD]
            by_month[(dx.year, dx.month)] += w * net
            cnt += 1
            last = i
        return monthly_summary(dict(by_month)), cnt

    sizers = {
        "always": lambda z: 1.0,
        "cor_gate0": lambda z: 1.0 if z >= 0 else 0.0,
        "cor_ramp+": lambda z: min(1.0, max(0.0, z / 0.5)),
        "cor_inverse_gate": lambda z: 1.0 if z < 0 else 0.0,  # test opposite sign
    }
    sh = {}
    for nm, fn in sizers.items():
        summ, cnt = sizer_series(fn)
        sh[nm] = {
            "sharpe": round(summ["sharpe"], 3),
            "maxdd": round(summ["maxdd"], 4),
            "annror": round(summ["annror"], 4),
            "n_trades": cnt,
        }
    result["sharpe_by_cor_sizer_nonoverlap"] = sh

    # ---- 6. top-10 equal-weight dispersion proxy vs COR1M (issue's method) ----
    cur.execute(
        "SELECT ticker, market_date, iv::float8 FROM uw_scan.vrp_daily "
        "WHERE ticker = ANY(%s) OR ticker='SPY' ORDER BY market_date",
        (TOP10,),
    )
    comp = defaultdict(dict)  # date -> {ticker: iv}
    for tk, md, iv in cur.fetchall():
        if iv and iv > 0:
            comp[md][tk] = iv
    proxy_rows = []
    for md, ivs in sorted(comp.items()):
        members = [t for t in TOP10 if t in ivs]
        if len(members) < 6 or "SPY" not in ivs:
            continue
        sig = np.array([ivs[t] for t in members])
        N = len(members)
        w = 1.0 / N
        sigI = ivs["SPY"]
        num = sigI**2 - (w**2) * float(np.sum(sig**2))
        cross = (w**2) * (float(np.sum(sig)) ** 2 - float(np.sum(sig**2)))
        if cross <= 0:
            continue
        rho = num / cross
        proxy_rows.append((md, rho, ivs["SPY"]))
    # align proxy with COR1M on same dates
    prox_dates = [p[0] for p in proxy_rows]
    prox_rho = [p[1] for p in proxy_rows]
    cor_on = [cor.get(d) for d in prox_dates]
    pr_corr, pr_n = _pearson(
        prox_rho, [c if c is not None else float("nan") for c in cor_on]
    )
    result["top10_dispersion_proxy_crosscheck"] = {
        "n_days": len(proxy_rows),
        "window": [str(prox_dates[0]), str(prox_dates[-1])] if proxy_rows else None,
        "proxy_mean_rho": round(float(np.mean(prox_rho)), 4) if prox_rho else None,
        "pearson_proxy_vs_COR1M": round(pr_corr, 3),
        "pearson_n": pr_n,
        "note": "equal-weight top-10, sigma_I=SPY IV; validates COR1M ~ issue proxy",
    }

    # ---- write trace ----
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "2026-07-07-implied-corr-gate-results.json").write_text(
        json.dumps(result, indent=2, default=str)
    )
    # CSV of per-trade records (weekly)
    import csv

    with (OUT / "2026-07-07-implied-corr-gate-trades.csv").open("w", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(["date", "net", "cor_z", "vix_z", "vrp_z", "cor", "vix", "vrp"])
        for x in recs:
            wtr.writerow(
                [
                    x["date"],
                    round(x["net"], 6),
                    x["cor_z"],
                    x["vix_z"],
                    x["vrp_z"],
                    round(x["cor"], 3),
                    round(x["vix"], 3),
                    round(x["vrp"], 5) if x["vrp"] is not None else "",
                ]
            )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
