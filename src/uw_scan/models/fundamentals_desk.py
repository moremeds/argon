"""Contract models for the fundamentals industry desk (spec §2–§4).

WHAT IS ABSENT FROM THESE MODELS IS THE DESIGN
------------------------------------------------
The desk LISTS; it never RANKS. No model here carries `rank`, `score`,
`composite`, `percentile_rank`, or `sort`, and no endpoint accepts an
ordering parameter — because the ordering a caller would reach for is a
measured-inverted claim. Cross-sectional value measured INVERTED in this
universe (`book_to_price` IC -0.0365, t -2.32) while own-history value is the
one thing that works (`sales_to_ev` within-ticker IC +0.0744, t 5.77); the
cross-sectional composite correlates 0.89 with its own growth input and is a
disguised growth screen. An added `sort` would ship the refuted claim under
the validated one's name and nothing about the response SHAPE would show it.
So the shape is the guard, and `tests/integration/api/
test_fundamentals_desk_api.py` pins it.

`ProfitPoolLayer` likewise has no field for arrows, edges, propagation, or
read-through, by design: the hyperscaler-capex → supplier-revenue timing
edge was tested and did not validate (`docs/research/2026-08-13-ai-capex-
demand-ledger/`, headline 0.59 collapsing to 0.25 matched-growth). The page
may show layers side by side; it may not draw arrows, and a model with an
`edges` field is an invitation to.

ABSENCE IS A STATEMENT, NOT A GAP
-----------------------------------
Every nullable field here means "Argon does not have this", never zero and
never a carry-forward. `coverage_missing` NAMES the missing tickers rather
than reporting `12/18`, because "12/18" is decoration and "missing: COHR,
LITE" is actionable. `percentile_state` carries the six-state
`FundamentalResultState` so a null percentile can say WHICH kind of nothing
it is — `no_compatible_run` is not `no_coverage`.
"""

from __future__ import annotations

from datetime import date

from uw_scan.models._base import _preserve_public_module, _UwBase
from uw_scan.models.radar import FundamentalResultState


class DeskCalendarRow(_UwBase):
    """One upcoming print, placed in the chain.

    The row is grained `(ticker, report_date, chain, layer)` — membership's own
    grain. A name in two chains appears twice, each time under the chain whose
    read-through order put it there; collapsing to one row would require
    picking a chain for it, which is a judgement the desk has no basis to make
    and would hide the other membership entirely.
    """

    ticker: str
    report_date: date
    #: 'premarket' | 'afterhours' | None. NULL is a REAL third value — the ~2%
    #: of names UW reports as `report_time: "unknown"`, which appear in
    #: neither classified slot. Never guess one.
    session: str | None
    chain: str
    layer: str
    layer_rank: int
    #: None = not covered by the option-surface snapshot, rendered as such.
    implied_move_pct: float | None
    implied_move_asof: date | None
    #: Last <=4 realised print moves, newest first. An empty list is "no
    #: reaction history", which is not "flat".
    reactions: list[float] = []
    #: Own-history YIELD percentile: 0.80 = CHEAP. Never a cross-sectional
    #: rank, and never an ordering key.
    spot_percentile: float | None = None
    #: "ok" when a percentile is present; otherwise which of the six states
    #: explains its absence.
    percentile_state: FundamentalResultState = "ok"


class DeskCalendarResponse(_UwBase):
    section: str
    #: The date the list is current AS OF — also the floor: rows are prints on
    #: or after it. A print that has happened is history, not calendar.
    as_of: date
    #: report_date ASC, then layer_rank ASC — chain order is read-through
    #: order, which a generic calendar cannot say. Fixed regardless of filter.
    rows: list[DeskCalendarRow] = []


