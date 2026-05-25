"""Volatility-Credit Gap (VCG) — pure scoring functions.

Ported from xenon/src/xenon/scanners/vcg.py. The xenon scanner combines data
fetching (IB/UW/Yahoo) with math; this module is just the math. No DB, no
network. Inputs are np.ndarrays of aligned daily closes; output is a payload
dict shaped for the API contract.

Model:
    Δlog(credit_t) = α + β1·Δlog(VVIX_t) + β2·Δlog(VIX_t) + ε_t

Rolling 21-day OLS produces residuals; standardising residuals over 63 days
gives the VCG z-score. A panic-adjusted variant suppresses the signal when
VIX is already crashing (π = clamp((VIX-40)/8, 0, 1) damps the signal).

Strategy reference: xenon docs/VCG_institutional_research_note.md.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# Composite scoring contract version.
# v1: as-ported from xenon/src/xenon/scanners/vcg.py at commit d3cbc08.
#     OLS_WINDOW=21, Z_WINDOW=63, VCG_TRIGGER=2.0, VCG_RO_TRIGGER=2.5,
#     BOUNCE_TRIGGER=-3.5, VIX_FLOOR=28, VIX_EDR=25, VIX_PANIC_LOW=40,
#     VIX_PANIC_HIGH=48, VVIX_ELEVATED=100, VVIX_EXTREME=120.
#     Calibration NOT re-derived in this repo — see vcg-methodology.md §3.
# Bump in lockstep with any threshold change above.
COMPOSITE_VERSION = 1

# ── windows ───────────────────────────────────────────────────────
OLS_WINDOW = 21  # Rolling regression window (business days)
Z_WINDOW = 63  # Residual standardisation lookback
MIN_BARS = OLS_WINDOW + Z_WINDOW + 10  # Floor for a meaningful scan

# ── thresholds (mirror xenon constants exactly) ──────────────────
VIX_PANIC_LOW = 40.0  # π clamp lower bound
VIX_PANIC_HIGH = 48.0  # π clamp upper bound
VIX_FLOOR = 28.0  # RO gate: VIX must exceed this
VIX_EDR = 25.0  # EDR watch gate
VCG_TRIGGER = 2.0  # EDR / Watch threshold
VCG_RO_TRIGGER = 2.5  # Risk-Off threshold
BOUNCE_TRIGGER = -3.5  # Counter-signal (tactical long)
VVIX_EXTREME = 120.0  # VVIX amplifier: extreme
VVIX_ELEVATED = 100.0  # VVIX amplifier: elevated (below = moderate)


# ══════════════════════════════════════════════════════════════════
# Math primitives
# ══════════════════════════════════════════════════════════════════


def log_returns(prices: np.ndarray) -> np.ndarray:
    """ln(P_t / P_{t-1}). Returns has length N-1.

    Non-finite / non-positive inputs (NaN, Inf, 0, negative) propagate as NaN
    rather than Inf — protects downstream OLS and JSONB persistence from a
    bad parquet row leaking into the model.
    """
    arr = np.asarray(prices, dtype=float)
    bad = ~(np.isfinite(arr) & (arr > 0))
    safe = np.where(bad, np.nan, arr)
    return np.log(safe[1:] / safe[:-1])


def rolling_ols(
    y: np.ndarray, X: np.ndarray, window: int = OLS_WINDOW
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Rolling OLS: y = α + β₁·X[:,0] + β₂·X[:,1] + ε.

    Returns aligned arrays (alpha, beta1, beta2, residual) where indices
    [0, window-2] are NaN (insufficient history).
    """
    n = len(y)
    alphas = np.full(n, np.nan)
    beta1s = np.full(n, np.nan)
    beta2s = np.full(n, np.nan)
    residuals = np.full(n, np.nan)

    for t in range(window - 1, n):
        start = t - window + 1
        y_w = y[start : t + 1]
        X_w = X[start : t + 1]
        # np.linalg.lstsq does not raise on collinear / rank-deficient windows;
        # it silently returns a reduced-rank solution with meaningless betas
        # that would still drive sign_ok/ro. Skip windows where any input is
        # non-finite or the design matrix is not full-rank.
        if not (np.isfinite(y_w).all() and np.isfinite(X_w).all()):
            continue
        A = np.column_stack([np.ones(window), X_w])
        try:
            coeff, _, rank, _ = np.linalg.lstsq(A, y_w, rcond=None)
        except np.linalg.LinAlgError as exc:
            _ = repr(exc)  # CI Guardrail 2: window silently dropped, OLS will skip
            continue
        if rank < A.shape[1]:
            continue
        alphas[t] = coeff[0]
        beta1s[t] = coeff[1]
        beta2s[t] = coeff[2]
        y_hat = A @ coeff
        residuals[t] = y_w[-1] - y_hat[-1]
    return alphas, beta1s, beta2s, residuals


