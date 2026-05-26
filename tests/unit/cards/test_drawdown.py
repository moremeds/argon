"""Drawdown event detector — non-overlapping within a single definition.

Cross-definition independence: Fast/Medium/Major may overlap across
definitions and are detected independently against the same close series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.drawdown import (
    DrawdownDefinition,
    detect_drawdown_events,
)


def _closes(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(
        values, index=pd.bdate_range(start=start, periods=len(values)), dtype=float
    )


def test_no_events_in_flat_series() -> None:
    closes = _closes([100.0] * 50)
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert events == []


def test_single_fast_drawdown_detected() -> None:
    # Peak 100 -> trough 92 in 5 days (-8%), then recovers.
    closes = _closes([100, 98, 96, 94, 92] + [93, 95, 97, 99, 101] + [102] * 20)
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert len(events) == 1
    e = events[0]
    assert e.depth_pct == pytest.approx(0.08, abs=1e-9)
    assert e.peak_price == pytest.approx(100.0)
    assert e.trough_price == pytest.approx(92.0)


def test_consecutive_drawdowns_non_overlapping_within_definition() -> None:
    """Two drawdowns separated by recovery must produce two events, not one."""
    closes = _closes(
        [100, 94, 92]
        + [93, 99, 101]  # event 1: -8% then recover to 101
        + [95, 92, 90]
        + [91, 96, 102]  # event 2: -11.8% then recover to 102
    )
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert len(events) == 2
    assert events[0].trough_price == pytest.approx(92.0)
    assert events[1].trough_price == pytest.approx(90.0)


def test_nested_dips_do_not_create_overlapping_events() -> None:
    """A continuous selloff must be ONE event, not many."""
    closes = _closes(
        list(np.linspace(100, 80, 15))  # 20% selloff over 15 bars
        + list(np.linspace(80, 100, 10))  # recovery
    )
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert len(events) == 1, f"expected one event, got {len(events)}"


def test_definitions_independent_for_same_series() -> None:
    """Fast and Major see the same series differently — neither suppresses
    the other."""
    closes = _closes(
        list(np.linspace(100, 88, 8))  # -12% in 8 bars: qualifies Fast AND Major
        + [89, 91, 95, 100]
    )
    fast = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    major = detect_drawdown_events(closes, DrawdownDefinition("Major", 0.10, 60))
    assert len(fast) == 1
    assert len(major) == 1
    # Both should have detected the same trough independently
    assert fast[0].trough_date == major[0].trough_date


def test_continuous_selloff_without_recovery_emits_one_event() -> None:
    """REGRESSION GUARD: a series that drops continuously to the end of the
    range (no recovery before the data ends) must emit exactly ONE event.
    Without the 'i = n' exit in the detector, progressively-lower troughs
    would each spawn a separate event."""
    closes = _closes(list(np.linspace(100, 50, 60)))  # -50% over 60 bars, no recovery
    events = detect_drawdown_events(closes, DrawdownDefinition("Major", 0.10, 60))
    assert len(events) == 1
    assert events[0].recovery_date is None
