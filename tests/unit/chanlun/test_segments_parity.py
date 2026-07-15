from __future__ import annotations

from tests.unit.chanlun.parity_helpers import (
    GOLDEN,
    assert_records_equal,
    bars_from_golden,
)
from uw_scan.chanlun.full import compute_chanlun
from uw_scan.chanlun.segments import build_segments


def test_segvertices_parity():
    r = compute_chanlun(bars_from_golden())
    segs = build_segments(r.vertices)
    assert_records_equal(
        GOLDEN["segVertices"],
        segs,
        ["time", "price", "kind", "confirmed"],
        "segVertices",
    )


def test_segvertices_sit_on_stroke_vertices():
    # Mirrors chanlunFull.test.ts:49-54 — every segment vertex is a stroke vertex.
    r = compute_chanlun(bars_from_golden())
    segs = build_segments(r.vertices)
    assert len(segs) > 0  # non-vacuity
    by_time = {v.time: v.price for v in r.vertices}
    for s in segs:
        assert by_time.get(s.time) == s.price
