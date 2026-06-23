from datetime import date

import pytest

from uw_scan.reports.goas_putwrite_pricing import (
    GOAS_AS_OF,
    GOAS_DTE_DAYS,
    GOAS_PREMIUM_FRAC,
    GOAS_STRIKE_FRAC,
    PutSkew,
    build_csp_skew,
    calibrate_skew,
)
from uw_scan.reports.vrp_structure import bs_delta, bs_price, build_cash_secured_put

# Real frozen fixture — SPY/VIX daily closes as of 2026-05-05, read once from the
# market-warehouse lake (asset_class={equity,volatility}/symbol={SPY,VIX}/1d.parquet).
SPY_2026_05_05 = 723.77
VIX_2026_05_05 = 17.38
R = 0.04
T_1M = GOAS_DTE_DAYS / 252.0  # 1-month tenor, consistent with the calibration


def test_goas_as_of_constant():
    assert GOAS_AS_OF == date(2026, 5, 5)


def test_flat_skew_is_noop():
    sk = PutSkew(slope=0.0)
    assert sk.iv(0.18, 100.0, 95.0) == pytest.approx(0.18)


def test_skew_is_monotone_downside():
    sk = PutSkew(slope=1.5)
    iv_atm = sk.iv(0.18, 100.0, 100.0)
    iv_otm = sk.iv(0.18, 100.0, 90.0)
    assert iv_otm > iv_atm == pytest.approx(0.18)


def test_build_csp_skew_none_matches_flat():
    S, sigma = 100.0, 0.18
    a = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=None)
    b = build_cash_secured_put(S, sigma, T_1M, R, short_delta=0.15)
    assert a.short_put == pytest.approx(b.short_put)
    assert a.credit == pytest.approx(b.credit)


def test_build_csp_skew_is_delta_consistent():
    S, sigma = 100.0, 0.18
    sk = PutSkew(slope=1.2)
    csp = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=sk)
    iv_k = sk.iv(sigma, S, csp.short_put)
    recovered = -bs_delta(S, csp.short_put, T_1M, R, iv_k, is_call=False)
    assert recovered == pytest.approx(0.15, abs=1e-3)


def test_skew_credit_richer_than_flat():
    S, sigma = 100.0, 0.18
    flat = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=None)
    skew = build_csp_skew(S, sigma, T_1M, R, short_delta=0.15, skew=PutSkew(slope=1.2))
    assert skew.credit > flat.credit


def test_calibrate_reproduces_goas_quote():
    # the calibrated skew reproduces GOAS's published 96.2% strike / 0.7% premium at
    # the real 2026-05-05 VIX (flat-vol is below 0.7% there → positive slope expected).
    S, sigma = SPY_2026_05_05, VIX_2026_05_05 / 100.0
    sk = calibrate_skew(
        S,
        sigma,
        T_1M,
        R,
        target_strike_frac=GOAS_STRIKE_FRAC,
        target_premium_frac=GOAS_PREMIUM_FRAC,
    )
    assert sk.slope > 0.0  # flat-vol under-prices the quote at this VIX
    k_star = GOAS_STRIKE_FRAC * S
    prem = bs_price(S, k_star, T_1M, R, sk.iv(sigma, S, k_star), is_call=False)
    assert prem == pytest.approx(GOAS_PREMIUM_FRAC * S, rel=0.02)


def test_build_csp_skew_rejects_degenerate():
    with pytest.raises(ValueError):
        build_csp_skew(100.0, 0.18, T_1M, R, short_delta=0.6, skew=PutSkew(slope=1.0))
    with pytest.raises(ValueError):
        build_csp_skew(-1.0, 0.18, T_1M, R, short_delta=0.15, skew=None)
