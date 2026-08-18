"""Contract models for the per-ticker fundamental card (spec §7)."""

from __future__ import annotations

from datetime import date

from uw_scan.models._base import _preserve_public_module, _UwBase


class FundamentalPercentile(_UwBase):
    """Where a value sits in its knowledge-quarter panel.

    Locational only. Not a quality score and not an expected return — the
    2026-08-12 cost study measured zero gross alpha from this composite at every
    slice. `n` is stated per feature because it differs: a name missing `roe` is
    absent from that panel while present in the others, and a percentile whose
    denominator is unnamed is not a fact.
    """

    percentile: float
    n: int


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
    # Oldest-first, aligned to `series_dates`. `null` marks a quarter whose input
    # was flagged, so a renderer draws a GAP rather than interpolating through a
    # figure we do not believe. Empty when history was not requested.
    series: list[float | None] = []
    percentile: FundamentalPercentile | None = None


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


class FundamentalAnchors(_UwBase):
    """A price band from this name's OWN valuation history (spec §5.3, stage 3).

    Each level is the price at which this company's valuation yield would sit at
    a stated percentile of its own past: `buy_below` at the 80th (cheap),
    `risk_above` at the 20th. Ascending in price, enforced by a schema CHECK.

    Measured basis (2026-08-12): `sales_to_ev` carries a market-neutral 2q IC of
    +0.0744 (t 5.77) within-ticker, rising to +0.0826 when a pure-reversal
    control is held constant.

    OWN-HISTORY, NEVER CROSS-SECTIONAL — the distinction is the whole result.
    Ranking a name against OTHER names on value is INVERTED in this universe
    (`book_to_price` IC -0.0365, t -2.32), so a peer-ranked `buy_below` would
    point at the half of the panel that then underperforms.

    Not a forecast, and no scenario grid: §7's base/bear/bull x 1y/3y needs a
    validated growth model and there is none.
    """

    company_type: str
    # The yield the band was built from: sales_to_ev | fcf_yield | ebitda_to_ev.
    method: str
    # Null where the yield inversion diverges or lands below zero after net debt.
    # A null level is unknown, not zero, and must not be drawn as a boundary.
    buy_below: float | None = None
    observe_low: float | None = None
    observe_mid: float | None = None
    observe_high: float | None = None
    risk_above: float | None = None
    # Spot at compute time, and where it sat in this name's own yield history.
    # High = cheap versus its own past, because every method is a yield.
    spot: float | None = None
    spot_percentile: float | None = None
    history_quarters: int
    confidence: str
    # Every reason, never collapsed to the badge. "medium because the filing is
    # 180 days old" is actionable; "medium" is not. Non-empty with all levels
    # null means the band was REFUSED, and the reason says why.
    confidence_reasons: list[str] = []
    as_of: date


class FundamentalCardResponse(_UwBase):
    """The deterministic blocks of §7. The narrative and audit blocks are absent
    rather than empty — they need stages 4-5."""

    ticker: str
    # A cross-sectional z-mean under the active method. Valid as a SORT KEY only
    # across the wide tier, and never as an expected return: the 2026-08-12 cost
    # study measured zero gross alpha at every slice.
    composite: float | None
    composite_series: list[float | None] = []
    composite_percentile: FundamentalPercentile | None = None
    # Shared x-axis for every series on the card: one knowledge_date per quarter,
    # oldest first. One axis for all eight lines keeps them comparable.
    series_dates: list[str] = []
    # Names in the knowledge-quarter panel the percentiles were computed against.
    panel_size: int = 0
    subscores: list[FundamentalSubscore]
    # Absent when the name is unrouted (no company_type) or has no band row yet.
    # Absent, never an empty band: an empty band would assert "no view", which is
    # a claim about the company rather than about our coverage.
    anchors: FundamentalAnchors | None = None
    coverage: FundamentalCoverage
    provenance: FundamentalProvenance


