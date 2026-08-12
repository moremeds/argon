"""Band WIDTH — the check the full-history window needed and did not have.

Every level of ASML's 2026-08-12 band was arithmetically correct and the band was
still useless: `buy_below` at 255.7 against a spot of 1518. Correctness of each
number is not usability of the set, and only the second is a product property.

Width is the metric that separates them, and it had to be measured to find that
out. Spot-versus-midpoint does not work: ASML's broken band sat only 2.17x from
its own `observe_mid`, comfortably inside any sane bound. What was wrong is that
its ends were **4.35x apart**. Against a measured median width of 1.73x across
the 50 banded names, that is the discriminator.

Figures below are real, from the 2026-08-12 run.
"""

from __future__ import annotations

import pytest

from uw_scan.fundamentals.valuation import MAX_BAND_WIDTH, build_anchors

# A 20-quarter history whose ends are ~2x apart — a normal, usable band.
TIGHT = [0.20 + 0.01 * i for i in range(20)]


def _band(history, **kw):
    base = {
        "ticker": "AAA",
        "company_type": "chips_cyclical",
        "history": history,
        "fundamental": 1000.0,
        "net_debt": 0.0,
        "shares": 100.0,
        "spot": 50.0,
        "knowledge_age_days": 30,
    }
    return build_anchors(**{**base, **kw})


def _width(band):
    a = band["anchors"]
    return a["risk_above"] / a["buy_below"]


def test_a_normal_band_renders_and_is_narrow():
    out = _band(TIGHT)
    assert out["anchors"] is not None
    assert _width(out) < MAX_BAND_WIDTH


def test_a_band_whose_ends_are_far_apart_is_refused_with_its_width():
    """NBIS's real shape: a 20-quarter range spanning 72x, because the window
    still straddles a business transformation. A 72x band is not a decision
    surface no matter how correctly each level was computed."""
    wild = [0.001 * (1.6**i) for i in range(20)]
    out = _band(wild)
    assert out["anchors"] is None
    assert any("too unstable to anchor" in r for r in out["confidence_reasons"])
    assert any("x" in r for r in out["confidence_reasons"]), "the width is stated"


def test_the_threshold_sits_in_the_empty_part_of_the_measured_distribution():
    """Median width across the 50 banded names is 1.73x; the refused tail is
    NBIS 72x, MSTR 47x, APLD 17x, DIS 7.0x. 4.0 separates two populations rather
    than cutting a continuum."""
    assert 3.0 < MAX_BAND_WIDTH < 5.0


def test_spot_versus_midpoint_would_not_have_caught_asml():
    """Recorded because it was my first attempt and it silently passed.

    ASML's broken band: observe_mid 699.8 against spot 1518.3 is 2.17x — inside
    any reasonable spot-distance bound. The band was still unusable. A metric
    that cannot fail on the case that motivated it is not a guard.
    """
    assert 1518.3 / 699.8 == pytest.approx(2.17, abs=0.01)
    assert 1112.67 / 255.71 == pytest.approx(4.35, abs=0.01)
    assert 1112.67 / 255.71 > MAX_BAND_WIDTH


def test_the_windowed_asml_band_passes():
    """Same name, same day, trailing 20 quarters: 1431.5 / 1028.1 = 1.39x."""
    assert 1431.5 / 1028.1 < MAX_BAND_WIDTH
