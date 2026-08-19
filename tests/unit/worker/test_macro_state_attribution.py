"""The attribution's window has to be the window it is named for.

``_attribution`` opens a 30-day move by reaching for the newest print on or before the
window's start. Unbounded, that reach walks back as far as the loaded history allows --
``RATES_HISTORY_DAYS`` is 45 -- and reports a 45-day move under a 30-day name. The
numbers stay real; the window silently is not the one the metric claims.

The 10y levels below are real DGS10 readings already frozen elsewhere in this suite
(``tests/unit/macro/test_rates_state.py``): 2.39 traded in April 2022 and 3.86 in July
2023. Only their dates are arranged, to place a print inside or outside the tolerance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from uw_scan.macro.contracts import DomainObservation
from uw_scan.worker.jobs.macro_state_jobs import (
    ATTRIBUTION_START_TOLERANCE_DAYS,
    ATTRIBUTION_WINDOW_DAYS,
    _attribution,
)

AS_OF = datetime(2026, 8, 18, 23, 0, tzinfo=UTC)


def _obs(series_id: str, period_end: date, value: str) -> DomainObservation:
    return DomainObservation(
        series_id=series_id,
        causal_role="curve" if series_id == "DGS10" else "decomposition_component",
        period_end=period_end,
        value=Decimal(value),
        unit="percent",
        publisher_transform="level",
        available_at=datetime.combine(period_end, datetime.min.time(), tzinfo=UTC)
        + timedelta(days=1),
        source="fred",
        source_kind="official",
        cost_class="free_official",
    )


def _legs(start_age_days: int) -> tuple[DomainObservation, ...]:
    """One nominal print at ``start_age_days`` back, one today."""
    return (
        _obs("DGS10", AS_OF.date() - timedelta(days=start_age_days), "3.86"),
        _obs("DGS10", AS_OF.date(), "2.39"),
    )


def test_a_print_inside_the_tolerance_opens_the_window() -> None:
    inside = ATTRIBUTION_WINDOW_DAYS + ATTRIBUTION_START_TOLERANCE_DAYS
    result = _attribution(_legs(inside), as_of=AS_OF)
    assert result is not None
    assert result.nominal_change_bps == Decimal("2.39") * 100 - Decimal("3.86") * 100


def test_a_print_older_than_the_tolerance_leaves_the_leg_unavailable() -> None:
    """A 45-day-old print must not be reported as the start of a 30-day move."""
    stale = ATTRIBUTION_WINDOW_DAYS + ATTRIBUTION_START_TOLERANCE_DAYS + 1
    result = _attribution(_legs(stale), as_of=AS_OF)
    assert result is not None
    assert result.nominal_change_bps is None
    assert result.attribution == "unavailable"
    assert "not published over this window" in result.note
