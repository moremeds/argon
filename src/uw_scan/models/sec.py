"""SEC filing record shared by the SEC source, the filing-index store and the
publication-evidence derivation. Lives here, not in ``sources``, so ``storage``
does not import ``sources`` (I-30). Internal: not part of the API contract and
not re-exported from ``uw_scan.models``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SecFiling:
    """One periodic filing. Frozen and hashable so a caller can dedupe archives.

    `report_date` is SEC's `reportDate` — the fiscal period the filing covers,
    which is NOT reliably equal to Argon's `period_end` (52/53-week calendars
    disagree by a few days). `filing_date` is when it became public.
    """

    accession: str
    form: str
    report_date: date
    filing_date: date
    is_amendment: bool
