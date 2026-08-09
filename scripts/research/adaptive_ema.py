"""Adaptive-EMA catalog: causal smoothers with a time-varying alpha.

Provenance: transcribed from a Chinese-language article ("17 种自适应 EMA 变体",
supplied by the operator 2026-07-27). The article *claims* 17 variants but only
ships 7 implementations; the rest are named in its summary with no code. See
NOT_IMPLEMENTED below -- do not invent them.

This module is a RESEARCH REFERENCE, not production code. Nothing in uw_scan
imports it. Promote a function into `cards/` only after a probe shows it beats
the plain EMA on a metric that matters.

Every filter here is strictly causal: y[t] depends only on x[<=t]. That is a
property worth stating loudly because the source article asserted it while
violating it -- three of its snippets used full-sample or backfilled statistics.
Deviations from the source are marked `# FIX:` and listed in DEVIATIONS.

Self-check: `uv run python scripts/research/adaptive_ema.py`
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Named in the source article's summary but shipped with NO implementation.
# Listed so a future reader knows the catalog is incomplete by 10, and knows
# that the missing 10 were never actually specified -- not that we dropped them.
NOT_IMPLEMENTED = (
    "VA-EMA (volatility-adaptive; distinct from NA-EMA only by the article's own"
    " taxonomy, no formula given)",
    "Ehlers filters (MAMA/FAMA, super-smoother -- named only)",
    "ML-driven EMA (a model predicts alpha_t -- named only, no target/feature spec)",
    "...and 7 further unnamed variants making up the article's claimed 17.",
)

DEVIATIONS = (
    "na_ema: source used `sigma.median()` over the WHOLE series as the reference"
    " -- full-sample lookahead. Replaced with an expanding median.",
    "na_ema: source clamped alpha only from above (`min(a, 1.0)`), so a vol spike"
    " drives alpha->1, i.e. the filter turns into passthrough exactly when noise"
    " is worst. Added a two-sided clamp.",
    "na_ema/snr_ema: source used `.fillna(method='bfill')` on the rolling stat --"
    " deprecated in pandas 2.x AND lookahead (fills the warmup with future vol)."
    " Replaced with a base-alpha fallback during warmup.",
    "frama: source's fractal dimension omitted Ehlers' per-window length"
    " normalisation (N1,N2 over half-length; N3 over full length), which shifts D"
    " and therefore alpha. Implemented per Ehlers.",
)


def _out(values: np.ndarray, index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index, dtype=float)


def causal_laplace_filter(series: pd.Series, s: float = 0.2) -> pd.Series:
    """Plain EMA in DSP clothing: alpha = 1 - exp(-s), s = decay rate.

    Included for completeness -- it is mathematically identical to
    `series.ewm(alpha=1-exp(-s), adjust=False).mean()`. Use pandas instead.
    """
    return series.ewm(alpha=1.0 - np.exp(-s), adjust=False).mean()


def _recurse(x: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """y[t] = y[t-1] + alpha[t] * (x[t] - y[t-1]), y[0] = x[0]."""
    y = np.empty_like(x)
    y[0] = x[0]
    for t in range(1, len(x)):
        y[t] = y[t - 1] + alpha[t] * (x[t] - y[t - 1])
    return y


def na_ema(
    series: pd.Series,
    base_span: int = 10,
    vol_window: int = 20,
    alpha_min: float = 0.01,
    alpha_max: float = 0.5,
) -> pd.Series:
    """Noise-adaptive EMA: alpha scales with realised vol vs its own history.

    High vol -> larger alpha -> faster response. Note this is the OPPOSITE of a
    noise filter: it speeds up when the series is noisiest. The article's stated
    rationale is that a vol expansion carries information; whether that holds is
    an empirical question, not a given.
    """
    alpha_base = 2.0 / (base_span + 1.0)
    sigma = series.rolling(vol_window).std()
    # FIX: expanding, not full-sample, median -- the reference must be causal.
    sigma_ref = sigma.expanding(min_periods=vol_window).median()
    ratio = (sigma / sigma_ref).to_numpy()
    alpha = np.where(np.isfinite(ratio), alpha_base * ratio, alpha_base)
    # FIX: two-sided clamp. Upper-only lets a vol spike degrade to passthrough.
    alpha = np.clip(alpha, alpha_min, alpha_max)
    return _out(_recurse(series.to_numpy(dtype=float), alpha), series.index)


def snr_ema(
    series: pd.Series,
    fast_span: int = 10,
    slow_span: int = 50,
    noise_window: int = 20,
    alpha_min: float = 0.05,
    alpha_max: float = 0.6,
) -> pd.Series:
    """Signal-to-noise adaptive EMA.

    signal = |EMA_fast - EMA_slow| (trend displacement)
    noise  = rolling std of first differences
    alpha  = alpha_min + (alpha_max-alpha_min) * snr/(snr+1), a saturating map.

    Reacts fast when displacement dominates noise; smooths hard in chop.
    """
    ema_fast = series.ewm(span=fast_span, adjust=False).mean()
    ema_slow = series.ewm(span=slow_span, adjust=False).mean()
    signal = (ema_fast - ema_slow).abs()
    noise = series.diff().rolling(noise_window).std()
    snr = (signal / noise).to_numpy()
    alpha = alpha_min + (alpha_max - alpha_min) * (snr / (snr + 1.0))
    # FIX: warmup falls back to the midpoint instead of backfilling future noise.
    alpha = np.where(np.isfinite(alpha), alpha, (alpha_min + alpha_max) / 2.0)
    alpha = np.clip(alpha, alpha_min, alpha_max)
    return _out(_recurse(series.to_numpy(dtype=float), alpha), series.index)


def kama(series: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive Moving Average.

    Efficiency Ratio ER = |P[t]-P[t-n]| / sum(|dP|) over the same window: net
    displacement divided by path length. ER->1 is a clean trend, ER->0 is chop.
    The smoothing constant is (ER*(fast_sc-slow_sc)+slow_sc)**2 -- the square is
    Kaufman's, and it is what makes KAMA sit near-frozen in chop.

    The most defensible variant in the catalog: one parameter-free measurement
    (ER) drives alpha, and the measurement is scale-invariant.
    """
    price = series.to_numpy(dtype=float)
    fastest_sc = 2.0 / (fast + 1.0)
    slowest_sc = 2.0 / (slow + 1.0)
    out = np.empty_like(price)
    out[0] = price[0]
    for t in range(1, len(price)):
        if t < n:
            out[t] = price[t]
            continue
        change = abs(price[t] - price[t - n])
        path = np.abs(np.diff(price[t - n : t + 1])).sum()
        er = change / path if path > 0 else 0.0
        sc = (er * (fastest_sc - slowest_sc) + slowest_sc) ** 2
        out[t] = out[t - 1] + sc * (price[t] - out[t - 1])
    return _out(out, series.index)