def standardise_residuals(residuals: np.ndarray, window: int = Z_WINDOW) -> np.ndarray:
    """Trailing z-score of residuals."""
    n = len(residuals)
    z = np.full(n, np.nan)
    for t in range(window - 1, n):
        start = t - window + 1
        chunk = residuals[start : t + 1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) < 10:
            continue
        mu = float(np.mean(valid))
        sigma = float(np.std(valid, ddof=1))
        if sigma < 1e-12:
            continue
        z[t] = (residuals[t] - mu) / sigma
    return z


def compute_vcg(
    vix_prices: np.ndarray,
    vvix_prices: np.ndarray,
    credit_prices: np.ndarray,
) -> dict[str, np.ndarray]:
    """Full VCG model. Returns dict of per-day arrays (length = N-1)."""
    vix_ret = log_returns(vix_prices)
    vvix_ret = log_returns(vvix_prices)
    credit_ret = log_returns(credit_prices)

    X = np.column_stack([vvix_ret, vix_ret])
    alphas, beta1s, beta2s, residuals = rolling_ols(credit_ret, X, OLS_WINDOW)
    vcg = standardise_residuals(residuals, Z_WINDOW)

    vix_levels = vix_prices[1:]
    pi = np.clip(
        (vix_levels - VIX_PANIC_LOW) / (VIX_PANIC_HIGH - VIX_PANIC_LOW), 0.0, 1.0
    )
    vcg_div = (1.0 - pi) * vcg

    return {
        "vcg": vcg,
        "vcg_adj": vcg_div,
        "residuals": residuals,
        "alpha": alphas,
        "beta1": beta1s,
        "beta2": beta2s,
        "vix_ret": vix_ret,
        "vvix_ret": vvix_ret,
        "credit_ret": credit_ret,
        "vix_levels": vix_levels,
        "vvix_levels": vvix_prices[1:],
        "credit_levels": credit_prices[1:],
        "pi": pi,
    }


# ══════════════════════════════════════════════════════════════════
# Signal evaluation
# ══════════════════════════════════════════════════════════════════


def _vvix_severity(vvix: float) -> str:
    if vvix > VVIX_EXTREME:
        return "extreme"
    if vvix >= VVIX_ELEVATED:
        return "elevated"
    return "moderate"


def _round_or_none(value: float, ndigits: int) -> float | None:
    if math.isnan(value):
        return None
    return round(float(value), ndigits)


def _signal_for_index(
    model: dict[str, np.ndarray],
    idx: int,
    *,
    vix_floor: float = VIX_FLOOR,
    vcg_trigger: float = VCG_RO_TRIGGER,
) -> dict[str, Any]:
    """Evaluate ro/edr/tier/bounce/sign_ok for a single index.

    Gates compare against panic-adjusted ``vcg_adj`` rather than raw ``vcg`` —
    when π → 1 (VIX ≥ 48) vcg_adj → 0, so ro/edr/tier/bounce naturally fall
    to zero. Without this, a VIX-50 day persists regime="PANIC" alongside
    ro=1/tier=1 and the UI renders the RISK-OFF badge atop the PANIC label.
    Bounce additionally requires sign discipline (β₁,β₂ ≤ 0); a contrarian
    long signal is not actionable when the model's correlation signs flip.
    """
    vcg_eff = float(model["vcg_adj"][idx])
    beta1 = float(model["beta1"][idx])
    beta2 = float(model["beta2"][idx])
    vix = float(model["vix_levels"][idx])

    sign_ok = (
        not math.isnan(beta1) and beta1 <= 0 and not math.isnan(beta2) and beta2 <= 0
    )

    ro = bool(
        not math.isnan(vcg_eff)
        and vix > vix_floor
        and vcg_eff > vcg_trigger
        and sign_ok
    )
    edr = bool(
        not math.isnan(vcg_eff) and vix > VIX_EDR and vcg_eff > VCG_TRIGGER and sign_ok
    )
    tier: int | None = None
    if ro:
        tier = 1 if vix > 30.0 else 2
    elif edr:
        tier = 3
    bounce = bool(not math.isnan(vcg_eff) and vcg_eff < BOUNCE_TRIGGER and sign_ok)
    return {
        "ro": int(ro),
        "edr": int(edr),
        "tier": tier,
        "bounce": int(bounce),
        "sign_ok": bool(sign_ok),
    }


