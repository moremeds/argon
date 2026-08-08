"""E1 — is the ATM-IV cone calibrated against realised moves? (spec §3.2)

Under Black-Scholes with r = q = 0, ln(S_T/S_0) ~ N(-sigma^2 T/2, sigma^2 T),
so the standardised residual

    z = [ ln(S_{t+h}/S_t) + sigma^2 T/2 ] / ( sigma * sqrt(T) )

is N(0,1) if the cone is right. It will not be: the cone is a RISK-NEUTRAL
density tested against PHYSICAL realisations, so z is biased on two axes — the
equity risk premium shifts its mean, the variance risk premium shrinks its
spread.

Only the second is correctable. Estimating drift from ~154 trading days is
hopeless (annualised SE ~= 0.40/sqrt(154/252) ~= 51%, larger than any drift being
estimated); variance converges in days, drift needs decades. So the calibration
fits SCALE only and publishes mean(z) as a diagnostic that is never applied.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
from scipy.stats import norm

# |z| < 1 -> 68.27%,  |z| < 1.96 -> 95.00%.
# 95.4% belongs to |z| < 2. Pairing 95.4% with 1.96 fabricates a 0.4pt miss.
NOMINAL_COVERAGE: dict[float, float] = {
    1.0: float(norm.cdf(1.0) - norm.cdf(-1.0)),
    1.96: float(norm.cdf(1.96) - norm.cdf(-1.96)),
}

# MAD -> sigma consistency constant for a normal, 1/Phi^-1(0.75).
_MAD_TO_SIGMA = 1.4826


def standardized_residual(
    log_return: float, sigma: float, horizon_days: int, trading_days: int = 252
) -> float:
    """z-score of a realised log return against its risk-neutral cone."""
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")
    t = horizon_days / trading_days
    return (log_return + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))


def pit(z: np.ndarray) -> np.ndarray:
    """Probability integral transform. Uniform(0,1) iff the cone is calibrated."""
    return norm.cdf(np.asarray(z, dtype=float))


def coverage(z: np.ndarray, level: float) -> float:
    """Share of residuals strictly inside +/- level."""
    arr = np.asarray(z, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.mean(np.abs(arr) < level))


def scale_estimates(z: np.ndarray) -> dict:
    """Scale (two estimators) and location (diagnostic only) of the residuals.

    `std` is the maximum-likelihood scale under normality and is the headline
    shrink factor k. `mad` is the robust companion: a plain standard deviation
    over fat-tailed equity returns is precisely the estimator not to trust alone,
    and a large std/mad gap is itself the finding.

    `mean` is the equity-risk-premium diagnostic. It is REPORTED, never applied.
    """
    arr = np.asarray(z, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return {
            "std": float("nan"),
            "mad": float("nan"),
            "mean": float("nan"),
            "n": int(arr.size),
        }
    med = float(np.median(arr))
    return {
        "std": float(np.std(arr, ddof=1)),
        "mad": float(np.median(np.abs(arr - med)) * _MAD_TO_SIGMA),
        "mean": float(np.mean(arr)),
        "n": int(arr.size),
    }


def nonoverlapping_subsample(
    values: np.ndarray, step: int, offset: int = 0
) -> np.ndarray:
    """Every `step`-th observation from `offset` — independent under an h-day
    overlap when step >= h."""
    if step <= 0:
        raise ValueError(f"step must be positive, got {step}")
    return np.asarray(values, dtype=float)[offset::step]


def moving_block_bootstrap(
    values: np.ndarray,
    statistic: Callable[[np.ndarray], float],
    *,
    block: int,
    n_boot: int,
    seed: int,
) -> dict:
    """Percentile CI for `statistic` under h-day overlap. SINGLE SERIES ONLY.

    At h = 5 with daily sampling, consecutive residuals share 4 of 5 days.
    Overlap does not bias point estimates but destroys the independence every
    closed-form CI and p-value assumes. Resampling contiguous blocks preserves
    the dependence the naive bootstrap would throw away.

    For anything pooled across tickers use panel_block_bootstrap — see its
    docstring for what this one silently gets wrong there.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if block <= 0:
        raise ValueError(f"block must be positive, got {block}")
    if n < block:
        raise ValueError(f"sample of {n} shorter than block {block}")
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    starts_hi = n - block + 1
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        starts = rng.integers(0, starts_hi, size=n_blocks)
        sample = np.concatenate([arr[s : s + block] for s in starts])[:n]
        stats[i] = float(statistic(sample))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return {
        "point": float(statistic(arr)),
        "lo": float(lo),
        "hi": float(hi),
        "n_boot": int(n_boot),
        "block": int(block),
    }


def panel_block_bootstrap(
    dates: Sequence,
    values: np.ndarray,
    statistic: Callable[[np.ndarray], float],
    *,
    block: int,
    n_boot: int,
    seed: int,
) -> dict:
    """Block bootstrap over a PANEL — resample blocks of DATES, keep every ticker.

    Use this, NOT moving_block_bootstrap, for any statistic pooled across tickers.

    moving_block_bootstrap treats its input as ONE time series. Handed a flattened
    (date x ticker) panel it resamples blocks that straddle ticker boundaries,
    which shuffles observations from different tickers together and implicitly
    asserts they are independent on a given day. They are not: this watchlist is
    concentrated in AI/semis and shares a common volatility factor.

    The consequence is not academic. Destroying cross-sectional correlation
    understates the variance of the pooled estimator, so the CI comes out too
    narrow — and G3 compares per-ticker dispersion AGAINST that CI width. A CI
    that is too narrow makes `dispersion > width` easier to satisfy, so G3 would
    call for a per-ticker table and a refit job on a statistical artifact.
    Measured: ~6x too narrow at a common-factor strength of 0.6.

    Resampling whole dates preserves both dependencies: serial (blocks are
    contiguous in time) and cross-sectional (a sampled date brings all of its
    tickers along). For a single ticker it degenerates exactly to the
    moving-block version, so it is safe to use everywhere.
    """
    arr = np.asarray(values, dtype=float)
    d = np.asarray(dates)
    keep = np.isfinite(arr)
    arr, d = arr[keep], d[keep]
    if arr.size == 0:
        return {
            "point": float("nan"),
            "lo": float("nan"),
            "hi": float("nan"),
            "n_boot": int(n_boot),
            "block": int(block),
            "n_dates": 0,
        }

    uniq = np.unique(d)
    by_date = {u: arr[d == u] for u in uniq}
    n_dates = len(uniq)
    if block <= 0:
        raise ValueError(f"block must be positive, got {block}")
    if n_dates < block:
        raise ValueError(f"panel has {n_dates} dates, shorter than block {block}")

    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n_dates / block))
    starts_hi = n_dates - block + 1
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        starts = rng.integers(0, starts_hi, size=n_blocks)
        picked = np.concatenate([uniq[s : s + block] for s in starts])[:n_dates]
        sample = np.concatenate([by_date[u] for u in picked])
        stats[i] = float(statistic(sample))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return {
        "point": float(statistic(arr)),
        "lo": float(lo),
        "hi": float(hi),
        "n_boot": int(n_boot),
        "block": int(block),
        "n_dates": int(n_dates),
    }
