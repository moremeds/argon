"""Pure flat-vol option pricing → defined-risk iron condor → expiry P&L.

No DB, no I/O, no scipy/numpy. N(·) and N⁻¹(·) come from statistics.NormalDist
(Python 3.13 stdlib). FLAT-VOL APPROXIMATION (plan §Global Constraints): all four
legs are priced off a single ATM IV — skew is ignored, so absolute credit is
approximate while the harvest direction (sell rich IV, pay realized RV, truncated
by wings) is faithful. Skew overlay is a v2.

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

_N = NormalDist()  # standard normal; .cdf / .inv_cdf


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_price(
    S: float, K: float, T: float, r: float, sigma: float, *, is_call: bool
) -> float:
    """Black-Scholes premium per share. Degenerate (T<=0 or sigma<=0) → intrinsic."""
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    disc = math.exp(-r * T)
    if is_call:
        return S * _N.cdf(d1) - K * disc * _N.cdf(d2)
    return K * disc * _N.cdf(-d2) - S * _N.cdf(-d1)


def bs_delta(
    S: float, K: float, T: float, r: float, sigma: float, *, is_call: bool
) -> float:
    """Spot delta. Call ∈ (0,1); put ∈ (-1,0)."""
    if T <= 0 or sigma <= 0:
        intrinsic = (S > K) if is_call else (S < K)
        return (1.0 if is_call else -1.0) if intrinsic else 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _N.cdf(d1) if is_call else _N.cdf(d1) - 1.0


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """d²price/dS² (call==put). Degenerate (T<=0 or sigma<=0 or S<=0) → 0."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _N.pdf(d1) / (S * sigma * math.sqrt(T))


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """dprice/dsigma per 1.00 vol (call==put). Divide by 100 for per-1%."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return S * _N.pdf(d1) * math.sqrt(T)


def bs_theta(
    S: float, K: float, T: float, r: float, sigma: float, *, is_call: bool
) -> float:
    """dprice/dt per YEAR (negative for long options). Divide by 365 for per-day."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    term1 = -(S * _N.pdf(d1) * sigma) / (2.0 * math.sqrt(T))
    disc = math.exp(-r * T)
    if is_call:
        return term1 - r * K * disc * _N.cdf(d2)
    return term1 + r * K * disc * _N.cdf(-d2)


def strike_for_delta(
    S: float, T: float, r: float, sigma: float, target_delta: float, *, is_call: bool
) -> float:
    """Invert delta→strike under flat vol. target_delta is the OTM magnitude
    (0<δ<0.5). Call: d1 = N⁻¹(δ); Put: d1 = -N⁻¹(δ). K = S·exp((r+σ²/2)T − d1·σ√T)."""
    d1 = _N.inv_cdf(target_delta)
    if not is_call:
        d1 = -d1
    return S * math.exp((r + 0.5 * sigma * sigma) * T - d1 * sigma * math.sqrt(T))


@dataclass(frozen=True)
class IronCondor:
    short_put: float
    long_put: float
    short_call: float
    long_call: float
    credit: float
    put_width: float
    call_width: float
    max_loss: float
    leg_premiums: tuple[float, float, float, float]  # sp, lp, sc, lc (per share)

    def expiry_pnl(self, S_T: float) -> float:
        return condor_expiry_pnl(self, S_T)

    def breached(self, S_T: float) -> bool:
        return S_T < self.short_put or S_T > self.short_call

    def value(self, S: float, T: float, r: float, sigma: float) -> float:
        """Cost-to-close now (mark). At T<=0 bs_price returns intrinsic, so this
        equals the expiry loss → credit − value(S,0) == expiry_pnl(S)."""
        return (
            bs_price(S, self.short_put, T, r, sigma, is_call=False)
            - bs_price(S, self.long_put, T, r, sigma, is_call=False)
            + bs_price(S, self.short_call, T, r, sigma, is_call=True)
            - bs_price(S, self.long_call, T, r, sigma, is_call=True)
        )


def build_iron_condor(
    S: float, sigma: float, T: float, r: float, *, short_delta: float, wing_delta: float
) -> IronCondor:
    """Symmetric 4-leg condor at the given short/wing deltas, priced flat-vol.
    Guards: positive spot/vol/T and 0 < wing_delta < short_delta < 0.5, else the
    strikes collapse (sigma→0 maps every strike to spot·e^{rT}) or invert."""
    if S <= 0 or sigma <= 0 or T <= 0:
        raise ValueError(f"build_iron_condor needs S,sigma,T > 0 (got {S},{sigma},{T})")
    if not (0.0 < wing_delta < short_delta < 0.5):
        raise ValueError("require 0 < wing_delta < short_delta < 0.5")
    sp = strike_for_delta(S, T, r, sigma, short_delta, is_call=False)
    lp = strike_for_delta(S, T, r, sigma, wing_delta, is_call=False)
    sc = strike_for_delta(S, T, r, sigma, short_delta, is_call=True)
    lc = strike_for_delta(S, T, r, sigma, wing_delta, is_call=True)
    sp_p = bs_price(S, sp, T, r, sigma, is_call=False)
    lp_p = bs_price(S, lp, T, r, sigma, is_call=False)
    sc_p = bs_price(S, sc, T, r, sigma, is_call=True)
    lc_p = bs_price(S, lc, T, r, sigma, is_call=True)
    credit = (sp_p - lp_p) + (sc_p - lc_p)  # short premia minus long premia
    put_width = sp - lp
    call_width = lc - sc
    max_loss = max(put_width, call_width) - credit
    return IronCondor(
        short_put=sp,
        long_put=lp,
        short_call=sc,
        long_call=lc,
        credit=credit,
        put_width=put_width,
        call_width=call_width,
        max_loss=max_loss,
        leg_premiums=(sp_p, lp_p, sc_p, lc_p),
    )


