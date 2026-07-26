"""Crowding leg mappers and the min-band state rule.

Raw inputs are frozen from a live UW probe on 2026-07-24 plus warm-store
iv_rank on 2026-07-25. Reproduce with
`uv run python scripts/research/sector_crowding_probe.py`; full trace in
docs/research/2026-07-26-sector-crowding-probe.md.
"""

import pytest

from uw_scan.reports.sector_crowding import (
    CrowdingLeg,
    band_of,
    combine,
    flow_score,
    pct_rank,
    premium_score,
)


def test_pct_rank_counts_strictly_below():
    assert pct_rank([1.0, 2.0, 3.0, 4.0], 3.5) == 75.0
    assert pct_rank([1.0, 2.0, 3.0, 4.0], 0.5) == 0.0


def test_pct_rank_empty_history_is_none():
    assert pct_rank([], 1.0) is None


@pytest.mark.parametrize(
    "flow_aum_pct,expected",
    [
        (21.46, 97.64),  # SOXX -- interpolated between 10%->90 and 25%->100
        (4.98, 69.8),  # XLF  -- interpolated between 2%->40 and 5%->70
        (1.91, 39.1),  # SMH  -- between 0%->20 and 2%->40
        (0.28, 22.8),  # XLK  -- same segment, near the bottom
        (-8.27, 0.0),  # IGV  -- heavy outflow, clamps at the floor
        (30.0, 100.0),  # past the 25% breakpoint, clamps (boundary, not a
        # ticker observation -- nothing in the universe is
        # there today and the ceiling still needs a test)
    ],
)
def test_flow_score_uses_tweet_breakpoints(flow_aum_pct, expected):
    assert flow_score(flow_aum_pct) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize(
    "spread,expected",
    [
        (64.23, 100.0),  # SOXX 93.93 - SPY 29.70, clamps at the 60pt cap
        (56.75, 94.58),  # XLK  86.45 - SPY 29.70
        (0.0, 0.0),
        (-10.0, 0.0),  # below the benchmark is not crowding
    ],
)
def test_premium_score_caps_at_60_points(spread, expected):
    assert premium_score(spread) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize(
    "score,band",
    [
        (100.0, "CROWDED"),
        (75.0, "CROWDED"),
        (74.9, "WARM"),
        (50.0, "WARM"),
        (49.9, "NORMAL"),
        (25.0, "NORMAL"),
        (24.9, "COLD"),
        (0.0, "COLD"),
        (None, None),
    ],
)
def test_band_of(score, band):
    assert band_of(score) == band


def test_soxx_all_legs_fire_so_state_is_crowded():
    """Real SOXX legs, 2026-07-24 probe, date-joined against SPY."""
    legs = [
        CrowdingLeg("price", 53.69, 97.0, "CROWDED"),
        CrowdingLeg("flow", 21.46, 97.64, "CROWDED"),
        CrowdingLeg("premium", 64.23, 100.0, "CROWDED"),
    ]
    score, state, binding = combine(legs)
    assert score == pytest.approx(98.21, abs=0.01)
    assert state == "CROWDED"
    assert binding == "price"  # the lowest-scoring leg inside the weakest band


def test_smh_is_demoted_by_its_two_normal_legs():
    """SMH's +17.88% is the second-loudest spread on the table and still not
    crowded: it is only its own 46th percentile, and its 1M flow is a modest
    1.91% of AUM. Only the premium leg is hot. The min-band rule is what stops
    that one extreme leg from manufacturing a CROWDED badge -- the tweet's
    conjunctive requirement, 三者同时出现，才算真正拥挤.

    Real SMH legs, 2026-07-24 probe, date-joined against SPY.
    """
    legs = [
        CrowdingLeg("price", 17.88, 46.0, "NORMAL"),
        CrowdingLeg("flow", 1.91, 39.1, "NORMAL"),
        CrowdingLeg("premium", 63.48, 100.0, "CROWDED"),
    ]
    score, state, binding = combine(legs)
    assert score == pytest.approx(61.70, abs=0.01)
    assert state == "NORMAL"
    # Weakest band is NORMAL; flow is the lower-scoring leg inside it.
    assert binding == "flow"


def test_missing_leg_is_skipped():
    legs = [
        CrowdingLeg("price", 9.09, 70.0, "WARM"),
        CrowdingLeg("flow", 0.28, 22.8, "COLD"),
        CrowdingLeg("premium", None, None, None),
    ]
    score, state, binding = combine(legs)
    assert score == pytest.approx(46.4, abs=0.01)
    assert state == "COLD"
    assert binding == "flow"


def test_fewer_than_two_legs_yields_nothing():
    legs = [
        CrowdingLeg("price", 1.0, 50.0, "WARM"),
        CrowdingLeg("flow", None, None, None),
        CrowdingLeg("premium", None, None, None),
    ]
    assert combine(legs) == (None, None, None)
