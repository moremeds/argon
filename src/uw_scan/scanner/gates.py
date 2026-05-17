"""Gates - pre-detection filters.

Only regime_gate is a hard block. earnings_gate and liquidity_gate are
ADVISORY: their pass/block status is recorded per (run, ticker) and
returned to the UI as a colored indicator, but they do NOT suppress
the candidate. Reason: earnings_iv_crush REQUIRES earnings within 14d
to fire - a hard earnings block would prevent EIC from ever emitting.
(Spec §4.)
"""

from __future__ import annotations

from collections.abc import Sequence
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


def regime_gate(
    *,
    structural_posture_chip: str | None,
    block_chips: Sequence[str] = ("SUSPENDED", "DEGRADED"),
) -> GateStatus:
    """Hard. Block when GOLD COMPASS structural posture is in block_chips.

    Fail-OPEN on missing posture - the scanner must not freeze just
    because GOLD hasn't run yet today. (Spec §4 fail-open rule.)
    """
    if structural_posture_chip is None:
        return "pass"
    return "block" if structural_posture_chip in block_chips else "pass"
