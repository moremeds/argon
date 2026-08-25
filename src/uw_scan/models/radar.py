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
