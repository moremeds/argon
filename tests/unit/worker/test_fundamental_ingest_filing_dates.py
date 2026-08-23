"""The two UW endpoints disagree about when a quarter ends; the match must tolerate it.

`income-statements` normalises a period to a calendar month-end; `fundamental-breakdown`
reports the true fiscal period end. For a 52/53-week filer the two never coincide, so an
exact lookup returns NULL on every period of every such name — 129 tickers and 885
periods measured on 2026-08-23, none of them matched at tolerance 0.

Figures are AAPL's real breakdown rows, read from
`GET /api/stock/AAPL/fundamental-breakdown` on 2026-08-23 and frozen here.
Method and the tolerance curve: docs/research/2026-08-23-fundamental-filing-date-recovery/
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.worker.jobs.fundamental_ingest import (
    FILING_DATE_MATCH_TOLERANCE_DAYS,
    _resolve_filing_date,
)

# Real AAPL fiscal period ends -> real SEC filing dates, as of 2026-08-23.
AAPL_BREAKDOWN: dict[date, date] = {
    date(2026, 6, 27): date(2026, 7, 31),
    date(2026, 3, 28): date(2026, 5, 1),
    date(2025, 12, 27): date(2026, 1, 30),
    date(2025, 9, 27): date(2025, 10, 31),
    date(2025, 6, 28): date(2025, 8, 1),
}

# What the statement endpoints report for the same quarters.
AAPL_STATEMENT_PERIODS = [
    (date(2026, 6, 30), date(2026, 7, 31)),
    (date(2026, 3, 31), date(2026, 5, 1)),
    (date(2025, 12, 31), date(2026, 1, 30)),
    (date(2025, 9, 30), date(2025, 10, 31)),
    (date(2025, 6, 30), date(2025, 8, 1)),
]


@pytest.mark.parametrize("period_end,expected", AAPL_STATEMENT_PERIODS)
def test_month_end_period_resolves_to_the_fiscal_filing_date(period_end, expected):
    assert _resolve_filing_date(AAPL_BREAKDOWN, period_end) == expected


def test_exact_match_still_wins():
    """A calendar-quarter filer must not be routed through the tolerance path."""
    exact = {date(2026, 6, 30): date(2026, 7, 30)}
    assert _resolve_filing_date(exact, date(2026, 6, 30)) == date(2026, 7, 30)


def test_exact_match_is_preferred_over_a_nearer_looking_neighbour():
    """When both exist the recorded period wins, never the arithmetic."""
    both = {
        date(2026, 6, 30): date(2026, 7, 30),
        date(2026, 6, 29): date(1999, 1, 1),
    }
    assert _resolve_filing_date(both, date(2026, 6, 30)) == date(2026, 7, 30)


def test_a_period_beyond_the_tolerance_does_not_match():
    """The window is a window. WMT's 2026-07-31 has no breakdown row and must stay NULL
    rather than borrow the 2026-04-30 quarter's date."""
    wmt = {date(2026, 4, 30): date(2026, 5, 29)}
    assert _resolve_filing_date(wmt, date(2026, 7, 31)) is None


def test_the_neighbouring_quarter_is_unreachable():
    """Quarters sit ~91 days apart, so no tolerance this small can cross one."""
    assert FILING_DATE_MATCH_TOLERANCE_DAYS < 45


def test_empty_breakdown_resolves_to_none():
    assert _resolve_filing_date({}, date(2026, 6, 30)) is None


def test_nearest_wins_and_ties_are_deterministic():
    """Two candidates equidistant on either side resolve the same way every run."""
    both_sides = {
        date(2026, 6, 27): date(2026, 7, 31),
        date(2026, 7, 3): date(2026, 8, 6),
    }
    first = _resolve_filing_date(both_sides, date(2026, 6, 30))
    assert first == _resolve_filing_date(both_sides, date(2026, 6, 30))
    assert first in {date(2026, 7, 31), date(2026, 8, 6)}