class FundamentalComponentSeries(_UwBase):
    """One plotted series on a card's back.

    `role` separates the figures the ratio is COMPUTED FROM from those merely
    shown alongside it. Only `input` series participate in the reconciliation
    invariant, so a renderer must not blend the two into one visual class.
    """

    key: str
    label: str
    # "input" | "context"
    role: str
    # "currency" | "ratio" | "turns"
    unit: str
    values: list[float | None]


class FundamentalFeatureDetail(_UwBase):
    """One feature's components and the ratio they produce.

    `basis` is stated per feature because it is not uniform: `gross_margin` and
    `op_margin` are quarterly, the rest are TTM or mix a TTM flow with a
    point-in-time balance. An unlabelled shared axis would invite a comparison
    none of them support.
    """

    feature: str
    # "ttm" | "quarterly" | "mixed"
    basis: str
    unit: str
    series: list[FundamentalComponentSeries]
    # Oldest-first, aligned to `period_ends`. Null where an input was absent —
    # never 0, which is a figure rather than an absence.
    ratio: list[float | None]


class FundamentalStatementsResponse(_UwBase):
    """The back-side payload for one ticker.

    Components are resolved server-side and the client performs no ratio math.
    A client-side re-derivation would be a second copy of `build_features`, and
    the two would drift until the back silently contradicted the front.
    """

    ticker: str
    period_ends: list[str]
    # Per the filer. TSM files TWD against a USD ADR quote, so an unlabelled
    # axis is the same defect that produced a negative enterprise value here.
    reported_currency: str | None
    features: list[FundamentalFeatureDetail]


class FundamentalConcentrationFamily(_UwBase):
    """The reported top-member share on one axis family, for one period.

    Carries its own `report_date`: a filer may publish a geography cut every
    quarter and a segment cut only annually, so the two families legitimately
    date differently and one shared as-of would misdate one of them.

    `top_member` is the RAW XBRL member string. Filers mix `country:US` with
    custom members like `nvda:ChinaIncludingHongKongMember` and with continent
    aggregates; the share is defensible, a beautified label would not be.
    """

    # The XBRL axis the partition was taken on, e.g.
    # 'us-gaap:StatementBusinessSegmentsAxis'.
    axis: str
    # "all" when the published members sum to the period total; "subset:N" when
    # a coarser level had to be recovered. Rendered so a reader can tell which.
    level: str
    n_members: int
    top_member: str
    top_share: float
    report_date: str


class FundamentalConcentrationPoint(_UwBase):
    """One period of the trend. Null where the family did not resolve — never 0,
    which would read as "no concentration" rather than "not disclosed"."""

    report_date: str
    segment_top_share: float | None
    geography_top_share: float | None


class FundamentalConcentrationResponse(_UwBase):
    """Revenue concentration for one name. DESCRIPTIVE ONLY.

    This is not an edge and nothing here may become a composite input. Measured
    over 401 tickers, the top share moves a median 1.20pp per quarter against
    annual/quarterly basis contamination of median 2.5pp and p90 17.5pp — the
    level is a public, filing-lagged, highly persistent characteristic, which is
    a factor loading rather than alpha. No rank, no percentile against other
    names, no score.
    """

    ticker: str
    # Absent, never an empty family: absence is about our coverage, an empty
    # band would be a claim about the company.
    segment: FundamentalConcentrationFamily | None = None
    geography: FundamentalConcentrationFamily | None = None
    # Oldest first, annual periods excluded.
    trend: list[FundamentalConcentrationPoint] = []
    # Excluded from the trend but reported, so a reader comparing against the
    # filer's own history can see the period existed and was filtered.
    dropped_annual_periods: list[str] = []
    # Which derivation produced the shares. The rules are new and one has
    # already been corrected once against real data.
    derivation_version: str


_preserve_public_module(
    FundamentalPercentile,
    FundamentalSubscore,
    FundamentalCoverage,
    FundamentalProvenance,
    FundamentalAnchors,
    FundamentalCardResponse,
    FundamentalComponentSeries,
    FundamentalFeatureDetail,
    FundamentalStatementsResponse,
    FundamentalConcentrationFamily,
    FundamentalConcentrationPoint,
    FundamentalConcentrationResponse,
)
