"""The publication rule — every refusal clause, and why it refuses.

The tests that matter here are the NEGATIVE ones. A rule that grants `true_pit`
generously is worse than no rule at all: it launders a restatement as
point-in-time history and every downstream backtest inherits the leak silently.
"""

from __future__ import annotations

from datetime import date

from uw_scan.fundamentals.publication_evidence import (
    REASON_AMBIGUOUS,
    REASON_AMENDED,
    REASON_FILED_BEFORE_PERIOD,
    REASON_MATCHED,
    REASON_MULTI_VERSION,
    REASON_NO_FILING,
    match_publication,
)
from uw_scan.sources.sec_submissions import SecFiling


def filing(report: str, filed: str, form="10-Q", accession="acc-1") -> SecFiling:
    return SecFiling(
        accession=accession,
        form=form,
        report_date=date.fromisoformat(report),
        filing_date=date.fromisoformat(filed),
        is_amendment=form.endswith("/A"),
    )


def test_a_clean_single_version_period_matches():
    m, reason = match_publication(
        date(2026, 4, 30), [filing("2026-04-26", "2026-05-20")], version_count=1
    )
    assert reason == REASON_MATCHED
    assert m is not None
    assert m.filing_date == date(2026, 5, 20)
    assert m.accession == "acc-1"


def test_the_52_53_week_gap_is_why_tolerance_exists():
    """SEC says 2026-04-26, Argon says 2026-04-30. Exact matching finds nothing."""
    m, _ = match_publication(
        date(2026, 4, 30), [filing("2026-04-26", "2026-05-20")], version_count=1
    )
    assert m is not None
    m0, reason = match_publication(
        date(2026, 4, 30),
        [filing("2026-04-26", "2026-05-20")],
        version_count=1,
        tolerance_days=0,
    )
    assert m0 is None and reason == REASON_NO_FILING


def test_two_content_versions_refuse_before_looking_at_filings():
    m, reason = match_publication(
        date(2026, 4, 30), [filing("2026-04-26", "2026-05-20")], version_count=2
    )
    assert m is None and reason == REASON_MULTI_VERSION


def test_an_amendment_poisons_the_period():
    """The clause that keeps this honest: UW serves CURRENT data."""
    m, reason = match_publication(
        date(2004, 1, 31),
        [
            filing("2004-01-25", "2004-03-01", accession="orig"),
            filing("2004-01-25", "2004-05-20", form="10-K/A", accession="amd"),
        ],
        version_count=1,
    )
    assert m is None and reason == REASON_AMENDED


def test_an_amendment_outside_the_window_does_not_poison():
    m, reason = match_publication(
        date(2026, 4, 30),
        [
            filing("2026-04-26", "2026-05-20", accession="orig"),
            filing("2020-01-25", "2020-05-20", form="10-K/A", accession="old-amd"),
        ],
        version_count=1,
    )
    assert reason == REASON_MATCHED and m.accession == "orig"


def test_two_near_filings_without_an_exact_hit_are_ambiguous():
    m, reason = match_publication(
        date(2026, 4, 30),
        [
            filing("2026-04-26", "2026-05-20", accession="a"),
            filing("2026-05-04", "2026-06-01", accession="b"),
        ],
        version_count=1,
    )
    assert m is None and reason == REASON_AMBIGUOUS


def test_an_exact_hit_breaks_a_tie():
    m, reason = match_publication(
        date(2026, 4, 30),
        [
            filing("2026-04-30", "2026-05-20", accession="exact"),
            filing("2026-05-04", "2026-06-01", accession="near"),
        ],
        version_count=1,
    )
    assert reason == REASON_MATCHED and m.accession == "exact"


def test_no_filing_in_range_writes_nothing():
    m, reason = match_publication(
        date(2026, 4, 30), [filing("2025-04-26", "2025-05-20")], version_count=1
    )
    assert m is None and reason == REASON_NO_FILING


def test_empty_index_is_a_refusal_not_a_crash():
    m, reason = match_publication(date(2026, 4, 30), [], version_count=1)
    assert m is None and reason == REASON_NO_FILING


def test_a_filing_predating_its_own_period_is_corrupt_not_early():
    m, reason = match_publication(
        date(2026, 4, 30), [filing("2026-04-26", "2026-04-01")], version_count=1
    )
    assert m is None and reason == REASON_FILED_BEFORE_PERIOD