class DeltaRailEvent(_UwBase):
    """One entry on the "what changed since you last looked" rail.

    `first_known_at` is a DATE, not a timestamp: `research_events.first_known_at`
    is a `date` column (migration 142), and rendering it as an instant at
    midnight would manufacture a precision the ledger does not hold.
    """

    event_class: str
    ticker: str
    occurred_at: date
    first_known_at: date
    title: str
    #: The event's own payload, plus `also` when a second class fired for the
    #: same fact and was collapsed into this entry.
    detail: dict = {}


class DeltaRailResponse(_UwBase):
    since: date
    #: Ordered `first_known_at` DESC — the desk's KNOWLEDGE clock, not the
    #: world's. "What changed" is a question about what Argon learned.
    events: list[DeltaRailEvent] = []


class MemberDot(_UwBase):
    """One name's value inside a chain cell. One dot per DISTINCT ticker.

    `value` is null when the name has no figure — never 0.0, which would put a
    name with no data at whatever the reader takes zero to mean.
    """

    ticker: str
    value: float | None
    state: FundamentalResultState
    #: Whether this figure's knowledge date was ESTIMATED rather than filed.
    #: True  = `period_end + FALLBACK_LAG_DAYS`, which errs EARLY for late
    #:         filers and therefore manufactures look-ahead (measured:
    #:         composite IC 0.059 with the fallback against 0.039 without).
    #: False = a real filing date.
    #: None  = this dot has no knowledge date at all (a valuation percentile
    #:         is not a filed figure), which is not the same as "filed".
    #:
    #: Carried, never filtered on: showing a knowledge-dated figure without
    #: saying whether the date is real presents an estimate as a fact, while
    #: filtering the estimated rows out is a research concern no consumer of
    #: this surface has asked for.
    knowledge_date_estimated: bool | None = None


class CohortSlice(_UwBase):
    """One cross-section bucket a chain's members sit in.

    `fundamental_scores.as_of` is a cross-section IDENTIFIER, not a freshness
    stamp. When members straddle two buckets that is reporting season, and
    merging them would compare names that were never in the same peer group.
    """

    as_of: date
    #: 'reported' for the newest bucket present, 'awaiting' for every older one.
    label: str
    tickers: list[str] = []


class ChainMetricCell(_UwBase):
    """One chain × metric cell.

    `median` is the UNWEIGHTED median of the non-null dot values. Never
    revenue-weighted: a revenue-weighted "optical" margin is one member's
    margin wearing the chain's label, measured as actively misleading.

    For `metric='valuation_percentile'` the median is ALWAYS None. Own-history
    percentiles are NAME facts; any aggregate over them is the banned "chain
    percentile distribution" (spec §3) — the dots still render, because the
    name-level facts are real.
    """

    chain: str
    #: 'rev_yoy' | 'gross_margin' | 'valuation_percentile'
    metric: str
    median: float | None = None
    dots: list[MemberDot] = []
    #: >=2 entries iff the chain's members straddle as_of buckets.
    cohorts: list[CohortSlice] = []
    #: NAMED missing DISTINCT tickers — never a bare count. "12/18" is
    #: decoration; "missing: COHR" is actionable.
    coverage_missing: list[str] = []
    #: DISTINCT tickers. `chain_membership` is (chain, layer, ticker)-grained,
    #: so a name in two layers is two rows and must count ONCE.
    members_total: int = 0


class DeskMatrixResponse(_UwBase):
    section: str
    #: Ordered by each chain's minimum `layer_rank`, ties alphabetically —
    #: never by any metric.
    chains: list[str] = []
    cells: list[ChainMetricCell] = []


class ProfitPoolLayer(_UwBase):
    """Where gross profit sits, layer by layer. Descriptive only.

    NO field for arrows, edges, propagation, or read-through exists here, by
    design — see the module docstring.
    """

    chain: str
    layer_rank: int
    median_gross_margin: float | None = None
    median_rev_yoy: float | None = None
    dots: list[MemberDot] = []


