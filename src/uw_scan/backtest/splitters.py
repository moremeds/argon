"""Time-ordered train/test window generators.

Only the holdout splitter exists today. fixed_windows (backtest_canary's
WF-1..WF-5) and rolling (backtest_cri) are added when those scripts migrate —
not before (YAGNI).
"""

from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def time_ordered_holdout(
    items: Iterable[T], *, key: Callable[[T], object], frac: float
) -> tuple[list[T], list[T]]:
    """Sort ascending by key; return (ordered, holdout) where holdout is the
    latest tail. Cut index is int(round(n * (1 - frac))) — the EXACT boundary
    of the two legacy gate implementations (skew_markout, vrp_markout_core);
    do not change the rounding."""
    ordered = sorted(items, key=key)
    cut = int(round(len(ordered) * (1.0 - frac)))
    return ordered, ordered[cut:]