def condor_expiry_pnl(condor: IronCondor, S_T: float) -> float:
    """Per-share gross P&L held to expiry against settlement price S_T:
    credit collected minus the realized loss on whichever spread is breached.
    Each spread loss is capped by its wing → defined risk."""
    put_loss = max(0.0, condor.short_put - S_T) - max(0.0, condor.long_put - S_T)
    call_loss = max(0.0, S_T - condor.short_call) - max(0.0, S_T - condor.long_call)
    return condor.credit - put_loss - call_loss


@dataclass(frozen=True)
class BullPutSpread:
    """Defined-risk bullish short-vol: sell short_put, buy lower long_put. One
    breach side (downside). Capped loss = put_width − credit."""

    short_put: float
    long_put: float
    credit: float
    put_width: float
    max_loss: float
    leg_premiums: tuple[float, float]  # sp, lp (per share)

    def expiry_pnl(self, S_T: float) -> float:
        put_loss = max(0.0, self.short_put - S_T) - max(0.0, self.long_put - S_T)
        return self.credit - put_loss

    def breached(self, S_T: float) -> bool:
        return S_T < self.short_put

    def value(self, S: float, T: float, r: float, sigma: float) -> float:
        return bs_price(S, self.short_put, T, r, sigma, is_call=False) - bs_price(
            S, self.long_put, T, r, sigma, is_call=False
        )


def build_bull_put_spread(
    S: float, sigma: float, T: float, r: float, *, short_delta: float, wing_delta: float
) -> BullPutSpread:
    if S <= 0 or sigma <= 0 or T <= 0:
        raise ValueError(
            f"build_bull_put_spread needs S,sigma,T > 0 (got {S},{sigma},{T})"
        )
    if not (0.0 < wing_delta < short_delta < 0.5):
        raise ValueError("require 0 < wing_delta < short_delta < 0.5")
    sp = strike_for_delta(S, T, r, sigma, short_delta, is_call=False)
    lp = strike_for_delta(S, T, r, sigma, wing_delta, is_call=False)
    sp_p = bs_price(S, sp, T, r, sigma, is_call=False)
    lp_p = bs_price(S, lp, T, r, sigma, is_call=False)
    credit = sp_p - lp_p
    put_width = sp - lp
    return BullPutSpread(sp, lp, credit, put_width, put_width - credit, (sp_p, lp_p))


@dataclass(frozen=True)
class CashSecuredPut:
    """Defined-risk bullish short-vol: sell short_put, hold cash. No wing → more
    credit but loss runs to the strike. Capital at risk = strike·100 (max_loss =
    strike − credit, the assignment-to-zero floor)."""

    short_put: float
    credit: float
    max_loss: float  # short_put − credit (stock assigned and falls to 0)
    leg_premiums: tuple[float]  # (sp,)

    def expiry_pnl(self, S_T: float) -> float:
        return self.credit - max(0.0, self.short_put - S_T)

    def breached(self, S_T: float) -> bool:
        return S_T < self.short_put

    def value(self, S: float, T: float, r: float, sigma: float) -> float:
        return bs_price(S, self.short_put, T, r, sigma, is_call=False)


def build_cash_secured_put(
    S: float, sigma: float, T: float, r: float, *, short_delta: float
) -> CashSecuredPut:
    if S <= 0 or sigma <= 0 or T <= 0:
        raise ValueError(
            f"build_cash_secured_put needs S,sigma,T > 0 (got {S},{sigma},{T})"
        )
    if not (0.0 < short_delta < 0.5):
        raise ValueError("require 0 < short_delta < 0.5")
    sp = strike_for_delta(S, T, r, sigma, short_delta, is_call=False)
    sp_p = bs_price(S, sp, T, r, sigma, is_call=False)
    return CashSecuredPut(sp, sp_p, sp - sp_p, (sp_p,))


@dataclass(frozen=True)
class CostModel:
    per_contract: float  # commission per leg per side
    slippage_frac: float  # half-spread as fraction of leg mid
    slippage_min: float  # half-spread floor per leg (price points)
    round_trip: bool = True
    n_legs: int = 4  # legacy default; commission now scales to len(leg_premiums)
    multiplier: int = 100

    def total(self, leg_premiums: tuple[float, ...], contracts: int) -> float:
        """Dollar cost: per-leg half-spread (max of floor and frac·mid) + commission,
        ×(2 if round_trip)·contracts. Slippage is in price points → ×multiplier.
        Commission scales to the actual leg count (condor=4, put-spread=2, CSP=1)."""
        sides = 2 if self.round_trip else 1
        slip_pts = sum(
            max(self.slippage_min, self.slippage_frac * abs(p)) for p in leg_premiums
        )
        slip_dollars = slip_pts * self.multiplier * contracts * sides
        commission = self.per_contract * len(leg_premiums) * contracts * sides
        return slip_dollars + commission