class MembershipEvidenceCount(_UwBase):
    """How many memberships rest on each class of evidence.

    Counted at MEMBERSHIP grain deliberately — this is a statement about the
    taxonomy's evidential footing, not about how many companies there are.
    """

    #: 'disclosed' | 'analyst' | 'mirrored' | 'inferred'
    evidence_class: str
    memberships: int


class ChainExposureCoverage(_UwBase):
    """Three denominators, because they answer three different questions and a
    surface showing only the first invites the reader to assume the third."""

    chain: str
    members: int
    with_exposure: int
    with_magnitude: int


class DeskLimitsResponse(_UwBase):
    """What the desk cannot say, computed rather than asserted (spec §3f).

    THE NI FIELDS ARE DESCRIPTIVE AND MUST NEVER BE LABELLED PASS/FAIL.
    Task 10's premise — that an income-vs-cash-flow net-income disagreement is
    a data-integrity failure — was DISPROVED. Income-statement `net_income` is
    attributable-to-parent post-discontinued-ops; the cash-flow statement
    opens from consolidated NI INCLUDING noncontrolling interests (ASC 230
    indirect). A disagreement is usually correct accounting on BOTH sides —
    measured on 342 of 419 tickers, worked case VZ 2010-Q3 where 2,698M =
    881M + 1,817M NCI. Argon stores no NCI field and therefore CANNOT
    attribute the difference. Never name these pass/fail/offender and never
    render them as an integrity error.
    """

    #: The two statements' net income matches.
    ni_basis_agree: int = 0
    #: They differ — NOT an error. See the class docstring.
    ni_basis_differ: int = 0
    #: Named tickers, largest number of differing periods first.
    ni_largest_basis_differences: list[str] = []
    #: The one GENUINE integrity check on this axis, separate and rare:
    #: a literal sign inversion between the two statements (measured 5 of
    #: 28,973 rows). This one IS a violation and is labelled as such.
    ni_sign_flip_violations: int = 0
    #: Spec §3f's fixed sentence — legitimately prose, because the reason a
    #: number is withheld is not itself a number.
    withheld_composite: str = ""
    #: Membership semantics as NUMBERS (spec §3f: computed, not prose); the
    #: web layer writes captions OVER these, never instead of them.
    membership_evidence: list[MembershipEvidenceCount] = []
    exposure_coverage: list[ChainExposureCoverage] = []


class NodeUnderwritingRow(_UwBase):
    """One name's underwriting figures WITH their filed line items.

    Spec §4 trust requirement #1: the raw values and the filing date travel
    with the figure rather than behind another request. The PM trust ranking
    put traceability first — one untraceable number kills the page, while
    traceability survives several wrong ones.

    `shares_outstanding_yoy` is BASIC period-end shares (`common_stock_shares_
    outstanding`, 420/420 coverage), not a diluted weighted-average count —
    no diluted share key exists at any tier of the UW store, verified
    exhaustively. It measures issuance/buyback, not dilution, and the word
    "diluted" must never appear over it.
    """

    ticker: str
    period_end: date
    dio: float | None = None
    sbc_to_revenue: float | None = None
    shares_outstanding_yoy: float | None = None
    filing_published_at: date | None = None
    #: Verbatim `raw_jsonb` strings — the filed line items themselves, copied
    #: not reformatted, so the figure above can be checked against them.
    inventory_raw: str | None = None
    cost_of_revenue_raw: str | None = None
    sbc_raw: str | None = None
    shares_outstanding_raw: str | None = None
    state: FundamentalResultState = "ok"


_preserve_public_module(
    DeskCalendarRow,
    DeskCalendarResponse,
    DeltaRailEvent,
    DeltaRailResponse,
    MemberDot,
    CohortSlice,
    ChainMetricCell,
    DeskMatrixResponse,
    ProfitPoolLayer,
    MembershipEvidenceCount,
    ChainExposureCoverage,
    DeskLimitsResponse,
    NodeUnderwritingRow,
)
