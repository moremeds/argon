"""Publisher transforms, computed on the calendar rather than on row positions.

Every function here is total: it returns ``None`` when the period it needs was not
published, and never substitutes a neighbouring period for a missing one.  That is the
whole reason they are separate from the engines -- a transform that silently reaches
one row further back turns an absent month into a wrong number rather than a stated
gap, and no downstream check can recover the difference.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any


def shift_months(period: date, back: int) -> date:
    """Calendar-anchored month arithmetic.

    Monthly publisher periods are always the first of the month; a day that cannot
    exist in the target month raises rather than being silently clamped, because a
    clamped date would quietly change which period a change is measured over.
    """
    total = period.year * 12 + (period.month - 1) - back
    return date(total // 12, total % 12 + 1, period.day)


def yoy_from_index(series: Mapping[date, Decimal], period: date) -> Decimal | None:
    prior = shift_months(period, 12)
    if period not in series or prior not in series or series[prior] == 0:
        return None
    return (series[period] / series[prior] - 1) * 100


def change_over_months(
    series: Mapping[date, Decimal], period: date, months: int
) -> Decimal | None:
    """Difference against the period exactly ``months`` earlier on the calendar.

    Calendar-anchored, never positional.  October 2025 CPI does not exist -- the
    government shutdown stopped it being published -- so counting three rows back from
    December 2025 lands on August and reports a four-month change labelled as three.
    Anchoring on the calendar instead returns ``None`` when the anchor period is absent,
    which is the honest answer.
    """
    prior = shift_months(period, months)
    if period not in series or prior not in series:
        return None
    return series[period] - series[prior]


def yoy_change_over_months(
    series: Mapping[date, Decimal], period: date, months: int
) -> Decimal | None:
    """Change in the year-over-year rate, differenced at full precision."""
    now = yoy_from_index(series, period)
    then = yoy_from_index(series, shift_months(period, months))
    return None if now is None or then is None else now - then


def annualized_over_months(
    series: Mapping[date, Decimal], period: date, months: int
) -> Decimal | None:
    """Compound the change over ``months`` up to an annual rate."""
    prior = shift_months(period, months)
    if period not in series or prior not in series or series[prior] <= 0:
        return None
    ratio = series[period] / series[prior]
    return ((ratio.ln() * (Decimal(12) / Decimal(months))).exp() - 1) * 100


def newest_period(series: Mapping[date, Any]) -> date | None:
    return max(series) if series else None
