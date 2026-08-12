"""Contract models for the per-ticker fundamental card (spec §7)."""

from __future__ import annotations

from datetime import date

from uw_scan.models._base import _preserve_public_module, _UwBase


class FundamentalSubscore(_UwBase):
    """One of the seven measured features.

    `value` is the RAW level (a ratio or a multiple), never a 0-100 rank — a rank
    is only meaningful against a stated cross-section, and this endpoint speaks
    about one name.
    """

    feature: str
    value: float | None
    # "ratio" renders as a percentage, "turns" as a multiple.
    unit: str
    # "higher_better" or null. Null for `gross_margin`, `op_margin` and `roe`:
    # the first two measured INVERTED and the third is named by no rubric row, so
    # no direction may be implied for them by color, arrow or ordering.
    direction: str | None
    # Non-empty means the value was computed but is not believed, and MUST render
    # as `na`. The check names are carried so the suppression is inspectable
    # rather than an unexplained blank.
    suppressed_by: list[str]


class FundamentalCoverage(_UwBase):
    """The explicit absence list. Mandatory, not a footer.

    `missing` and `suppressed` are kept apart on purpose: "never reported" and
    "reported and not believed" are different facts about a company.
    """

    features_present: int
    features_total: int
    missing: list[str]
    suppressed: list[str]


class FundamentalProvenance(_UwBase):
    engine_version: str
    inputs_hash: str
    as_of: date
    period_end: date
    # When the world could have known this figure. Consumers date the card by
    # THIS, not by `as_of`, which is a cross-section bucket.
    knowledge_date: date
    # False means `knowledge_date` came from the 45-day filing fallback rather
    # than a real filing date.
    filing_date_known: bool
    source_obs_count: int


class FundamentalCardResponse(_UwBase):
    """The deterministic blocks of §7. The valuation anchor, narrative and audit
    blocks are absent rather than empty — they need stages 3-5."""

    ticker: str
    # A cross-sectional z-mean under the active method. Valid as a SORT KEY only
    # across the wide tier, and never as an expected return: the 2026-08-12 cost
    # study measured zero gross alpha at every slice.
    composite: float | None
    subscores: list[FundamentalSubscore]
    coverage: FundamentalCoverage
    provenance: FundamentalProvenance


_preserve_public_module(
    FundamentalSubscore,
    FundamentalCoverage,
    FundamentalProvenance,
    FundamentalCardResponse,
)
