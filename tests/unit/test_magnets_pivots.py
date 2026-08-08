# tests/unit/test_magnets_pivots.py
import math

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.magnets import Pivot, all_pivots
from uw_scan.cards.technicals import atr14, last_pivot_index


def _frame(closes: list[float]) -> pd.DataFrame:
    """OHLC frame from a close path; high/low straddle close so ATR is non-zero."""
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": c, "high": c * 1.01, "low": c * 0.99, "close": c}
    )


def _zigzag(n_legs: int, amplitude: float, leg_len: int) -> list[float]:
    out: list[float] = [100.0]
    up = True
    for _ in range(n_legs):
        target = out[-1] * (1 + amplitude) if up else out[-1] * (1 - amplitude)
        out.extend(np.linspace(out[-1], target, leg_len)[1:].tolist())
        up = not up
    return out


def _legacy_last_pivot_index(df: pd.DataFrame, k: float = 3.0) -> int:
    """FROZEN copy of cards/technicals.py::last_pivot_index as it stood at
    commit ebd0393, before the all_pivots extraction.

    Do not "simplify" this to call the real function — that makes the
    equivalence test circular and it would pass even if the refactor silently
    changed behaviour for every caller. This copy is the reference; if it ever
    disagrees with the shipped wrapper, the shipped wrapper is what changed.
    """
    close = df["close"].to_numpy(dtype=float)
    atr = atr14(df).to_numpy(dtype=float)
    n = len(close)
    if n < 30:
        return 0
    pivots: list[int] = []
    direction = 1 if close[min(20, n - 1)] >= close[0] else -1
    ext_i = 0
    for i in range(1, n):
        thr = k * atr[i] if math.isfinite(atr[i]) and atr[i] > 0 else math.inf
        if direction == 1:
            if close[i] >= close[ext_i]:
                ext_i = i
            elif close[ext_i] - close[i] >= thr:
                pivots.append(ext_i)
                direction, ext_i = -1, i
        else:
            if close[i] <= close[ext_i]:
                ext_i = i
            elif close[i] - close[ext_i] >= thr:
                pivots.append(ext_i)
                direction, ext_i = 1, i
    if not pivots:
        return max(0, n - 126)
    return pivots[-1]


def test_pivots_alternate_top_and_bottom():
    df = _frame(_zigzag(6, 0.30, 12))
    pivots = all_pivots(df, k=3.0)
    assert len(pivots) >= 2
    kinds = [p.kind for p in pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))


def test_pivot_price_matches_the_close_at_its_index():
    df = _frame(_zigzag(6, 0.30, 12))
    for p in all_pivots(df, k=3.0):
        assert p.price == pytest.approx(float(df["close"].iloc[p.index]))


def test_higher_threshold_yields_no_more_pivots():
    df = _frame(_zigzag(8, 0.25, 10))
    assert len(all_pivots(df, k=5.0)) <= len(all_pivots(df, k=2.0))


def test_monotonic_series_confirms_no_pivots():
    df = _frame(np.linspace(100.0, 300.0, 200).tolist())
    assert all_pivots(df, k=3.0) == []


def test_short_series_returns_empty():
    assert all_pivots(_frame([100.0] * 10), k=3.0) == []


def test_last_pivot_index_is_unchanged_by_the_refactor():
    """Regression guard: the wrapper must reproduce the legacy contract exactly,
    including the len-126 fallback when nothing confirms."""
    df = _frame(_zigzag(6, 0.30, 12))
    pivots = all_pivots(df, k=3.0)
    assert last_pivot_index(df) == pivots[-1].index

    flat = _frame(np.linspace(100.0, 300.0, 200).tolist())
    assert last_pivot_index(flat) == max(0, len(flat) - 126)

    tiny = _frame([100.0] * 10)
    assert last_pivot_index(tiny) == 0


def test_pivot_is_a_named_tuple_with_stable_field_order():
    p = Pivot(3, "top", 101.5, 7)
    assert (p.index, p.kind, p.price, p.confirmed_index) == (3, "top", 101.5, 7)


def test_confirmation_always_lags_the_pivot_bar():
    """The lookahead guard. If this ever fails, every forward test is invalid."""
    df = _frame(_zigzag(8, 0.25, 10))
    pivots = all_pivots(df, k=3.0)
    assert pivots, "fixture must produce pivots or the guard proves nothing"
    for p in pivots:
        assert p.confirmed_index > p.index


def test_confirmation_price_differs_materially_from_the_pivot_price():
    """Quantifies WHY confirmed_index exists: entering at the pivot bar buys a
    low that was not knowable. Measured lag is 3-25 bars, 8-14% of price."""
    df = _frame(_zigzag(8, 0.25, 10))
    close = df["close"]
    gaps = [
        abs(close.iloc[p.confirmed_index] / p.price - 1.0)
        for p in all_pivots(df, k=3.0)
    ]
    assert max(gaps) > 0.05


def test_wrapper_matches_the_legacy_last_pivot_index_exactly():
    """Equivalence against the SHIPPED function, not against all_pivots — the
    latter would be circular and would pass even if both were wrong together."""
    for closes in (
        _zigzag(6, 0.30, 12),
        _zigzag(8, 0.25, 10),
        _zigzag(3, 0.10, 40),
        np.linspace(100.0, 300.0, 200).tolist(),
        [100.0] * 10,
    ):
        df = _frame(closes)
        assert last_pivot_index(df) == _legacy_last_pivot_index(df)
