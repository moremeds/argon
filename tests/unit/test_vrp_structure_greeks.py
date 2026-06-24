import math

from uw_scan.reports.vrp_structure import bs_gamma, bs_theta, bs_vega

# Frozen reference: S=K=100, T=1, r=0, sigma=0.2 -> d1=0.1, N.pdf(0.1)=0.396953  [COMPUTED]


def test_bs_gamma_reference():
    assert math.isclose(bs_gamma(100, 100, 1.0, 0.0, 0.2), 0.0198477, abs_tol=1e-5)


def test_bs_vega_reference():
    assert math.isclose(bs_vega(100, 100, 1.0, 0.0, 0.2), 39.6953, abs_tol=1e-3)


def test_bs_theta_reference():
    # r=0 -> call theta == put theta == -(S*pdf*sigma)/(2*sqrt(T)) = -3.96953 per year
    assert math.isclose(
        bs_theta(100, 100, 1.0, 0.0, 0.2, is_call=True), -3.96953, abs_tol=1e-3
    )
    assert math.isclose(
        bs_theta(100, 100, 1.0, 0.0, 0.2, is_call=False), -3.96953, abs_tol=1e-3
    )


def test_degenerate_returns_zero():
    assert bs_gamma(100, 100, 0.0, 0.0, 0.2) == 0.0
    assert bs_vega(100, 100, 1.0, 0.0, 0.0) == 0.0
    assert bs_theta(100, 100, -1.0, 0.0, 0.2, is_call=True) == 0.0
