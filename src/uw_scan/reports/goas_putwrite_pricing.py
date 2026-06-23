"""Parametric downside-skew layer over the flat-vol BS primitives.

A put held to expiry settles at intrinsic (vol-independent), so skew changes only
(a) the strike chosen for a target delta, (b) the entry credit, and (c) the daily
mark-to-market of open positions — the expiry SETTLEMENT and realized P&L stay
model-free. The historical skew SHAPE here is MODELED (calibrated to one recent
GOAS quote), not observed: no multi-year IV surface exists on our data.
Design: docs/superpowers/specs/2026-06-23-goas-putwrite-delta-sweep-design.md
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

from uw_scan.reports.vrp_structure import (
    CashSecuredPut,
    bs_delta,
    bs_price,
    build_cash_secured_put,
)

log = logging.getLogger(__name__)

# GOAS published quote (illustrative option price table, as of 2026-05-05): SPDR
# S&P 500 ETF, 1-month ~15%-exercise-probability put → strike 96.2% of spot,
# premium 0.7% of spot. Used to calibrate the skew slope.
GOAS_AS_OF = date(2026, 5, 5)
GOAS_STRIKE_FRAC = 0.962
GOAS_PREMIUM_FRAC = 0.007
GOAS_DTE_DAYS = 21  # GOAS "1 month" ≈ 21 trading days; dte_days are trading-day offsets


@dataclass(frozen=True)
class PutSkew:
    """Downside vol skew: iv(K) = atm·(1 − slope·ln(K/S)). For a put strike below
    spot, ln(K/S) < 0, so a positive slope RAISES iv as strikes fall (the observed
    index shape). slope=0 ⇒ flat-vol."""

    slope: float

    def iv(self, atm_sigma: float, S: float, K: float) -> float:
        return atm_sigma * (1.0 - self.slope * math.log(K / S))


def build_csp_skew(
    S: float,
    atm_sigma: float,
    T: float,
    r: float,
    *,
    short_delta: float,
    skew: PutSkew | None,
) -> CashSecuredPut:
    """Cash-secured put at the delta-consistent strike under `skew`. When skew is
    None, delegates to the flat-vol builder. The put delta magnitude N(−d1)
    decreases monotonically as K falls (for the calibrated-slope regime), so a
    bisection on K ∈ (0, S) converges."""
    if skew is None:
        return build_cash_secured_put(S, atm_sigma, T, r, short_delta=short_delta)
    if S <= 0 or atm_sigma <= 0 or T <= 0:
        raise ValueError(
            f"build_csp_skew needs S,atm_sigma,T > 0 (got {S},{atm_sigma},{T})"
        )
    if not (0.0 < short_delta < 0.5):
        raise ValueError("require 0 < short_delta < 0.5")
    lo, hi = 1e-9 * S, S
    # admissible-delta guard: max attainable |put delta| is near K=S; a target at/above
    # it cannot be bracketed in (0, S) and bisection would converge to K≈S (a wrong
    # strike). Raise so the caller skips this entry rather than mis-pricing it.
    k_atm = S * (1.0 - 1e-9)
    dmag_max = -bs_delta(S, k_atm, T, r, skew.iv(atm_sigma, S, k_atm), is_call=False)
    if short_delta >= dmag_max:
        raise ValueError(
            f"short_delta {short_delta} >= max attainable |put delta| {dmag_max:.3f} "
            "at this tenor/vol — not bracketable in (0, S)"
        )
    k = 0.5 * (lo + hi)
    for _ in range(200):
        k = 0.5 * (lo + hi)
        iv_k = skew.iv(atm_sigma, S, k)
        if iv_k <= 0:
            lo = k  # iv blew up at very low strike; push up
            continue
        dmag = -bs_delta(S, k, T, r, iv_k, is_call=False)  # |put delta| ∈ (0, 0.5)
        if dmag > short_delta:  # strike too close to money → lower the ceiling
            hi = k
        else:
            lo = k
        if hi - lo < 1e-9 * S:
            break
    iv_k = skew.iv(atm_sigma, S, k)
    recovered = -bs_delta(
        S, k, T, r, iv_k, is_call=False
    )  # |put delta| at solved strike
    if abs(recovered - short_delta) > 1e-3:
        # |put delta| can be non-monotone in K when IV depends on K (steep skew);
        # surface it loudly rather than silently mis-pricing the whole sweep.
        log.warning(
            "build_csp_skew non-convergent: target Δ=%.3f recovered Δ=%.3f K=%.2f slope=%.3f",
            short_delta,
            recovered,
            k,
            skew.slope,
        )
    credit = bs_price(S, k, T, r, iv_k, is_call=False)
    return CashSecuredPut(k, credit, k - credit, (credit,))


def calibrate_skew(
    S: float,
    atm_sigma: float,
    T: float,
    r: float,
    *,
    target_strike_frac: float,
    target_premium_frac: float,
) -> PutSkew:
    """Solve the skew `slope` so a put struck at target_strike_frac·S prices to
    target_premium_frac·S at the given ATM σ. One equation, one unknown — premium
    rises monotonically with slope (higher downside IV). If flat-vol (slope=0)
    already exceeds the target, returns slope=0 and logs it; if the target is
    unreachable within slope≤10, logs a non-convergence warning."""
    if S <= 0 or atm_sigma <= 0 or T <= 0:
        raise ValueError("calibrate_skew needs S,atm_sigma,T > 0")
    k_star = target_strike_frac * S
    target_prem = target_premium_frac * S
    flat_prem = bs_price(S, k_star, T, r, atm_sigma, is_call=False)
    if flat_prem >= target_prem:
        log.info(
            "calibrate_skew: flat-vol premium %.4f already ≥ target %.4f → slope=0",
            flat_prem,
            target_prem,
        )
        return PutSkew(slope=0.0)
    lo, hi = 0.0, 10.0
    slope = 0.5 * (lo + hi)
    for _ in range(200):
        slope = 0.5 * (lo + hi)
        iv_k = atm_sigma * (1.0 - slope * math.log(k_star / S))
        prem = bs_price(S, k_star, T, r, iv_k, is_call=False)
        if prem > target_prem:
            hi = slope
        else:
            lo = slope
        if hi - lo < 1e-9:
            break
    final_iv = atm_sigma * (1.0 - slope * math.log(k_star / S))
    final_prem = bs_price(S, k_star, T, r, final_iv, is_call=False)
    if abs(final_prem - target_prem) > 0.05 * target_prem:
        # target premium unreachable within slope≤10 → calibration did not converge.
        log.warning(
            "calibrate_skew non-convergent: got premium %.4f want %.4f at slope=%.3f",
            final_prem,
            target_prem,
            slope,
        )
    return PutSkew(slope=slope)
