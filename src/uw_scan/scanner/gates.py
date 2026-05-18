"""Gates - pre-detection advisory filters.

Earnings and liquidity pass/block status is recorded per (run, ticker)
and returned to the UI as a colored indicator, but they do NOT suppress
the candidate. GOLD regime no longer hard-blocks scanner output.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

GateStatus = Literal["pass", "block"]


def earnings_gate(
    *,
    next_earnings_date: date | None,
    today: date,
    window_days: int = 14,
) -> GateStatus:
    """Advisory. Pass when earnings is known AND > window_days away.

    Conservative-block on unknown (matches xenon `_parse_next_earnings`
    returning `(None, True)` - better to advise caution than to assert
    safety the data can't prove).
    """
    if next_earnings_date is None:
        return "block"
    return "pass" if (next_earnings_date - today).days > window_days else "block"


def liquidity_gate(
    *,
    option_volume: int | None,
    min_volume: int = 1000,
) -> GateStatus:
    """Advisory. Pass when the run's total FlowAlert.volume >= min_volume."""
    if option_volume is None:
        return "block"
    return "pass" if option_volume >= min_volume else "block"
