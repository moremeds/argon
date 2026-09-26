"""build_technical_snapshot must accept a precomputed series and produce the
same snapshot as when it builds the series itself."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from uw_scan.cards import technicals as mod


def _bars(n: int = 260) -> list[dict]:
    d0 = date(2025, 9, 1)
    out = []
    px = 100.0
    for i in range(n):
        px *= 1.0 + (0.004 if i % 3 else -0.003)
        out.append(
            {
                "time": f"{d0 + timedelta(days=i)}T00:00:00Z",
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "volume": 1_000_000 + i,
            }
        )
    return out


def test_snapshot_with_prebuilt_series_matches_and_skips_rebuild():
    bars = _bars()
    series = mod.build_technical_series(bars)
    baseline = mod.build_technical_snapshot(bars)
    assert baseline is not None

    with patch.object(mod, "build_technical_series", wraps=mod.build_technical_series) as spy:
        reused = mod.build_technical_snapshot(bars, series=series)
    assert spy.call_count == 0
    assert reused == baseline
