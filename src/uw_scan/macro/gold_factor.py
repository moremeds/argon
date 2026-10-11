"""Gold factor model: how much of gold's daily move the 10Y real yield, the dollar and the
safe-haven spread explain. A port of the signal-lab gold-regime study (estimator A, regime
label, daily parts), recomputed by argon from its own stored inputs.

Historical description only. The direction test (Phase 3) failed, so nothing here is a
forecast: a slope is the fit over the last 252 rows, not a forward sensitivity.

Source of truth (signal-lab, research/gold-regime-phase3):
  runs/2026-10-09-gold-regime-direction/scripts/{panel,estimators,layers}.py
  forward/gold-regime-direction/statesheet/build_sheet.py (items 1, 3, 3b)

Inputs per date (levels): XAUUSD and the six ICE dollar-index pairs as IB 1-day MIDPOINT
closes (the bar ending 17:00 New York, keyed by New York date), DFII10 and DGS10 from FRED.
A row exists only on dates with every input present; each row changes from the previous such
date (no forward fill). DGS10 only gates the calendar, as in the study.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

DXY_CONSTANT = 50.14348112
DXY_EXPONENT = {
    "EURUSD": -0.576,
    "USDJPY": 0.136,
    "GBPUSD": -0.119,
    "USDCAD": 0.091,
    "USDSEK": 0.042,
    "USDCHF": 0.036,
}
PAIRS = tuple(DXY_EXPONENT)
PRICE_LEGS = ("XAUUSD", *PAIRS)
INPUTS = (*PRICE_LEGS, "DFII10", "DGS10")

W = 252  # rolling rows
E_WINDOW = 63  # explained-share rows
SWITCH_ROWS = 5  # a new label publishes after this many consecutive rows
# 33rd/67th percentiles of the explained share on rows to 2021-12-31, fixed by the study.
# ponytail: frozen constants, not refit; re-derive only if the study re-freezes its thresholds.
E_LO = 0.21839387732373133
E_HI = 0.4020650422009684

MUCH, PART, LITTLE, UNDEF = "much", "part", "little", None
# the study's names, kept in the parity check
STUDY_NAME = {MUCH: "DRIVEN", PART: "PARTIAL", LITTLE: "OWN-DRIVER"}


def changes(levels: pd.DataFrame) -> pd.DataFrame:
    """Daily variables from a date-indexed frame of input levels.

    y, d, h, s in percent (100 x log change); r in bp. Rows: dates with every input present,
    each changing from the previous complete date; the first complete date is the base only.
    """
    g = levels.loc[:, list(INPUTS)].sort_index().dropna()
    lg = 100 * np.log(g[list(PRICE_LEGS)]).diff()
    dxy = DXY_CONSTANT * np.exp(sum(w * np.log(g[p]) for p, w in DXY_EXPONENT.items()))
    out = pd.DataFrame(index=g.index)
    out["y"] = lg["XAUUSD"]
    out["r"] = 100 * g["DFII10"].diff()
    out["d"] = 100 * np.log(dxy).diff()
    out["s"] = 0.5 * (lg["USDCHF"] + lg["USDJPY"]) - out["d"]
    return out.iloc[1:]


def rolling_ols(y: np.ndarray, X: np.ndarray, w: int = W) -> np.ndarray:
    """b_t from rows t-w+1..t; NaN before row w-1."""
    n, k = X.shape
    zz = np.concatenate(
        [np.zeros((1, k, k)), np.cumsum(X[:, :, None] * X[:, None, :], axis=0)]
    )
    zy = np.concatenate([np.zeros((1, k)), np.cumsum(X * y[:, None], axis=0)])
    out = np.full((n, k), np.nan)
    out[w - 1 :] = np.linalg.solve(zz[w:] - zz[:-w], (zy[w:] - zy[:-w])[..., None])[
        ..., 0
    ]
    return out


def lag2(a: np.ndarray) -> np.ndarray:
    out = np.full_like(a, np.nan)
    out[2:] = a[:-2]
    return out


def rsum(a: np.ndarray, h: int) -> np.ndarray:
    """Sum over rows t-h+1..t; NaN unless all h rows are finite."""
    ok = np.isfinite(a)
    c = np.concatenate([[0.0], np.cumsum(np.where(ok, a, 0.0))])
    k = np.concatenate([[0.0], np.cumsum(ok)])
    out = np.full(len(a), np.nan)
    out[h - 1 :] = np.where(k[h:] - k[:-h] == h, c[h:] - c[:-h], np.nan)
    return out


def publish(raw: list) -> list:
    """The first defined raw label publishes at once; later a new label publishes at the row
    where the raw label has equalled it on SWITCH_ROWS consecutive rows."""
    pub: list = [UNDEF] * len(raw)
    first = next((i for i, v in enumerate(raw) if v is not UNDEF), None)
    if first is None:
        return pub
    cur, run_lab, run = raw[first], UNDEF, 0
    for t in range(first, len(raw)):
        run = run + 1 if raw[t] == run_lab else 1
        run_lab = raw[t]
        if run_lab != cur and run_lab is not UNDEF and run >= SWITCH_ROWS:
            cur = run_lab
        pub[t] = cur
    return pub


def nw_lag(n: int) -> int:
    """Newey-West (1994) automatic lag, Bartlett kernel."""
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def compute(chg: pd.DataFrame, *, intervals: bool = True) -> pd.DataFrame:
    """All per-row outputs from the output of `changes`. Rows before the first full window
    carry NaN coefficients; parts and U need two more rows."""
    y = chg["y"].to_numpy(float)
    F = chg[["r", "d", "s"]].to_numpy(float)
    X = np.c_[np.ones(len(y)), F]
    B = rolling_ols(y, X)
    BL = lag2(B)
    U = y - np.einsum("ij,ij->i", X, BL)
    e = 1 - rsum(U**2, E_WINDOW) / rsum(y**2, E_WINDOW)
    ok = np.isfinite(e) & np.isfinite(B[:, 1]) & np.isfinite(B[:, 2])
    raw = [
        UNDEF
        if not ok[t]
        else MUCH
        if e[t] >= E_HI and B[t, 1] < 0 and B[t, 2] < 0
        else LITTLE
        if e[t] <= E_LO or (B[t, 1] >= 0 and B[t, 2] >= 0)
        else PART
        for t in range(len(y))
    ]
    out = pd.DataFrame(
        {
            "a": B[:, 0],
            "b_r": B[:, 1],
            "b_d": B[:, 2],
            "b_s": B[:, 3],
            "explained_share": e,
            "raw_label": raw,
            "published_label": publish(raw),
            "gold_change": y,
            "own_trailing_drift": BL[:, 0],
            "real_yield_part": BL[:, 1] * F[:, 0],
            "dollar_part": BL[:, 2] * F[:, 1],
            "haven_part": BL[:, 3] * F[:, 2],
            "unexplained_1": U,
            "unexplained_5": rsum(U, 5),
            "unexplained_21": rsum(U, 21),
            "real_yield_change_bp": F[:, 0],
            "dollar_change_pct": F[:, 1],
            "haven_change_pct": F[:, 2],
        },
        index=chg.index,
    )
    if intervals:
        ci = np.full((len(y), 6), np.nan)
        lag = nw_lag(W)
        for t in range(W - 1, len(y)):
            w = slice(t - W + 1, t + 1)
            res = sm.OLS(y[w], X[w]).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
            ci[t] = np.asarray(res.conf_int(0.05))[1:].ravel()
        for j, nm in enumerate(
            ("b_r_lo95", "b_r_hi95", "b_d_lo95", "b_d_hi95", "b_s_lo95", "b_s_hi95")
        ):
            out[nm] = ci[:, j]
    return out
