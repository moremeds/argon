from __future__ import annotations

from tests.unit.chanlun.parity_helpers import GOLDEN, bars_from_golden
from uw_scan.chanlun.core import macd_hist


def test_macd_hist_parity():
    bars = bars_from_golden()
    hist = macd_hist([b.close for b in bars])
    golden = GOLDEN["macdHist"]
    assert len(hist) == len(golden) and len(hist) > 0  # non-vacuity
    for i, (a, g) in enumerate(zip(hist, golden)):
        assert abs(a - g) <= 1e-9, f"macdHist[{i}]: {a!r} vs golden {g!r}"
