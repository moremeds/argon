"""Does one stored content version earn a publication date? Pure rule, no I/O.

`capture_bounded` says "Argon first saw this on date X". `true_pit` says "the
world could see this on date X". Only the second supports a leak-free replay,
and only SEC can supply it. This module decides, for one statement identity,
whether SEC's filing index licenses that upgrade — and refuses by default.

THE RULE, AND WHY EACH CLAUSE EXISTS
------------------------------------
A version earns `true_pit` only when ALL FOUR hold:

1. **exactly one content version for the identity.** With two or more, Argon
   holds several hashes for the same quarter and cannot tell which one the
   filing published. Dating any of them at the filing is a coin flip.
2. **exactly one non-amendment periodic filing within +/-7 days of
   `period_end`.** Two matches means the window caught a neighbouring quarter;
   the answer is refusal, not the nearer one.
3. **no amendment for that period.** This is the clause that makes the whole
   thing honest. UW serves CURRENT data: if a company restated, the single
   version Argon stores may be the restated content. Stamping it with the
   ORIGINAL filing's date is precisely `filing_published_at`'s trap, wearing
   SEC's authority instead of UW's.
4. **the filing is not dated before the period it reports.** A filing that
   predates its own period end is corrupt evidence, not early evidence.

Anything else writes NO claim. The observation keeps `capture_bounded` and every
existing reader behaves exactly as it did before.

WHY +/-7 DAYS AND NOT ZERO
--------------------------
SEC's `reportDate` and Argon's `period_end` disagree on 52/53-week fiscal
calendars: NVDA's April 2026 quarter is `2026-04-26` at SEC and `2026-04-30`
here. Measured on NVDA's 82 quarterly periods, an exact join matched 11 (13.4%)
and a +/-7-day join matched 77 (93.9%). This is the SAME mismatch already
documented between UW's statement endpoints and `fundamental-breakdown`, where
exact matching returned 0 of 885. The tolerance is reused deliberately; a second
independent tolerance would be a second thing to get wrong.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from uw_scan.sources.sec_submissions import SecFiling

#: Same tolerance as the UW period-key reconciliation. Exact match wins first.
PUBLICATION_TOLERANCE_DAYS = 7

#: Bumping the rule means a NEW key, never a rewrite: claims are append-only, so
#: two rule versions coexist and their disagreement stays inspectable.
CLAIM_KEY_SEC_PUBLICATION = "sec:publication:v1"

SOURCE_SEC_EDGAR = "sec_edgar"

#: Refusal slugs. Every one is a counter name in the job, so a run reports WHY
#: it refused rather than only how often — a bare "matched 60%" cannot tell a
#: coverage gap from a universe of serial restaters.
REASON_MATCHED = "matched"
REASON_MULTI_VERSION = "multi_version"
REASON_AMENDED = "amended"
REASON_AMBIGUOUS = "ambiguous"
REASON_NO_FILING = "no_filing"
REASON_FILED_BEFORE_PERIOD = "filed_before_period"

REFUSAL_REASONS = (
    REASON_MULTI_VERSION,
    REASON_AMENDED,
    REASON_AMBIGUOUS,
    REASON_NO_FILING,
    REASON_FILED_BEFORE_PERIOD,
)


@dataclass(frozen=True)
class PublicationMatch:
    """The filing that dates a content version."""

    accession: str
    filing_date: date


def _within(a: date, b: date, tolerance: int) -> bool:
    return abs((a - b).days) <= tolerance


def match_publication(
    period_end: date,
    filings: Sequence[SecFiling],
    *,
    version_count: int,
    tolerance_days: int = PUBLICATION_TOLERANCE_DAYS,
) -> tuple[PublicationMatch | None, str]:
    """Return `(match, reason)` for one identity. `match` is None unless matched.

    `version_count` is how many content hashes Argon holds for the identity —
    the caller counts them, because this module never touches SQL.
    """
    if version_count != 1:
        return None, REASON_MULTI_VERSION

    # Clause 3 first: an amendment anywhere near the period poisons it, and
    # checking it before the match keeps a matched-then-rejected period from
    # being counted as ambiguous.
    amended = [
        f
        for f in filings
        if f.is_amendment and _within(f.report_date, period_end, tolerance_days)
    ]
    if amended:
        return None, REASON_AMENDED

    candidates = [
        f
        for f in filings
        if not f.is_amendment and _within(f.report_date, period_end, tolerance_days)
    ]
    if not candidates:
        return None, REASON_NO_FILING

    if len(candidates) > 1:
        # Exact first, per the existing period-key rule. Only an exact hit
        # breaks a tie; two filings equidistant from the period end are a
        # genuine ambiguity and get refused rather than sorted arbitrarily.
        exact = [f for f in candidates if f.report_date == period_end]
        if len(exact) != 1:
            return None, REASON_AMBIGUOUS
        candidates = exact

    winner = candidates[0]
    if winner.filing_date < period_end:
        return None, REASON_FILED_BEFORE_PERIOD

    return PublicationMatch(winner.accession, winner.filing_date), REASON_MATCHED
