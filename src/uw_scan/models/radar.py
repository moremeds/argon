"""Contract models for the Fundamental PM Research Radar and company v2 (M4).

THE STATE MODEL IS THE POINT OF THIS FILE
------------------------------------------
Six outcomes must be distinguishable by a caller, because each has a different
correct response and four of them are currently indistinguishable from "empty":

`ok`                     a compatible result exists and is fresh.
`no_coverage`            Argon holds no statements for this name at all.
`no_compatible_run`      statements exist; nothing has been computed under the
                         requested as-of / evidence policy / engine.
`stale_run`              a compatible run exists but its inputs have moved on.
`unsupported_capability` the request names something Argon cannot answer under
                         any run — a leak-free replay before a name's first
                         `true_pit` claim, for instance.
`failed_run`             a run was attempted and errored.

Collapsing these into an empty list is how "the job never ran" gets read as "this
company has no fundamentals", which is a statement about a real business that
Argon is not entitled to make. Transport errors are HTTP-level and deliberately
NOT a member here: a 500 must not arrive dressed as a data state.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from uw_scan.models._base import _preserve_public_module, _UwBase

#: See the module docstring. Ordered from strongest to weakest evidence.
FundamentalResultState = Literal[
    "ok",
    "stale_run",
    "no_compatible_run",
    "no_coverage",
    "unsupported_capability",
    "failed_run",
]

#: Spec §6.4's ladder, mirrored into the contract. `investment_ranking` is
#: deliberately absent: it is not a level this program can emit, so it must not
#: be expressible in the type a client switches on.
ClaimAuthority = Literal["descriptive", "research_priority", "directional_monitor"]


class RadarDimension(_UwBase):
    """One dimension for one name, with the permission it may exercise.

    `value` is null when no input was present — never 0.0, which is the
    cross-section MEAN and would render a name with no data as exactly average.
    `inputs_present`/`inputs_expected` are what let a surface show the
    denominator instead of a confident-looking blank.
    """

    dimension: str
    value: float | None
    inputs_present: int
    inputs_expected: int
    authority: ClaimAuthority
    #: Dimension-specific extras — `used`/`missing` for the aggregate,
    #: `true_pit`/`observations` for evidence quality.
    detail: dict = {}


class FundamentalRunRef(_UwBase):
    """Which computation produced this answer.

    Every number a surface shows must trace to one of these. A response with a
    null `run_id` is answering from the warm store without a ledgered run, which
    a caller is entitled to know.
    """

    run_id: int | None
    engine_version: str | None
    evidence_policy: str
    as_of: date | None
    as_of_cutoff: datetime | None
    computed_at: datetime | None
    status: str | None


class CompanyDimensionsResponse(_UwBase):
    """Company view v2: dimensions plus the state that explains their absence."""

    ticker: str
    state: FundamentalResultState
    #: Present and non-empty only when `state == "ok"` or `"stale_run"`.
    dimensions: list[RadarDimension] = []
    run: FundamentalRunRef | None = None
    #: Why the state is what it is, in the operator's words. Always populated for
    #: a non-ok state — a state with no reason is a shrug with a schema.
    reason: str | None = None
    #: Share of this result's observations carrying a `true_pit` claim.
    evidence_coverage: float | None = None


class RadarRow(_UwBase):
    """One name on the Radar.

    `priority` is separated from the dimensions it aggregates so a client cannot
    accidentally render a descriptive dimension as the sort key.
    """

    ticker: str
    company_type: str | None
    #: null when the aggregate REFUSED (too few present dimensions).
    priority: float | None
    priority_authority: ClaimAuthority
    #: Named so a partial name stays visible with its denominator rather than
    #: being dropped for looking incomplete.
    dimensions_present: int
    dimensions_expected: int
    missing_dimensions: list[str] = []
    dimensions: list[RadarDimension] = []
    evidence_coverage: float | None = None
    as_of: date | None = None
    #: Change in `priority` since the prior compatible run, when there is one.
    priority_change: float | None = None
    #: Dimensions whose z-score exceeds `EXTREME_Z`. Surfaced, never suppressed:
    #: winsorizing would change validated math and dropping the row would hide a
    #: real name, but an unmarked 18-sigma reading at the top of a descending
    #: sort invites the reader to treat volatility as conviction. Measured on the
    #: local panel: |z|>10 is 0.03-0.3% of rows per dimension.
    extreme_dimensions: list[str] = []


class RadarScope(_UwBase):
    """The frozen question this Radar answers.

    Persisted with the response rather than implied by the request, because a
    screenshot of a Radar with no scope is unfalsifiable — and because mixing two
    as-ofs or two engine versions in one table is the failure this exists to make
    impossible to render by accident.
    """

    universe: str
    tier: str
    as_of: date | None
    evidence_policy: str
    engine_version: str | None
    names: int
    #: Names in the tier with no compatible result, reported rather than dropped.
    names_without_result: int


class RadarResponse(_UwBase):
    """The Radar data product.

    `ordering` names the claim registry key that licenses the sort. A client that
    re-sorts on anything else is exceeding a permission, and the field is here so
    that is checkable rather than a convention.
    """

    scope: RadarScope
    rows: list[RadarRow]
    ordering: str
    ordering_authority: ClaimAuthority
    #: Wording constraints from the claim registry, so the UI does not have to
    #: carry its own copy and drift from it.
    prohibited: list[str] = []
    state: FundamentalResultState = "ok"
    reason: str | None = None


_preserve_public_module(
    RadarDimension,
    FundamentalRunRef,
    CompanyDimensionsResponse,
    RadarRow,
    RadarScope,
    RadarResponse,
)


class ChainCell(_UwBase):
    """One chain × layer cell of the research matrix.

    `members` is the DENOMINATOR and `with_result` the numerator. A cell showing
    an aggregate without both is unreadable: a mean over 2 of 17 members and a
    mean over 17 of 17 look identical and mean opposite things.
    """

    chain: str
    layer: str
    domain: str
    layer_rank: int
    members: int
    with_result: int
    #: Mean priority over members carrying a compatible result. Null when the
    #: cell abstains — which is a state, not a gap.
    priority_mean: float | None = None
    #: Members whose exposure carries a DISCLOSED magnitude. Measured at 4 of 316
    #: across the seeded taxonomy, so this is usually 0 and that is the finding.
    with_magnitude: int = 0
    #: Why the cell abstained, when it did.
    abstain_reason: str | None = None


class ChainMatrixResponse(_UwBase):
    """The chain × layer matrix under one taxonomy version and one engine.

    Both versions travel with the payload because mixing two taxonomy snapshots
    or two engine versions in one matrix is the failure this product exists to
    make impossible to render by accident.
    """

    taxonomy_version: str
    engine_version: str | None
    cells: list[ChainCell]
    #: Chain-level exposure coverage: members / with_exposure / with_magnitude.
    coverage: dict = {}
    state: FundamentalResultState = "ok"
    reason: str | None = None
    #: What a chain aggregate may not be read as. Chain membership is measured to
    #: be a sector by another name, so no propagation claim is licensed.
    prohibited: list[str] = []


class ChainMember(_UwBase):
    ticker: str
    layer: str
    evidence_class: str
    approved_by: str
    role: str | None = None
    direction: str | None = None
    magnitude: float | None = None
    magnitude_basis: str | None = None
    exposure_status: str | None = None
    source_ref: str | None = None
    priority: float | None = None


class ChainDrilldownResponse(_UwBase):
    taxonomy_version: str
    chain: str
    layer: str | None
    members: list[ChainMember]
    state: FundamentalResultState = "ok"
    reason: str | None = None


_preserve_public_module(ChainCell, ChainMatrixResponse, ChainMember, ChainDrilldownResponse)


class ResearchEvent(_UwBase):
    """One typed event. Both clocks travel with it.

    `occurred_at` is when it happened; `first_known_at` is when Argon could know.
    A historical read predicates on the second, or a replay sees events before
    they were knowable.
    """

    event_id: int
    event_class: str
    occurred_at: date
    first_known_at: date
    title: str
    detail: dict = {}
    source_kind: str
    source_ref: str | None = None
    superseded_by: int | None = None


class RiskFact(_UwBase):
    """A number against a threshold, and what a breach invalidates.

    Never prose. A risk expressed only as a sentence cannot be checked, replayed,
    or shown to have improved.
    """

    risk_kind: str
    observed_value: float | None
    threshold: float | None
    breached: bool
    severity: str
    statement: str
    #: Which computation the breach makes untrustworthy. Null = descriptive.
    invalidates: str | None = None
    source_kind: str
    as_of: date


class EventClassStatus(_UwBase):
    """The discovery gate's verdict for one candidate class.

    A `killed` class is not a missing feature — it is a measured absence of
    source, and `rationale` says which.
    """

    event_class: str
    status: str
    source_table: str | None = None
    rationale: str
    measured_rows: int | None = None


class CompanyEvidenceResponse(_UwBase):
    """Events + deterministic risks for one name, with the gate that bounds them."""

    ticker: str
    events: list[ResearchEvent] = []
    risks: list[RiskFact] = []
    #: Classes that cannot produce an event here, and why. Rendered rather than
    #: omitted: a timeline with no supply-chain events looks complete unless the
    #: reader is told that class was killed for want of a source.
    killed_classes: list[EventClassStatus] = []
    state: FundamentalResultState = "ok"
    reason: str | None = None


_preserve_public_module(
    ResearchEvent, RiskFact, EventClassStatus, CompanyEvidenceResponse
)
