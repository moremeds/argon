"""A cross-section may only contain information that has actually become public.

Every ticker, period end, and filing date below was read from the production
`fundamental_scores` table on 2026-08-23 and frozen. EXTR, COHR, TEAM and DMRC
all filed for period_end 2026-06-30; AMAT and CSCO had not filed for period_end
2026-07-31, so `_knowledge_date` estimated `period_end + FALLBACK_LAG_DAYS` and
produced 2026-09-14 — three weeks past the run date. That estimate is what put
371 rows across 363 tickers into the future and shadowed six days of fresher
scores behind `ORDER BY as_of DESC`.

Nothing here touches the network, the clock, or a database: `_build_buckets` is
pure, and the cutoff is passed in.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from uw_scan.worker.jobs.fundamental_scoring import _build_buckets

# The day the production damage was measured.
RUN_DATE = date(2026, 8, 23)

FILED = {
    "EXTR": ("2026-06-30", "2026-08-17"),
    "COHR": ("2026-06-30", "2026-08-14"),
    "TEAM": ("2026-06-30", "2026-08-14"),
}
# Real filings exist for neither, so both fall back to period_end + 45d = 2026-09-14.
UNFILED = {"AMAT": "2026-07-31", "CSCO": "2026-07-31"}


def _panel() -> tuple[dict[str, Any], dict[str, Any]]:
    feats: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for ticker, (period, filed) in FILED.items():
        feats[ticker] = {period: {"roe": 0.1}}
        raw[ticker] = {"filing_dates": {period: filed}, "obs_ids": {period: [1]}}
    for ticker, period in UNFILED.items():
        feats[ticker] = {period: {"roe": 0.1}}
        raw[ticker] = {"filing_dates": {}, "obs_ids": {period: [2]}}
    return feats, raw


def test_an_unarrived_estimate_is_withheld() -> None:
    buckets, withheld = _build_buckets(*_panel(), knowledge_cutoff=RUN_DATE)
    assert withheld == 2
    assert set(buckets["2026Q3"]) == {"EXTR", "COHR", "TEAM"}


def test_the_bucket_is_not_stamped_with_a_future_date() -> None:
    """The regression itself: `as_of` is the bucket max, so one future row poisons it."""
    buckets, _ = _build_buckets(*_panel(), knowledge_cutoff=RUN_DATE)
    as_of = max(d["knowledge_date"] for d in buckets["2026Q3"].values())
    assert as_of == date(2026, 8, 17)  # EXTR, the latest that had actually arrived
    assert as_of <= RUN_DATE


def test_without_the_cutoff_the_future_row_would_win() -> None:
    """Proves the fixture reproduces the bug — a control, not a tautology."""
    buckets, withheld = _build_buckets(*_panel(), knowledge_cutoff=date(2027, 1, 1))
    assert withheld == 0
    as_of = max(d["knowledge_date"] for d in buckets["2026Q3"].values())
    assert as_of == date(2026, 9, 14)


def test_the_cutoff_is_a_parameter_not_the_wall_clock() -> None:
    """Backdating withholds names that a later run admits — replay stays honest."""
    buckets, withheld = _build_buckets(*_panel(), knowledge_cutoff=date(2026, 8, 15))
    assert withheld == 3  # AMAT, CSCO, and EXTR (filed 08-17, after this cutoff)
    assert set(buckets["2026Q3"]) == {"COHR", "TEAM"}


def test_one_name_still_gets_one_vote_per_quarter() -> None:
    """Regression guard on the extraction: the fresher period wins, both never run."""
    feats, raw = _panel()
    feats["COHR"]["2026-03-31"] = {"roe": 0.2}
    raw["COHR"]["filing_dates"]["2026-03-31"] = "2026-08-10"
    raw["COHR"]["obs_ids"]["2026-03-31"] = [3]

    buckets, _ = _build_buckets(feats, raw, knowledge_cutoff=RUN_DATE)
    assert buckets["2026Q3"]["COHR"]["period"] == "2026-06-30"