def frama(
    series: pd.Series,
    window: int = 64,
    alpha_min: float = 0.01,
    alpha_max: float = 0.2,
) -> pd.Series:
    """Fractal Adaptive Moving Average (Ehlers).

    Estimates the price path's fractal dimension D in [1,2] from the range of
    the two window halves vs the whole. D~1 is a straight line (trend) -> fast;
    D~2 space-filling (chop) -> slow. alpha = exp(-4.6*(D-1)).

    `window` should be even; an odd window splits unevenly and biases D.
    """
    price = series.to_numpy(dtype=float)
    out = np.empty_like(price)
    out[0] = price[0]
    for t in range(1, len(price)):
        w = price[max(0, t - window + 1) : t + 1]
        half = len(w) // 2
        if half < 1:
            out[t] = out[t - 1] + alpha_max * (price[t] - out[t - 1])
            continue
        # FIX: Ehlers normalises each range by its own segment length.
        n1 = (w[:half].max() - w[:half].min()) / half
        n2 = (w[half:].max() - w[half:].min()) / (len(w) - half)
        n3 = (w.max() - w.min()) / len(w)
        if n1 <= 0 or n2 <= 0 or n3 <= 0:
            out[t] = out[t - 1] + alpha_min * (price[t] - out[t - 1])
            continue
        d = float(np.clip((np.log(n1 + n2) - np.log(n3)) / np.log(2.0), 1.0, 2.0))
        alpha = float(np.clip(np.exp(-4.6 * (d - 1.0)), alpha_min, alpha_max))
        out[t] = out[t - 1] + alpha * (price[t] - out[t - 1])
    return _out(out, series.index)


