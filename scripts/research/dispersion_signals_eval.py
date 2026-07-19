"""Evaluate two dispersion/correlation trading claims (directional, not vol-harvesting).

Context: a user proposed two market-tide signals.
  Claim 1: "VIX/COR1M very high -> deleverage high-beta stocks (they underperform)."
  Claim 2: "VIXEQ/VIX high (index vol low, single-stock vol high = low correlation)
            is a WARNING signal -> forward index weakness / vol spike."

Identity used: COR1M ~= (VIX/VIXEQ)^2  =>  VIXEQ/VIX ~= 1/sqrt(COR1M).
So "VIXEQ/VIX high" <=> "COR1M low". We test Claim 2 via COR1M (20yr real history)
instead of the unsourceable, <2yr-old VIXEQ index.

Prior art: docs/research/2026-07-07-implied-corr-gate.md (#226) already found COR1M
carries NO independent SPX short-vol edge and is ~80% collinear with VIX. That tested
vol-HARVESTING P&L; the claims here are equity-DIRECTIONAL, so we test them directly.

Data: uw_scan.vol_index_daily (VIX, COR1M, SPX; 2006->2026-05) + apex adjusted daily
bars for SPHB/SPLV (high-beta / low-vol factor ETFs; ~2021-06->present, the binding
constraint for Claim 1). Read-only DB; apex over Tailscale.

Reproduce (MacBook local):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x APEX_API_URL=http://100.66.147.98:8322 \
  uv run python scripts/research/dispersion_signals_eval.py

Writes full trace to docs/research/2026-07-19-dispersion-signals-eval.json.
No fabrication: every number derives from vol_index_daily / apex adjusted bars.
"""

from __future__ import annotations

import json
import math
import pathlib
from datetime import date as _date

import numpy as np
import psycopg

from uw_scan.config import Settings
from uw_scan.sources.apex import fetch_bars

ROLL = 252  # trailing z-score window
HS = [5, 10, 21, 42]  # forward horizons (trading days)
OUT = pathlib.Path("docs/research")


def _load_index(cur, symbol: str) -> dict[_date, float]:
    cur.execute(
        "SELECT trade_date, close::float8 FROM uw_scan.vol_index_daily "
        "WHERE symbol=%s AND close IS NOT NULL ORDER BY trade_date",
        (symbol,),
    )
    return {d: c for d, c in cur.fetchall()}


def _load_apex(ticker: str) -> dict[_date, float]:
    bars = fetch_bars(ticker, "1d", _date(2010, 1, 1), limit=0)
    out: dict[_date, float] = {}
    for b in bars:
        t = b.get("time")
        c = b.get("close")
        if t and c:
            out[_date.fromisoformat(t[:10])] = float(c)
    return out


def _ztrailing(vals: list[float], window: int) -> list[float | None]:
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


def _pearson(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 else float("nan")


def _tstat(x) -> tuple[float, float, int]:
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], float)
    n = len(x)
    if n < 2:
        return float("nan"), float("nan"), n
    m = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    return round(m, 5), round(t, 2), n


def _ols_t(y, X_cols: dict[str, list]) -> dict:
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
    sigma2 = float(resid @ resid) / (n - k)
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    r2 = 1.0 - (resid @ resid) / (((y - y.mean()) ** 2).sum() + 1e-12)
    out = {"n": int(n), "r2": round(r2, 4)}
    for i, nm in enumerate(names, start=1):
        out[nm] = {
            "coef": round(float(beta[i]), 6),
            "t": round(float(beta[i] / se[i]), 2),
        }
    return out


def _quintile_table(key_z: list, target: list, valid: list[int]) -> list[dict]:
    """Mean target per quintile of key_z over the valid index set."""
    pairs = [
        (key_z[i], target[i])
        for i in valid
        if key_z[i] is not None and target[i] is not None
    ]
    if len(pairs) < 25:
        return []
    zs = np.array([p[0] for p in pairs])
    qs = np.quantile(zs, np.linspace(0, 1, 6))
    rows = []
    for b in range(5):
        lo, hi = qs[b], qs[b + 1]
        sub = [p[1] for p in pairs if (lo <= p[0] <= hi if b == 4 else lo <= p[0] < hi)]
        m, t, n = _tstat(sub)
        rows.append(
            {
                "q": b + 1,
                "z_lo": round(float(lo), 2),
                "z_hi": round(float(hi), 2),
                "n": n,
                "mean": m,
                "t": t,
            }
        )
    return rows


