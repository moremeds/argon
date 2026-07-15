from __future__ import annotations

from tests.unit.chanlun.parity_helpers import bars_from_golden
from uw_scan.chanlun.core import merge_inclusions


def test_no_two_consecutive_merged_candles_are_mutually_inclusive():
    bars = bars_from_golden()
    m = merge_inclusions(bars)
    assert len(m) > 0  # non-vacuity
    for i in range(1, len(m)):
        a, b = m[i - 1], m[i]
        inc = (a.high >= b.high and a.low <= b.low) or (
            b.high >= a.high and b.low <= a.low
        )
        assert not inc, f"merged candles {i - 1}/{i} still mutually inclusive"


def test_merged_extremes_point_at_the_carrying_raw_bar():
    bars = bars_from_golden()
    m = merge_inclusions(bars)
    assert len(m) > 0
    for k in m:
        assert bars[k.hiIdx].high == k.high
        assert bars[k.loIdx].low == k.low
