"""GJR-GARCH bootstrap cone + EWMA baseline — vendored VERBATIM from signal-lab.

Source: signal-lab @ 0f893513, scripts/forward_paths.py + research/runs/_shd_v5.py.
Only this header and the import block differ from the source; every class and function
body below is byte-identical to its origin lines. DO NOT reformat, rename, or "fix" —
the load-bearing quirks (simple-return EWMA variance consumed as log vol; isfinite
filtering BEFORE log1p; v[t] lag in gjr_std_residuals; percent->log at exactly one point
in _gjr_simulate; np.quantile default method="linear") are frozen contract, and the
golden parity test fails on any behavioural change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from uw_scan.density.constants import GJR_MIN_OBS, LAM, QUANTILES  # noqa: F401 (GJR_MIN_OBS re-exported for fit.py)

@dataclass
class Cone:
    asof: pd.Timestamp
    price0: float
    horizons: np.ndarray  # (H,) = [1, 2, ..., H]
    quantiles: np.ndarray  # (len(QUANTILES),)
    cum_return_q: np.ndarray  # (H, len(QUANTILES)) cumulative simple-return quantiles
    # (H, M) cumulative simple returns per Monte-Carlo path, or None for a
    # quantile-only arm. Consumers of CRPS / Brier / PIT / path metrics need draws,
    # not quantiles; every consumer must handle None.
    samples: np.ndarray | None = None

    def price_q(self) -> np.ndarray:
        return self.price0 * (1.0 + self.cum_return_q)

    def at(self, horizon: int) -> np.ndarray:
        """Quantile row for a horizon VALUE (horizons need not be contiguous — arm D emits
        only the primary horizons). Consumers must index by value via this, not by h-1."""
        i = int(np.where(self.horizons == horizon)[0][0])
        return self.cum_return_q[i]


def cone_from_paths(
    price_mult_by_h: np.ndarray,
    asof: pd.Timestamp,
    price0: float,
    quantiles: tuple[float, ...] = QUANTILES,
    keep_samples: bool = True,
) -> Cone:
    """price_mult_by_h: (H, M) gross multipliers (price_{t+h}/price_t) per path. Quantiles
    are taken across the M paths at each horizon; cum return = multiplier - 1."""
    mult = np.asarray(price_mult_by_h, dtype=float)
    H = mult.shape[0]
    cum = mult - 1.0
    q = np.quantile(cum, quantiles, axis=1).T  # (H, len(quantiles))
    return Cone(
        asof=asof,
        price0=float(price0),
        horizons=np.arange(1, H + 1),
        quantiles=np.asarray(quantiles, dtype=float),
        cum_return_q=q,
        samples=cum if keep_samples else None,
    )


def ewma_cone(
    returns_hist: np.ndarray,
    price0: float,
    asof: pd.Timestamp,
    H: int,
    lam: float = 0.94,
    quantiles: tuple[float, ...] = QUANTILES,
    M: int = 10000,
    seed: int = 0,
) -> Cone:
    """RiskMetrics EWMA 1-day sigma, zero drift (random walk), lognormal quantile bands
    scaled by sqrt(h): cum_return_q(h,p) = exp(z_p * sigma * sqrt(h)) - 1. The dumb floor
    every other arm must beat on calibration+sharpness.

    Quantiles stay ANALYTIC (exact, seed-independent). `samples` is an additional seeded
    draw used only by CRPS / Brier / PIT / path metrics. It cumulates iid increments so
    each column is a coherent path through time — per-horizon independent draws would
    match the marginals but destroy first-passage and touch probability."""
    from scipy.stats import norm

    r = np.asarray(returns_hist, dtype=float)
    r = r[np.isfinite(r)]
    var = 0.0
    for x in r:
        var = lam * var + (1.0 - lam) * x * x
    sigma1 = float(np.sqrt(var))
    z = norm.ppf(quantiles)
    h = np.arange(1, H + 1)[:, None]
    cum_return_q = np.expm1(z[None, :] * sigma1 * np.sqrt(h))
    return Cone(
        asof=asof,
        price0=float(price0),
        horizons=np.arange(1, H + 1),
        quantiles=np.asarray(quantiles, dtype=float),
        cum_return_q=cum_return_q,
        samples=_gbm_samples(sigma1, H, M, seed),
    )


def _gbm_samples(sigma1: float, H: int, M: int, seed: int) -> np.ndarray:
    """(H, M) cumulative simple returns from a zero-drift lognormal random walk with
    constant daily log-vol sigma1. Cumulating log increments keeps each column a
    coherent path, which the path metrics in scripts/path_metrics.py depend on."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, sigma1, size=(H, M))
    return np.expm1(np.cumsum(steps, axis=0))


# --- Arm S / S+R: GJR-GARCH conditional scale (hypothesis-v5.md §3) ----------------------
#
# UNITS AND FIRST-STEP STATE ARE FROZEN (v5 §3, F-8). Both are silent-failure surfaces: a
# mis-set unit gives a 100x scale error and a mis-set first step gives a one-day offset, and
# either produces a confident WRONG calibration verdict rather than a crash.
#
#     fit input        =  100 * log_return           (percent, the arch convention)
#     fitted omega/var are in percent^2
#     path log return  =  simulated_percent / 100
#     v_{t+1} = omega + (alpha + gamma*I[r_t < 0]) * r_t^2 + beta * v_t
#
# The as-of-t forecast has ALREADY absorbed r_t, so the first simulated return uses v_{t+1}.


