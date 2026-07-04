"""Raw-SVI (Gatheral) single-expiry smile fit + no-arbitrage diagnostics.

Pure numpy/scipy. No DB, no I/O. Feasibility-spike core for the surface
mispricing signal (radon-adoption R1). See docs/research/svi-surface-fit/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import log
from typing import Any, Iterable

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        return (self.a, self.b, self.rho, self.m, self.sigma)


def raw_svi_total_variance(k: np.ndarray, p: SVIParams) -> np.ndarray:
    """w(k) = a + b(rho(k-m) + sqrt((k-m)^2 + sigma^2))."""
    km = np.asarray(k, float) - p.m
    return p.a + p.b * (p.rho * km + np.sqrt(km * km + p.sigma * p.sigma))


def _svi_deriv(k: np.ndarray, p: SVIParams) -> tuple[np.ndarray, np.ndarray]:
    km = np.asarray(k, float) - p.m
    root = np.sqrt(km * km + p.sigma * p.sigma)
    w1 = p.b * (p.rho + km / root)
    w2 = p.b * p.sigma * p.sigma / (root**3)
    return w1, w2


def butterfly_g(k: np.ndarray, p: SVIParams) -> np.ndarray:
    """Gatheral g(k); g>=0 everywhere <=> no butterfly (density) arbitrage."""
    k = np.asarray(k, float)
    w = raw_svi_total_variance(k, p)
    w1, w2 = _svi_deriv(k, p)
    return (
        (1.0 - k * w1 / (2.0 * w)) ** 2 - (w1 * w1 / 4.0) * (1.0 / w + 0.25) + w2 / 2.0
    )


def fit_raw_svi(k, w, weights=None) -> tuple[SVIParams, float]:
    """Least-squares raw-SVI fit of total variance w(k). Multi-start over (m, sigma).

    Returns (params, rmse_total_variance). Bounds: b>=0, |rho|<1, sigma>0.
    """
    k = np.asarray(k, float)
    w = np.asarray(w, float)
    sw = np.ones_like(w) if weights is None else np.sqrt(np.asarray(weights, float))

    def resid(theta):
        return sw * (raw_svi_total_variance(k, SVIParams(*theta)) - w)

    lo = [1e-8, 1e-8, -0.999, float(k.min()) - 0.5, 1e-4]
    hi = [
        max(float(w.max()), 1e-6) * 2.0 + 1e-6,
        10.0,
        0.999,
        float(k.max()) + 0.5,
        5.0,
    ]
    a0 = max(float(w.min()), 1e-6)
    m_at_min = float(k[int(np.argmin(w))]) if k.size else 0.0
    best = None
    for m0 in {0.0, m_at_min}:
        for s0 in (0.05, 0.2, 0.5):
            theta0 = [a0, 0.1, -0.3, float(np.clip(m0, lo[3], hi[3])), s0]
            try:
                sol = least_squares(
                    resid, theta0, bounds=(lo, hi), method="trf", max_nfev=2000
                )
            except Exception:
                continue
            if best is None or sol.cost < best.cost:
                best = sol
    if best is None:
        raise RuntimeError("SVI fit failed for all starts")
    p = SVIParams(*(float(x) for x in best.x))
    rmse_w = float(np.sqrt(np.mean((raw_svi_total_variance(k, p) - w) ** 2)))
    return p, rmse_w


def rmse_vol_points(k, iv, p: SVIParams, t_years: float) -> float:
    """RMSE(marked IV, SVI IV) in VOL POINTS (0.5 == half a vol point)."""
    w = np.maximum(raw_svi_total_variance(np.asarray(k, float), p), 0.0)
    iv_fit = np.sqrt(w / t_years)
    return float(np.sqrt(np.mean((iv_fit - np.asarray(iv, float)) ** 2)) * 100.0)


def build_smile(
    rows: Iterable[dict[str, Any]], spot: float, market_date: date, expiry: date
):
    """OTM-wing smile: put_iv for K<spot, call_iv for K>=spot.

    Returns (k, iv, w, t_years, strikes) as numpy arrays. Null/<=0 IV rows dropped.
    """
    t_years = (expiry - market_date).days / 365.0
    ks, ivs, strikes_used = [], [], []
    for r in rows:
        strike = float(r["strike"])
        iv_raw = r["put_iv"] if strike < spot else r["call_iv"]
        if iv_raw is None or strike <= 0.0:
            continue
        iv = float(iv_raw)
        if iv <= 0.0:
            continue
        ks.append(log(strike / spot))
        ivs.append(iv)
        strikes_used.append(strike)
    k = np.array(ks, float)
    iv = np.array(ivs, float)
    return k, iv, iv * iv * t_years, t_years, np.array(strikes_used, float)


def calendar_violations(fitted_by_expiry, ref_k: float = 0.0) -> int:
    """Count expiries where total variance at ref_k DROPS vs the prior (shorter) one."""
    items = sorted(fitted_by_expiry, key=lambda x: x[1])  # by t_years
    prev_w, viol = None, 0
    for _exp, _t, p in items:
        wk = float(raw_svi_total_variance(np.array([ref_k]), p)[0])
        if prev_w is not None and wk < prev_w - 1e-9:
            viol += 1
        prev_w = wk
    return viol
