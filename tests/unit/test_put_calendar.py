"""Money-path checks for the two-expiry put-calendar engine.

Inputs here are deterministic unit-test fixtures (test doubles), not market
data — they exercise the pricing/settlement mechanics, not a market claim.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from uw_scan.reports.put_calendar import (
    CalendarConfig,
    long_put_mark,
    simulate,
    skew_bump,
)
from uw_scan.reports.vrp_structure import CostModel

CFG = CalendarConfig(front_dte=1, long_dte=30, short_delta=0.20, mode="calendar")
COST = CostModel(per_contract=1.0, slippage_frac=0.01, slippage_min=0.01)


def test_skew_bump_only_lifts_otm_puts():
    assert skew_bump(1.0, 0.5) == 1.0  # ATM: no bump
    assert skew_bump(1.2, 0.5) == 1.0  # ITM put (K>S): no bump
    assert skew_bump(0.9, 0.5) == pytest.approx(1.05)  # 10% OTM → +5%


def test_long_put_covers_any_lower_short_strike():
    # Defined-risk invariant: a longer-dated put struck at/above the short
    # strike covers the short's cash-settled intrinsic — up to a small
    # European interest-carry term K_long*(1-e^{-rT}) on the discounted strike.
    # That carry (cents at these rates/tenors) is the only "gap", not a naked
    # blowup: max loss stays ≈ debit + carry. We assert the correct bound.
    K_long, rvx, resid = 195.0, 0.22, 20
    carry = K_long * (1.0 - math.exp(-CFG.r * resid / 252.0))
    for S_settle in (250, 220, 200, 195, 180, 150, 120):
        for K_short in (195.0, 190.0, 175.0):  # all <= K_long
            long_val = long_put_mark(S_settle, K_long, resid, CFG, rvx)
            short_intrinsic = max(K_short - S_settle, 0.0)
            assert long_val >= short_intrinsic - carry - 1e-9, (S_settle, K_short)


def test_bs_long_put_decays_as_residual_shrinks():
    # Same spot/vol, less time → less extrinsic value (no dividends here).
    S, K, rvx = 200.0, 190.0, 0.25
    v30 = long_put_mark(S, K, 30, CFG, rvx)
    v5 = long_put_mark(S, K, 5, CFG, rvx)
    assert v30 > v5 > 0


def _flat_then_drop_loaded(n: int = 40, drop_day: int = 20):
    """Spot flat at 200 then a one-day -8% gap, RVX flat at 22%."""
    d0 = date(2024, 1, 2)
    dates = [d0 + timedelta(days=k) for k in range(n)]
    spots = [200.0] * n
    for k in range(drop_day, n):
        spots[k] = 184.0  # -8% step that persists
    adj = list(zip(dates, spots, strict=True))
    rows = [{"market_date": d, "iv": 0.22} for d in dates]
    return SimpleNamespace(adj=adj, rows=rows)


def test_simulate_runs_and_reports_finite_sharpe():
    loaded = _flat_then_drop_loaded()
    m = simulate(loaded, CalendarConfig(front_vol_mult=1.2), COST)
    assert m["n_days"] > 0
    assert m["sharpe"] is not None and math.isfinite(m["sharpe"])
    assert m["short_itm_rate"] is not None


def test_decoupled_mode_runs_and_legs_sum_to_combined():
    # Iteration 2: decoupled long-held put + independent short roll. The per-leg
    # decomposition must reconcile — short total + long total == combined total.
    loaded = _flat_then_drop_loaded(n=60, drop_day=30)
    m = simulate(
        loaded,
        CalendarConfig(
            mode="decoupled", long_dte=45, min_residual_days=21, front_vol_mult=1.2
        ),
        COST,
    )
    assert m["n_days"] > 0
    combined_total = sum(m["daily_ret"])
    assert m["short_leg_total"] + m["long_leg_total"] == pytest.approx(combined_total)


def test_richer_front_vol_raises_the_premium_collected():
    # The edge lever, isolated at a FIXED strike: a higher front_vol_mult must
    # price the daily short richer. (In the full sim the strike re-anchors with
    # vol, so we test the premium directly here.)
    from uw_scan.reports.put_calendar import _write_short

    S, rvx, K_long = 200.0, 0.22, 197.0
    _, prem_cheap = _write_short(S, rvx, K_long, CalendarConfig(front_vol_mult=0.7))
    _, prem_rich = _write_short(S, rvx, K_long, CalendarConfig(front_vol_mult=1.4))
    assert prem_rich > prem_cheap > 0