def _to_pct_log(returns_hist: np.ndarray) -> np.ndarray:
    """Simple returns (this module's convention) -> percent log returns (arch's)."""
    r = np.asarray(returns_hist, dtype=float)
    r = r[np.isfinite(r)]
    return 100.0 * np.log1p(r)


def gjr_var_path(returns_hist: np.ndarray, params: dict) -> np.ndarray:
    """(n+1,) conditional variances in percent^2. `out[t]` is the variance OF period t, known
    before r_t is drawn; `out[-1]` is `v_{t+1}`, the variance of the next, unobserved period.

    Run explicitly rather than read off the fit, because parameters are held constant between
    21-day refits (v5 §3) and the recursion must keep absorbing returns in between. Seeded at
    the unconditional variance; with beta ~ 0.9 that choice decays out within ~100 obs and the
    minimum history is 756."""
    o, a, g, b = params["omega"], params["alpha"], params["gamma"], params["beta"]
    r_pct = _to_pct_log(returns_hist)
    out = np.empty(r_pct.size + 1)
    v = o / max(1.0 - a - g / 2.0 - b, 1e-12)
    out[0] = v
    for t in range(r_pct.size):
        v = o + (a + (g if r_pct[t] < 0.0 else 0.0)) * r_pct[t] * r_pct[t] + b * v
        out[t + 1] = v
    return out


def _gjr_simulate(v_next: float, params: dict, z: np.ndarray) -> np.ndarray:
    """(H, M) cumulative gross multipliers from innovations `z` of shape (H, M).

    `z` carries the innovation SHAPE and must be unit-variance; everything else here is
    shared. Arm S passes Gaussian z, arm S+R passes standardized-residual blocks — that
    single substitution is the whole ablation (v5 §3)."""
    o, a, g, b = params["omega"], params["alpha"], params["gamma"], params["beta"]
    H, M = z.shape
    v = np.full(M, float(v_next))
    log_steps = np.empty((H, M))
    for h in range(H):
        r_pct = np.sqrt(v) * z[h]
        log_steps[h] = r_pct / 100.0  # percent -> log return, the ONLY conversion point
        v = o + (a + g * (r_pct < 0.0)) * r_pct * r_pct + b * v
    return np.exp(np.cumsum(log_steps, axis=0))


def gjr_std_residuals(returns_hist: np.ndarray, params: dict, burn_in: int = 252) -> np.ndarray:
    """Causally standardized GJR residuals, variance-normalised to exactly 1 (v5 §3).

    `z_t = r_pct[t] / sqrt(v[t])` uses the variance of period t, which was fixed BEFORE r_t
    was drawn — dividing by a sigma that has already absorbed r_t would shrink exactly the
    tail observation the overlay exists to preserve.

    Normalising to unit variance keeps the ablation shape-only; without it the pool would
    carry a scale of its own and S+R would differ from S in two factors."""
    r_pct = _to_pct_log(returns_hist)
    v = gjr_var_path(returns_hist, params)[: r_pct.size]  # v[t] precedes r_pct[t]
    z = r_pct / np.sqrt(v)
    z = z[int(burn_in) :]
    z = z[np.isfinite(z)]
    if z.size == 0:
        return z
    return z / np.sqrt(np.mean(z * z))


def gjr_std_boot_cone(
    returns_hist: np.ndarray,
    price0: float,
    asof: pd.Timestamp,
    H: int,
    params: dict,
    burn_in: int = 252,
    min_pool: int = 756,
    quantiles: tuple[float, ...] = QUANTILES,
    M: int = 10000,
    seed: int = 0,
) -> Cone | None:
    """Arm S+R — arm S with ONE substitution: Gaussian innovations -> standardized blocks.

    Returns None when the pool is shorter than `min_pool`; v5 §3 requires the caller to fall
    back to arm S and label `degraded_overlay`.

    SAMPLED at M, not exhaustive — deliberately the opposite of `std_bootstrap_cone`. That arm
    enumerated because ITS baseline (`ewma_cone`) emits closed-form quantiles, so sampling
    would have charged the candidate Monte-Carlo noise the baseline never paid. Here the
    baseline is arm S, itself simulated at M, so MATCHING M is what keeps the noise symmetric.
    Same principle, opposite choice, because the comparison changed."""
    pool = gjr_std_residuals(returns_hist, params, burn_in=burn_in)
    if pool.size < int(min_pool) + H:
        return None
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, pool.size - H + 1, size=M)
    z = np.stack([pool[starts + h] for h in range(H)])  # (H, M) contiguous blocks
    v_next = float(gjr_var_path(returns_hist, params)[-1])
    return cone_from_paths(_gjr_simulate(v_next, params, z), asof, price0, quantiles)


def _ewma_sigma_series(r: np.ndarray, lam: float = LAM) -> np.ndarray:
    """sigma AFTER absorbing each return, so `out[i]` is arm A's sigma1 for history r[:i+1].
    O(n) once instead of O(n^2) over 1500 expanding `ewma_cone` calls; a test pins it to
    `ewma_cone`'s own value."""
    out = np.empty(r.size)
    var = 0.0
    for t in range(r.size):
        var = lam * var + (1.0 - lam) * r[t] * r[t]
        out[t] = np.sqrt(var)
    return out


def arm_a_quantiles(sigma1: float, H: int) -> np.ndarray:
    """(H, len(QUANTILES)) — arm A's ANALYTIC cone. Seed-independent by construction."""
    from scipy.stats import norm

    z = norm.ppf(QUANTILES)
    h = np.arange(1, H + 1)[:, None]
    return np.expm1(z[None, :] * float(sigma1) * np.sqrt(h))