def _interpretation_for_index(
    model: dict[str, np.ndarray],
    idx: int,
    *,
    vix_floor: float = VIX_FLOOR,
    vcg_trigger: float = VCG_RO_TRIGGER,
) -> dict[str, Any]:
    """Build the interpretation payload for an arbitrary index.

    Returns the same dict as evaluate_signal MINUS credit_5d_return_pct
    (which depends on credit_prices, not the model). The backtest script
    in scripts/backtest_vcg.py calls this once per aligned trading day to
    reproduce the live-signal logic against historical bars.
    """
    flags = _signal_for_index(model, idx, vix_floor=vix_floor, vcg_trigger=vcg_trigger)

    vcg_val = float(model["vcg"][idx])
    vcg_adj_val = float(model["vcg_adj"][idx])
    beta1 = float(model["beta1"][idx])
    beta2 = float(model["beta2"][idx])
    alpha = float(model["alpha"][idx])
    vix = float(model["vix_levels"][idx])
    vvix = float(model["vvix_levels"][idx])
    credit = float(model["credit_levels"][idx])
    residual = float(model["residuals"][idx])
    pi_val = float(model["pi"][idx])

    sign_suppressed = not flags["sign_ok"]
    vvix_sev = _vvix_severity(vvix)

    # Attribution split
    vvix_component = (
        beta1 * float(model["vvix_ret"][idx]) if not math.isnan(beta1) else 0.0
    )
    vix_component = (
        beta2 * float(model["vix_ret"][idx]) if not math.isnan(beta2) else 0.0
    )
    model_implied = (
        alpha + vvix_component + vix_component if not math.isnan(alpha) else 0.0
    )
    total_component = (
        abs(vvix_component) + abs(vix_component)
        if (abs(vvix_component) + abs(vix_component)) > 1e-12
        else 1.0
    )
    vvix_pct = abs(vvix_component) / total_component * 100.0
    vix_pct = abs(vix_component) / total_component * 100.0

    # Regime label
    if pi_val >= 1.0:
        regime = "PANIC"
    elif pi_val > 0.0:
        regime = "TRANSITION"
    else:
        regime = "DIVERGENCE"

    # Interpretation
    if math.isnan(vcg_val):
        interpretation = "INSUFFICIENT_DATA"
    elif not flags["sign_ok"]:
        interpretation = "SUPPRESSED"
    elif pi_val >= 1.0:
        interpretation = "PANIC"
    elif flags["ro"]:
        interpretation = "RISK_OFF"
    elif flags["edr"]:
        interpretation = "EDR"
    elif flags["bounce"]:
        interpretation = "BOUNCE"
    elif not math.isnan(vcg_adj_val) and vcg_adj_val > VCG_TRIGGER:
        interpretation = "WATCH"
    else:
        interpretation = "NORMAL"

    return {
        "vcg": _round_or_none(vcg_val, 4),
        "vcg_adj": _round_or_none(vcg_adj_val, 4),
        "residual": _round_or_none(residual, 6),
        "beta1_vvix": _round_or_none(beta1, 6),
        "beta2_vix": _round_or_none(beta2, 6),
        "alpha": _round_or_none(alpha, 6),
        "vix": round(vix, 2),
        "vvix": round(vvix, 2),
        "credit_price": round(credit, 2),
        "ro": flags["ro"],
        "edr": flags["edr"],
        "tier": flags["tier"],
        "bounce": flags["bounce"],
        "vvix_severity": vvix_sev,
        "sign_ok": bool(flags["sign_ok"]),
        "sign_suppressed": bool(sign_suppressed),
        "pi_panic": round(pi_val, 4),
        "regime": regime,
        "interpretation": interpretation,
        "attribution": {
            "vvix_pct": round(vvix_pct, 1),
            "vix_pct": round(vix_pct, 1),
            "vvix_component": round(vvix_component, 6),
            "vix_component": round(vix_component, 6),
            "model_implied": round(model_implied, 6),
        },
    }


