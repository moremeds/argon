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


def test_a_band_missing_its_cheap_end_is_refused_not_drawn():
    """JPM's real 2026-08-12 shape, and the hole in the width guard.

    A bank's funding sits in `short_long_term_debt_total`, so net debt exceeds
    the enterprise value its own cheapest multiple implies and `buy_below` does
    not invert. The width guard reads `if lo and hi`, so a band with no cheap end
    skipped it entirely: JPM rendered three of five levels with `observe_mid` at
    11.3 against a spot of 297.8 — 4% of the price — and nothing said the band
    had no bottom.

    A missing INTERIOR level is a gap. A missing END is a band with no extent,
    and extent is the only thing a band asserts.
    """
    out = _band(TIGHT, net_debt=1e6, shares=100.0, fundamental=1000.0)
    assert out["anchors"] is None
    assert any("no price at this net debt" in r for r in out["confidence_reasons"])
    assert any("cheap end" in r for r in out["confidence_reasons"])


def test_the_rules_are_part_of_a_band_identity():
    """The corrective run must not collide with the row it corrects.

    Measured: after the missing-end guard was added, a run computed 233 bands and
    wrote 0. Every refusal carried the same `(ticker, as_of, engine_version,
    inputs_hash)` as the wrong band already stored, so `ON CONFLICT DO NOTHING`
    kept the wrong one. Hashing the rule revision is what makes a rule change
    append the correction.
    """
    from uw_scan.fundamentals import valuation as V

    args = dict(
        company_type="chips_cyclical",
        engine="v1_equal",
        fundamental=1000.0,
        net_debt=0.0,
        shares=100.0,
        history_n=20,
    )
    before = V.anchor_inputs_hash(**args)
    original = V.ANCHOR_RULES_REV
    try:
        V.ANCHOR_RULES_REV = original + 1
        assert V.anchor_inputs_hash(**args) != before
    finally:
        V.ANCHOR_RULES_REV = original
    assert V.anchor_inputs_hash(**args) == before

    original_width = V.MAX_BAND_WIDTH
    try:
        V.MAX_BAND_WIDTH = original_width + 1
        assert V.anchor_inputs_hash(**args) != before, "thresholds count too"
    finally:
        V.MAX_BAND_WIDTH = original_width
