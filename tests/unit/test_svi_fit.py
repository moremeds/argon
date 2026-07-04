from datetime import date

import numpy as np
from scripts.research.svi_fit import (
    SVIParams,
    build_smile,
    butterfly_g,
    calendar_violations,
    fit_raw_svi,
    raw_svi_total_variance,
    rmse_vol_points,
)


def test_fit_recovers_known_params():
    true = SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.0, sigma=0.1)
    k = np.linspace(-0.5, 0.5, 21)
    w = raw_svi_total_variance(k, true)
    p, _ = fit_raw_svi(k, w)
    iv = np.sqrt(w / 0.25)
    assert rmse_vol_points(k, iv, p, 0.25) < 0.05  # noiseless -> near-exact


def test_butterfly_g_hand_value_and_benign_is_arbfree():
    p = SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.0, sigma=0.1)
    assert (
        abs(butterfly_g(np.array([0.0]), p)[0] - 2.9541) < 1e-3
    )  # hand-derived at k=0
    grid = np.linspace(-1.0, 1.0, 201)
    assert butterfly_g(grid, p).min() >= 0.0  # benign smile is arb-free


def test_build_smile_uses_otm_wings():
    rows = [
        {"strike": 90, "call_iv": 0.25, "put_iv": 0.30},
        {"strike": 110, "call_iv": 0.22, "put_iv": 0.28},
    ]
    k, iv, w, t, strikes = build_smile(
        rows, spot=100.0, market_date=date(2026, 1, 1), expiry=date(2026, 4, 1)
    )
    assert list(strikes) == [90.0, 110.0]
    assert (
        abs(iv[0] - 0.30) < 1e-12 and abs(iv[1] - 0.22) < 1e-12
    )  # put wing, call wing
    assert abs(k[0] - np.log(0.9)) < 1e-12


def test_calendar_violations_flags_decreasing_variance():
    near = SVIParams(a=0.05, b=0.3, rho=-0.2, m=0.0, sigma=0.1)  # w(0)=0.08
    far_ok = SVIParams(a=0.09, b=0.3, rho=-0.2, m=0.0, sigma=0.1)  # w(0)=0.12 -> ok
    far_bad = SVIParams(a=0.02, b=0.3, rho=-0.2, m=0.0, sigma=0.1)  # w(0)=0.05 -> arb
    assert calendar_violations([(1, 0.1, near), (2, 0.3, far_ok)]) == 0
    assert calendar_violations([(1, 0.1, near), (2, 0.3, far_bad)]) == 1