def evaluate_signal(
    model: dict[str, np.ndarray],
    credit_prices: np.ndarray,
    *,
    vix_floor: float = VIX_FLOOR,
    vcg_trigger: float = VCG_RO_TRIGGER,
) -> dict[str, Any]:
    """Build the latest-bar signal payload.

    Thin wrapper over _interpretation_for_index that adds the 5-day credit
    return (depends on credit_prices, not the model).
    """
    payload = _interpretation_for_index(
        model, -1, vix_floor=vix_floor, vcg_trigger=vcg_trigger
    )
    if len(credit_prices) >= 6:
        credit_5d_ret = (credit_prices[-1] / credit_prices[-6]) - 1.0
    else:
        credit_5d_ret = 0.0
    payload["credit_5d_return_pct"] = round(credit_5d_ret * 100.0, 3)
    return payload


def _history_row(
    model: dict[str, np.ndarray],
    i: int,
    date_iso: str,
    *,
    vix_floor: float,
    vcg_trigger: float,
) -> dict[str, Any]:
    flags = _signal_for_index(model, i, vix_floor=vix_floor, vcg_trigger=vcg_trigger)
    return {
        "date": date_iso,
        "residual": _round_or_none(float(model["residuals"][i]), 6),
        "vcg": _round_or_none(float(model["vcg"][i]), 4),
        "vcg_adj": _round_or_none(float(model["vcg_adj"][i]), 4),
        "beta1": _round_or_none(float(model["beta1"][i]), 6),
        "beta2": _round_or_none(float(model["beta2"][i]), 6),
        "vix": round(float(model["vix_levels"][i]), 2),
        "vvix": round(float(model["vvix_levels"][i]), 2),
        "credit": round(float(model["credit_levels"][i]), 2),
        "ro": flags["ro"],
        "edr": flags["edr"],
        "tier": flags["tier"],
        "bounce": flags["bounce"],
    }


# ══════════════════════════════════════════════════════════════════
# Orchestrator (pure)
# ══════════════════════════════════════════════════════════════════


def run_analysis(
    aligned: dict[str, np.ndarray],
    common_dates: list[str],
    *,
    proxy: str = "HYG",
    vix_floor: float = VIX_FLOOR,
    vcg_trigger: float = VCG_RO_TRIGGER,
) -> dict[str, Any]:
    """Compute the full VCG snapshot from aligned daily closes.

    Required keys in ``aligned``: VIX, VVIX, <proxy>. All arrays must be the
    same length and aligned to ``common_dates``.
    """
    vix_prices = aligned["VIX"]
    vvix_prices = aligned["VVIX"]
    credit_prices = aligned[proxy]

    model = compute_vcg(vix_prices, vvix_prices, credit_prices)
    signal = evaluate_signal(
        model, credit_prices, vix_floor=vix_floor, vcg_trigger=vcg_trigger
    )

    # Last 20 sessions of history. Returns are length N-1 of common_dates,
    # so date index = i + 1.
    n = len(model["residuals"])
    history: list[dict[str, Any]] = []
    for i in range(max(0, n - 20), n):
        date_idx = i + 1
        date_iso = common_dates[date_idx] if date_idx < len(common_dates) else None
        if date_iso is None:
            continue
        history.append(
            _history_row(
                model, i, date_iso, vix_floor=vix_floor, vcg_trigger=vcg_trigger
            )
        )

    return {
        "date": common_dates[-1],
        "credit_proxy": proxy,
        "signal": signal,
        "history": history,
    }