def volume_adaptive_ema(
    price: pd.Series,
    volume: pd.Series,
    base_span: int = 10,
    vol_span: int = 30,
    alpha_min: float = 0.01,
    alpha_max: float = 0.5,
    gamma: float = 1.0,
) -> pd.Series:
    """Volume-adaptive EMA: alpha scales with volume vs its own EMA baseline.

    Premise: a move on heavy volume is more informative, so track it faster.
    `gamma` is the sensitivity exponent (1.0 = linear in relative volume).
    """
    p = price.to_numpy(dtype=float)
    v = volume.to_numpy(dtype=float)
    alpha_0 = 2.0 / (base_span + 1.0)
    # Causal volume baseline; ewm is the same recursion, just vectorised.
    vol_ema = volume.ewm(span=vol_span, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(vol_ema > 0, v / vol_ema, 1.0)
    alpha = np.clip(alpha_0 * np.power(rel, gamma), alpha_min, alpha_max)
    return _out(_recurse(p, alpha), price.index)


def kalman_ema(
    price: pd.Series, q: float = 1e-5, r: float = 1e-3
) -> tuple[pd.Series, pd.Series]:
    """Scalar Kalman filter on a random-walk state; returns (estimate, gain).

    The Kalman gain K[t] IS the adaptive alpha -- this is the principled member
    of the family: alpha falls out of an explicit noise model rather than a
    hand-tuned map. Caveat: with constant q and r the gain converges to a fixed
    point within ~50 steps, so steady-state Kalman == a plain EMA. It is only
    genuinely adaptive if q or r is made state-dependent (e.g. r from realised
    vol), which the source article does not do.
    """
    x = price.to_numpy(dtype=float)
    n = len(x)
    est = np.empty(n)
    gain = np.zeros(n)
    est[0] = x[0]
    p_cov = 1.0
    for t in range(1, n):
        p_pred = p_cov + q
        k = p_pred / (p_pred + r)
        gain[t] = k
        est[t] = est[t - 1] + k * (x[t] - est[t - 1])
        p_cov = (1.0 - k) * p_pred
    return _out(est, price.index), _out(gain, price.index)


def _self_check() -> None:
    """Invariant-based checks -- no price fixture needed, so no fabricated data.

    Three properties every causal smoother in this module must satisfy:
      1. Fixed point: a constant series smooths to that constant.
      2. Boundedness: output never leaves the input's [min, max] envelope
         (true for any convex update with alpha in [0,1]).
      3. Causality: mutating the tail of the input leaves the head unchanged.
    """
    idx = pd.RangeIndex(200)
    const = pd.Series(np.full(200, 42.0), index=idx)
    # A deterministic zig-zag + ramp: exercises both trend and chop branches.
    t = np.arange(200, dtype=float)
    zig = pd.Series(100.0 + 0.05 * t + np.where(t % 2 == 0, 1.0, -1.0), index=idx)
    vol = pd.Series(1_000_000.0 + 500_000.0 * (t % 5), index=idx)

    unary = {
        "causal_laplace_filter": causal_laplace_filter,
        "na_ema": na_ema,
        "snr_ema": snr_ema,
        "kama": kama,
        "frama": frama,
        "volume_adaptive_ema": lambda s: volume_adaptive_ema(s, vol),
        "kalman_ema": lambda s: kalman_ema(s)[0],
    }

    for name, fn in unary.items():
        # 1. fixed point
        got = fn(const)
        assert np.allclose(got.to_numpy(), 42.0), f"{name}: not a fixed point"

        # 2. boundedness
        out = fn(zig).to_numpy()
        assert np.isfinite(out).all(), f"{name}: produced non-finite values"
        lo, hi = zig.min(), zig.max()
        assert out.min() >= lo - 1e-9 and out.max() <= hi + 1e-9, (
            f"{name}: escaped input envelope"
        )

        # 3. causality -- blow up the last 50 points, head must be identical
        tampered = zig.copy()
        tampered.iloc[150:] *= 3.0
        assert np.allclose(out[:150], fn(tampered).to_numpy()[:150]), (
            f"{name}: LOOKAHEAD -- future values changed the past"
        )

    # KAMA-specific: the whole claim is that alpha rises with the efficiency
    # ratio. Measure the realised alpha directly by inverting the update --
    # alpha[t] = (y[t]-y[t-1]) / (x[t]-y[t-1]) -- rather than using a
    # distance-to-price proxy (that proxy is capped at 1.0 for a bounded chop
    # series, so it cannot discriminate).
    ramp = pd.Series(100.0 + 0.5 * t, index=idx)
    chop = pd.Series(100.0 + np.where(t % 2 == 0, 5.0, -5.0), index=idx)

    def _implied_alpha(x: pd.Series) -> float:
        y = kama(x).to_numpy()
        gap = x.to_numpy()[1:] - y[:-1]
        step = y[1:] - y[:-1]
        live = np.abs(gap) > 1e-9
        return float(np.mean((step[live] / gap[live])[99:]))

    a_ramp, a_chop = _implied_alpha(ramp), _implied_alpha(chop)
    assert a_ramp > a_chop * 5, (
        f"kama: not adapting -- trend alpha {a_ramp:.4f} should dominate "
        f"chop alpha {a_chop:.4f}"
    )

    print(f"ok: {len(unary)} filters pass fixed-point, envelope, and causality")
    print(f"    kama realised alpha: trend {a_ramp:.4f} >> chop {a_chop:.4f}")
    print(
        f"    catalog incomplete by ~10 -- see NOT_IMPLEMENTED ({len(NOT_IMPLEMENTED)} entries)"
    )


if __name__ == "__main__":
    _self_check()