def _nonoverlap(valid: list[int], step: int) -> list[int]:
    out, last = [], -step
    for i in valid:
        if i - last >= step:
            out.append(i)
            last = i
    return out


def main() -> None:
    s = Settings.from_env()
    conn = psycopg.connect(
        host=s.db_host, dbname=s.db_name, user=s.db_user, password=s.db_password
    )
    cur = conn.cursor()
    vix_m = _load_index(cur, "VIX")
    cor_m = _load_index(cur, "COR1M")
    spx_m = _load_index(cur, "SPX")
    conn.close()

    dates = sorted(set(vix_m) & set(cor_m) & set(spx_m))
    vix = [vix_m[d] for d in dates]
    cor = [cor_m[d] for d in dates]
    spx = [spx_m[d] for d in dates]
    ratio = [vix[i] / cor[i] for i in range(len(dates))]  # VIX/COR1M

    vix_z = _ztrailing(vix, ROLL)
    cor_z = _ztrailing(cor, ROLL)
    ratio_z = _ztrailing(ratio, ROLL)

    # forward targets over horizons
    def fwd_ret(series, i, h):
        return series[i + h] / series[i] - 1 if i + h < len(series) else None

    def fwd_mdd(series, i, h):  # worst close drawdown within (i, i+h]
        if i + h >= len(series):
            return None
        window = series[i + 1 : i + h + 1]
        return min(window) / series[i] - 1

    def fwd_chg(series, i, h):
        return series[i + h] - series[i] if i + h < len(series) else None

    def fwd_max(series, i, h):  # max level within (i, i+h] minus current
        if i + h >= len(series):
            return None
        return max(series[i + 1 : i + h + 1]) - series[i]

    result = {
        "meta": {
            "window": [str(dates[ROLL]), str(dates[-1])],
            "n_days_macro": len(dates),
            "roll_z": ROLL,
            "horizons": HS,
            "identity": "COR1M ~= (VIX/VIXEQ)^2 ; VIXEQ/VIX high <=> COR1M low",
            "prior_art": "docs/research/2026-07-07-implied-corr-gate.md (#226): COR1M "
            "no independent short-vol edge, ~0.80 collinear with VIX-z",
        },
        "confounds": {
            "pearson_ratio_z_vs_vix_z": round(_pearson(ratio_z, vix_z), 3),
            "pearson_cor_z_vs_vix_z": round(_pearson(cor_z, vix_z), 3),
            "pearson_ratio_z_vs_cor_z": round(_pearson(ratio_z, cor_z), 3),
        },
    }

    # ---------------- Claim 2: COR1M low (= VIXEQ/VIX high) = warning? ----------------
    # valid index: has z and horizon room
    c2 = {}
    for h in HS:
        valid = [i for i in range(ROLL, len(dates) - h) if cor_z[i] is not None]
        vno = _nonoverlap(valid, h)
        spx_ret = [fwd_ret(spx, i, h) for i in range(len(dates))]
        spx_mdd = [fwd_mdd(spx, i, h) for i in range(len(dates))]
        vix_chg = [fwd_chg(vix, i, h) for i in range(len(dates))]
        vix_mx = [fwd_max(vix, i, h) for i in range(len(dates))]
        c2[f"h{h}"] = {
            "quintiles_by_cor_z__fwd_spx_ret_nonoverlap": _quintile_table(
                cor_z, spx_ret, vno
            ),
            "quintiles_by_cor_z__fwd_spx_maxdrawdown_nonoverlap": _quintile_table(
                cor_z, spx_mdd, vno
            ),
            "quintiles_by_cor_z__fwd_vix_change_nonoverlap": _quintile_table(
                cor_z, vix_chg, vno
            ),
            "quintiles_by_cor_z__fwd_vix_max_nonoverlap": _quintile_table(
                cor_z, vix_mx, vno
            ),
        }
        if h == 21:
            # control: within VIX terciles, does LOW cor add forward weakness?
            vz = [(i, vix_z[i]) for i in vno if vix_z[i] is not None]
            tq = np.quantile([p[1] for p in vz], [0, 1 / 3, 2 / 3, 1.0])
            ctrl = {}
            for ti in range(3):
                lo, hi = tq[ti], tq[ti + 1]
                sub = [i for i, z in vz if (lo <= z <= hi if ti == 2 else lo <= z < hi)]
                czs = [cor_z[i] for i in sub]
                med = float(np.median(czs))
                lo_cor = [i for i in sub if cor_z[i] < med]  # low COR = "warning" side
                hi_cor = [i for i in sub if cor_z[i] >= med]
                ctrl[f"vix_tercile_{ti}"] = {
                    "n": len(sub),
                    "lowcor_fwd_spx_ret": _tstat([spx_ret[i] for i in lo_cor])[0],
                    "hicor_fwd_spx_ret": _tstat([spx_ret[i] for i in hi_cor])[0],
                    "lowcor_fwd_vix_chg": _tstat([vix_chg[i] for i in lo_cor])[0],
                    "hicor_fwd_vix_chg": _tstat([vix_chg[i] for i in hi_cor])[0],
                }
            c2["control_vixtercile_x_cor_h21"] = ctrl
    result["claim2_cor_low_is_warning"] = c2

    # ---------------- Claim 1: VIX/COR1M high => high-beta underperforms ----------------
    sphb = _load_apex("SPHB")
    splv = _load_apex("SPLV")
    hb_dates = sorted(set(dates) & set(sphb) & set(splv))
    di = {d: i for i, d in enumerate(dates)}  # map back to macro index for z-scores
    # high-beta minus low-vol forward spread return, on the aligned calendar
    hb_close = {d: sphb[d] for d in hb_dates}
    lv_close = {d: splv[d] for d in hb_dates}
    c1 = {"span": [str(hb_dates[0]), str(hb_dates[-1])], "n_days": len(hb_dates)}
    for h in HS:
        # forward spread return needs d and the date h trading days later on hb calendar
        idxmap = {d: k for k, d in enumerate(hb_dates)}
        hb_ret = {}
        for k in range(len(hb_dates) - h):
            d0, dh = hb_dates[k], hb_dates[k + h]
            hb_ret[d0] = (hb_close[dh] / hb_close[d0] - 1) - (
                lv_close[dh] / lv_close[d0] - 1
            )
        # align to macro z on same dates
        valid = [
            d
            for d in hb_dates
            if d in hb_ret and di.get(d) is not None and ratio_z[di[d]] is not None
        ]
        vno_d = []
        last = -h
        for d in valid:
            k = idxmap[d]
            if k - last >= h:
                vno_d.append(d)
                last = k
        rz = [ratio_z[di[d]] for d in vno_d]
        vz = [vix_z[di[d]] for d in vno_d]
        cz = [cor_z[di[d]] for d in vno_d]
        y = [hb_ret[d] for d in vno_d]
        # quintiles by ratio_z / vix_z, reused via macro index space
        idxlist = [di[d] for d in vno_d]
        rzmap = [None] * len(dates)
        vzmap = [None] * len(dates)
        ymap = [None] * len(dates)
        for d in vno_d:
            rzmap[di[d]] = ratio_z[di[d]]
            vzmap[di[d]] = vix_z[di[d]]
            ymap[di[d]] = hb_ret[d]
        c1[f"h{h}"] = {
            "quintiles_by_ratio_z__fwd_highbeta_spread": _quintile_table(
                rzmap, ymap, idxlist
            ),
            "quintiles_by_vix_z__fwd_highbeta_spread": _quintile_table(
                vzmap, ymap, idxlist
            ),
            "ols_fwd_hb__ratio_z": _ols_t(y, {"ratio_z": rz}),
            "ols_fwd_hb__vix_z": _ols_t(y, {"vix_z": vz}),
            "ols_fwd_hb__vix_z_plus_cor_z_MARGINAL": _ols_t(
                y, {"vix_z": vz, "cor_z": cz}
            ),
            "n_nonoverlap": len(vno_d),
        }
    result["claim1_highbeta_underperforms"] = c1

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "2026-07-19-dispersion-signals-eval.json").write_text(
        json.dumps(result, indent=2, default=str)
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
