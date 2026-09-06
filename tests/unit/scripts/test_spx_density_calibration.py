"""Hand-computed checks for the SPX density calibration metric math.

Loads scripts/research/spx_density_calibration.py by file path (scripts/ is not
an importable package), same as the other script tests here.

The histograms below are hand-built test doubles with round numbers chosen so
every expected value can be computed on paper — NOT market data, and never
presented as such. The market-data path is exercised by running the script
itself against uw_scan.spx_density_forecast.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/research/spx_density_calibration.py"
)
_spec = importlib.util.spec_from_file_location("spx_density_calibration", _SCRIPT)
cal = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cal
_spec.loader.exec_module(cal)


# 4 bins of width 0.01 spanning [-0.02, 0.02]; 98 draws on the axis, 2 clipped.
# The symmetric (0.005, 0.995) clip means 1 draw below lo and 1 above hi.
BINS = {
    "lo": -0.02,
    "hi": 0.02,
    "n_bins": 4,
    "counts": [10, 40, 40, 8],
    "total": 100,
    "clipped": 2,
}


def test_pit_inside_bin_interpolates_linearly():
    # x = 0.005 sits halfway through bin 2 ([0.00, 0.01)).
    # cum = 1 (below lo) + 10 + 40 (bins fully below) + 0.5 * 40 = 71 of 100.
    u, status = cal.pit_from_bins(BINS, 0.005)
    assert status == "inside"
    assert u == pytest.approx(0.71)


def test_pit_at_zero_is_p_down():
    # x = 0.0 is the left edge of bin 2: cum = 1 + 10 + 40 + 0 = 51 of 100.
    u, status = cal.pit_from_bins(BINS, 0.0)
    assert status == "inside"
    assert u == pytest.approx(0.51)


def test_pit_at_axis_edges_accounts_for_the_clipped_draws():
    # lo: only the 1 below-axis draw precedes it. hi: everything but the 1 above.
    assert cal.pit_from_bins(BINS, -0.02)[0] == pytest.approx(0.01)
    assert cal.pit_from_bins(BINS, 0.02)[0] == pytest.approx(0.99)


def test_pit_outside_the_axis_takes_the_tail_midpoint_and_is_flagged():
    u_lo, s_lo = cal.pit_from_bins(BINS, -0.05)
    u_hi, s_hi = cal.pit_from_bins(BINS, 0.05)
    assert (s_lo, s_hi) == ("below_lo", "above_hi")
    # below tail spans [0, 1/100]; above tail spans [99/100, 1]. Midpoints:
    assert u_lo == pytest.approx(0.005)
    assert u_hi == pytest.approx(0.995)
    assert 0.0 <= u_lo <= u_hi <= 1.0


def test_pit_is_monotone_across_the_axis():
    xs = [-0.019, -0.005, 0.0, 0.005, 0.019]
    us = [cal.pit_from_bins(BINS, x)[0] for x in xs]
    assert us == sorted(us)


def test_pit_rejects_unusable_bins():
    with pytest.raises(ValueError):
        cal.pit_from_bins({**BINS, "hi": -0.02}, 0.0)


def test_pinball_loss_both_sides():
    # Under-prediction (y above q) costs tau * d.
    assert cal.pinball_loss(0.9, 0.01, 0.03) == pytest.approx(0.9 * 0.02)
    # Over-prediction (y below q) costs (1 - tau) * -d.
    assert cal.pinball_loss(0.9, 0.01, -0.01) == pytest.approx(0.1 * 0.02)
    # The median is symmetric: equal-sized misses either way cost the same.
    assert cal.pinball_loss(0.5, 0.0, 0.02) == pytest.approx(0.01)
    assert cal.pinball_loss(0.5, 0.0, -0.02) == pytest.approx(0.01)
    # A perfect quantile costs nothing.
    assert cal.pinball_loss(0.25, 0.007, 0.007) == pytest.approx(0.0)


def test_pinball_is_minimised_at_the_true_quantile():
    # Sample whose 90th percentile is 9: pinball at tau=0.9 must be lowest there.
    ys = list(range(11))

    def total(q: float) -> float:
        return sum(cal.pinball_loss(0.9, q, float(y)) for y in ys)

    assert total(9.0) < total(5.0)
    assert total(9.0) < total(10.0)


def test_wilson_ci_brackets_the_point_estimate():
    lo, hi = cal.wilson_ci(80, 100)
    assert lo < 0.80 < hi
    # Wilson stays inside [0, 1] where the normal approximation would not.
    lo0, hi0 = cal.wilson_ci(100, 100)
    assert lo0 > 0.9 and hi0 == pytest.approx(1.0)
    # n = 0 has no interval: nan, not a crash and not a fake 0-1 span.
    assert all(math.isnan(v) for v in cal.wilson_ci(0, 0))
