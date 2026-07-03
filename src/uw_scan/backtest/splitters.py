"""Time-ordered train/test window generators.

Only the holdout splitter exists today. fixed_windows (backtest_canary's
WF-1..WF-5) and rolling (backtest_cri) are added when those scripts migrate —
not before (YAGNI).
"""

from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def holdout_cut_index(n: int, frac: float) -> int:
    """First index of a time-ordered holdout of the latest `frac`:
    int(round(n * (1 - frac))). The single source of the legacy cut rounding;
    do not change it."""
    return int(round(n * (1.0 - frac)))


def time_ordered_holdout(
    items: Iterable[T], *, key: Callable[[T], object], frac: float
) -> tuple[list[T], list[T]]:
    """Sort ascending by key; return (ordered, holdout) where holdout is the
    latest tail. Cut index is holdout_cut_index(n, frac) = int(round(n*(1-frac)))
    — the exact legacy boundary shared by every gate/holdout consumer; do not
    change the rounding."""
    ordered = sorted(items, key=key)
    cut = holdout_cut_index(len(ordered), frac)
    return ordered, ordered[cut:]
