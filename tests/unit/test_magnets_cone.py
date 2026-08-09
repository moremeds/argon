import math

import pytest

from uw_scan.cards.magnets import CONE_BANDS, CONE_HORIZONS, cone


def test_cone_inverts_the_research_z_definition_exactly():
    """The calibration defined z = (log_ret + 0.5*sigma^2*T) / (sigma*sqrt(T)).
    The drawn band must be the exact inverse or the measured coverage in
    VERDICT.md does not describe what is on screen."""
    spot, sigma, h = 313.33, 0.2271, 5
    t = h / 252.0
    bands = cone(spot, {5: sigma})
    upper = next(b for b in bands if b["horizon"] == 5 and b["band_sigma"] == 1.0)[
        "upper"
    ]
    # forward-solve z from the drawn price and assert it returns 1.0
    z = (math.log(upper / spot) + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    assert z == pytest.approx(1.0, abs=1e-12)


def test_cone_lower_band_is_the_negative_z():
    spot, sigma, h = 313.33, 0.2334, 10
    t = h / 252.0
    lower = next(
        b
        for b in cone(spot, {10: sigma})
        if b["horizon"] == 10 and b["band_sigma"] == 1.96
    )["lower"]
    z = (math.log(lower / spot) + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    assert z == pytest.approx(-1.96, abs=1e-12)


def test_cone_labels_carry_measured_not_nominal_confidence():
    b = next(
        x
        for x in cone(313.33, {5: 0.2271})
        if x["band_sigma"] == 1.0 and x["horizon"] == 5
    )
    assert b["measured_confidence"] == pytest.approx(0.709)  # not 0.6827
    b21 = next(
        x
        for x in cone(313.33, {21: 0.2364})
        if x["band_sigma"] == 1.96 and x["horizon"] == 21
    )
    assert b21["measured_confidence"] == pytest.approx(0.933)  # not 0.95


def test_cone_draws_no_band_wider_than_196_sigma():
    # The far tail needs 8-17% more width than the closed form; a 99% band drawn
    # from it would be wrong by more than any other band on the chart.
    assert max(CONE_BANDS) == 1.96


def test_cone_skips_horizons_with_no_usable_iv():
    got = cone(313.33, {5: 0.2271, 10: None, 21: 0.0})
    assert {b["horizon"] for b in got} == {5}


def test_cone_returns_two_bands_per_usable_horizon():
    got = cone(313.33, {h: 0.23 for h in CONE_HORIZONS})
    assert len(got) == len(CONE_HORIZONS) * len(CONE_BANDS)


def test_cone_k_shrink_below_one_narrows_the_band():
    """k_shrink MULTIPLIES z. The research calibrates with
    `coverage(z_test / k_train, level)`, so its calibrated band accepts
    |z| < k*level — feeding k_train=0.9747 here must make the band NARROWER,
    the direction the variance risk premium implies. Getting this backwards
    draws the reciprocal band and is silent, because it ships at k=1.0."""
    narrow = next(
        b for b in cone(313.33, {5: 0.2271}, k_shrink=0.9) if b["band_sigma"] == 1.0
    )
    base = next(
        b for b in cone(313.33, {5: 0.2271}, k_shrink=1.0) if b["band_sigma"] == 1.0
    )
    assert narrow["upper"] < base["upper"]
    assert narrow["lower"] > base["lower"]


def test_cone_k_shrink_reproduces_the_research_calibrated_band():
    # G2 at 5d fit k_train = 0.9747. The band drawn at (band=1.0, k=0.9747) must
    # be the price where the research's z_test/k_train equals 1.0.
    spot, sigma, h, k = 313.33, 0.2271, 5, 0.9747
    t = h / 252.0
    upper = next(
        b
        for b in cone(spot, {5: sigma}, k_shrink=k)
        if b["horizon"] == 5 and b["band_sigma"] == 1.0
    )["upper"]
    z_obs = (math.log(upper / spot) + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    assert z_obs / k == pytest.approx(1.0, abs=1e-12)


def test_cone_rejects_a_non_positive_k_shrink():
    with pytest.raises(ValueError):
        cone(313.33, {5: 0.2271}, k_shrink=0.0)
