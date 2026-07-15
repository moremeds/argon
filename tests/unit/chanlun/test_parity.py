from __future__ import annotations

from tests.unit.chanlun.parity_helpers import (
    GOLDEN,
    assert_records_equal,
    bars_from_golden,
)
from uw_scan.chanlun.core import macd_hist
from uw_scan.chanlun.full import compute_chanlun


def test_macd_hist_parity():
    bars = bars_from_golden()
    hist = macd_hist([b.close for b in bars])
    golden = GOLDEN["macdHist"]
    assert len(hist) == len(golden) and len(hist) > 0  # non-vacuity
    for i, (a, g) in enumerate(zip(hist, golden)):
        assert abs(a - g) <= 1e-9, f"macdHist[{i}]: {a!r} vs golden {g!r}"


def test_vertices_parity():
    r = compute_chanlun(bars_from_golden())
    assert_records_equal(
        GOLDEN["vertices"],
        r.vertices,
        ["time", "price", "kind", "confirmed"],
        "vertices",
    )


def test_divergences_parity():
    r = compute_chanlun(bars_from_golden())
    assert_records_equal(
        GOLDEN["divergences"],
        r.divergences,
        ["time", "price", "kind", "confirmed"],
        "divergences",
    )


def test_stroke_points_nonvacuity():
    # compute_chanlun points are the PRE-resonance v1 points; the golden `points`
    # array is the post-resonance full list (Task 5). Here only assert the v1
    # point set is non-empty and every point sits on a vertex with matching side.
    r = compute_chanlun(bars_from_golden())
    assert len(r.points) > 0
    by_time = {v.time: v for v in r.vertices}
    for p in r.points:
        v = by_time.get(p.time)
        assert v is not None
        assert v.kind == ("bottom" if p.kind.endswith("B") else "top")
