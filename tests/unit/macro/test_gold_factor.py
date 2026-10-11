"""uw_scan.macro.gold_factor on labelled synthetic data. Parity with the signal-lab study on
real data is scripts/research/gold_factor_parity.py (result in docs/research/)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from uw_scan.macro import gold_factor as gf


def _levels(n: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    walk = lambda s0, vol: s0 * np.exp(np.cumsum(rng.normal(0, vol, n)))  # noqa: E731
    lv = {leg: walk(1.0 + i, 0.005) for i, leg in enumerate(gf.PAIRS)}
    lv["XAUUSD"] = walk(1800.0, 0.01)
    lv["DFII10"] = 1.0 + np.cumsum(rng.normal(0, 0.03, n))
    lv["DGS10"] = 3.0 + np.cumsum(rng.normal(0, 0.03, n))
    return pd.DataFrame(lv, index=idx)


def test_changes_skip_incomplete_dates_without_forward_fill() -> None:
    lv = _levels(10)
    lv.iloc[4, lv.columns.get_loc("DFII10")] = np.nan
    chg = gf.changes(lv)
    assert lv.index[4] not in chg.index and len(chg) == 8  # base row + the gap dropped
    # the row after the gap changes from the last complete date, two dates back
    assert np.isclose(chg.loc[lv.index[5], "r"], 100 * (lv["DFII10"].iloc[5] - lv["DFII10"].iloc[3]))


def test_rolling_fit_matches_statsmodels_and_parts_sum_to_gold() -> None:
    chg = gf.changes(_levels())
    out = gf.compute(chg)
    X = np.c_[np.ones(len(chg)), chg[["r", "d", "s"]].to_numpy()]
    t = len(chg) - 1
    res = sm.OLS(chg["y"].to_numpy()[t - 251 : t + 1], X[t - 251 : t + 1]).fit(
        cov_type="HAC", cov_kwds={"maxlags": 4}
    )
    assert np.allclose(out.iloc[t][["a", "b_r", "b_d", "b_s"]].to_numpy(float), res.params)
    assert np.isclose(out.iloc[t]["b_d_lo95"], res.conf_int(0.05)[2, 0])
    assert out["b_r"].iloc[: gf.W - 1].isna().all() and np.isfinite(out["b_r"].iloc[gf.W - 1])
    parts = out[["own_trailing_drift", "real_yield_part", "dollar_part", "haven_part", "unexplained_1"]]
    ok = parts.notna().all(axis=1)
    assert ok.sum() == len(chg) - gf.W - 1
    assert np.allclose(parts[ok].sum(axis=1), out.loc[ok, "gold_change"], atol=1e-12)


def test_publish_needs_five_consecutive_rows() -> None:
    U, M, P, L = gf.UNDEF, gf.MUCH, gf.PART, gf.LITTLE
    raw = [U, M, P, P, P, P, M, P, P, P, P, P, L, L]
    assert gf.publish(raw) == [U, M, M, M, M, M, M, M, M, M, M, P, P, P]
