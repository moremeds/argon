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

EVERY FIELD IN THIS FILE IS REQUIRED. NULLABLE IS NOT OPTIONAL.
----------------------------------------------------------------
This is a rule about the whole module, not a property of particular fields,
and it exists because the natural way to declare a nullable field —
`x: float | None = None` — silently makes it ABSENT-ALLOWED too. Pydantic
drops it from the schema's `required` array and `openapi-typescript` emits
`x?: number | null`: three states where the contract has two.

That is not cosmetic here. `MemberDot.knowledge_date_estimated` is documented
as three-state with `null` explicitly NOT `false`; adding a fourth reading
(`undefined`) to a field whose whole problem is that two states are already
confusable is how a consumer inverts it. The collections are worse than the
scalars: `reactions?: number[]` makes `row.reactions.length` a runtime crash
instead of the "no reaction history is held — which is not 'the stock did not
move'" reading that field's own description demands.

So: nullable scalars are `Field(..., description=...)` or a bare annotation;
list fields never carry `= []` or `default_factory`. Every assembler passes
every field explicitly — verified, not assumed — so no default in this file is
load-bearing, and none should be reintroduced. If a future field's ABSENCE is
genuinely a different answer from its NULL, that is the one reason to make it
optional, and it needs a comment saying which two answers it is distinguishing.
`test_every_desk_field_is_required` enumerates this module's models
reflectively, so a model added later is covered without being listed anywhere.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from uw_scan.models._base import _preserve_public_module, _UwBase
from uw_scan.models.radar import FundamentalResultState

# WHY SOME FIELDS CARRY `Field(description=...)` AND MOST DO NOT
# ---------------------------------------------------------------
# A `#:` comment documents the field for a Python reader and reaches NOBODY
# else: it is stripped before OpenAPI, so `web/lib/types.ts` gets an empty
# description. A class docstring DOES reach the generated types as JSDoc, but
# only at object level. So any fact whose PLAIN READING IS BACKWARDS FROM ITS
# MEANING has to travel as `Field(description=...)`, or the web task inverts
# it. The ones below all failed that test; the rest are documented for the
# Python reader only, deliberately, because a description on every field is a
# wall of text the reader stops seeing.


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
    session: str | None = Field(
        ...,
        description=(
            "'premarket' | 'afterhours' | null. NULL IS A REAL THIRD VALUE, not "
            "missing data: the ~2% of names UW reports as report_time "
            "'unknown' appear in neither classified slot. Render it as "
            "'session unknown'; never guess one and never default to a side."
        ),
    )
    chain: str
    layer: str
    layer_rank: int
    implied_move_pct: float | None = Field(
        ...,
        description=(
            "null = NOT COVERED for THIS print. A snapshot exists only while a "
            "print is inside the nightly job's lookahead window, and a "
            "snapshot computed for an earlier print is never carried forward "
            "onto a later one. Render null as 'not covered', never as 0. The "
            "field is always PRESENT; only its value may be null."
        ),
    )
    implied_move_asof: date | None = Field(
        ...,
        description=(
            "The market date the implied move was computed on. Present exactly "
            "when implied_move_pct is; always emitted, null when not covered."
        ),
    )
    reactions: list[float] = Field(
        ...,
        description=(
            "Last <=4 realised print moves, NEWEST FIRST, as fractions "
            "(-0.0177 = -1.77%). An EMPTY list means no reaction history is "
            "held — which is not 'the stock did not move'."
        ),
    )
    spot_percentile: float | None = Field(
        ...,
        description=(
            "OWN-HISTORY YIELD percentile, so HIGH IS CHEAP: 0.80 means this "
            "name is cheaper against its own past than 80% of its own history. "
            "It is NOT a cross-sectional rank and must never order a list — "
            "cross-sectional value measured INVERTED in this universe."
        ),
    )
    percentile_state: FundamentalResultState = Field(
        ...,
        description=(
            "'ok' when a percentile is present; otherwise WHICH kind of "
            "absence it is. 'no_compatible_run' (Argon computed nothing) and "
            "'no_coverage' (Argon holds no statements) are different answers "
            "and must not render alike; 'unsupported_capability' means the "
            "valuation method REFUSED to price this name."
        ),
    )


class DeskCalendarResponse(_UwBase):
    section: str
    #: The date the list is current AS OF — also the floor: rows are prints on
    #: or after it. A print that has happened is history, not calendar.
    as_of: date
    #: report_date ASC, then layer_rank ASC — chain order is read-through
    #: order, which a generic calendar cannot say. Fixed regardless of filter.
    rows: list[DeskCalendarRow]


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
    #: same fact and was collapsed into this entry. `{}` when the class carries
    #: no extras — always emitted, so a reader never branches on its absence.
    detail: dict


class DeltaRailResponse(_UwBase):
    since: date
    #: Ordered `first_known_at` DESC — the desk's KNOWLEDGE clock, not the
    #: world's. "What changed" is a question about what Argon learned.
    events: list[DeltaRailEvent]


class MemberDot(_UwBase):
    """One name's value inside a chain cell. One dot per DISTINCT ticker.

    `value` is null when the name has no figure — never 0.0, which would put a
    name with no data at whatever the reader takes zero to mean.
    """

    ticker: str
    value: float | None
    state: FundamentalResultState
    knowledge_date_estimated: bool | None = Field(
        ...,
        description=(
            "THREE-STATE, and null is NOT false. true = this figure's "
            "knowledge date is the period_end + lag ESTIMATE, which errs early "
            "for late filers and manufactures look-ahead (measured: composite "
            "IC 0.059 with the fallback against 0.039 without). false = a real "
            "filing date. null = this dot has no knowledge date at all (a "
            "valuation percentile is not a filed figure), which is not a claim "
            "that the date is real. Carried so a reader can see it; the desk "
            "never filters on it."
        ),
    )


class CohortSlice(_UwBase):
    """One cross-section bucket a chain's members sit in.

    `fundamental_scores.as_of` is a cross-section IDENTIFIER, not a freshness
    stamp. When members straddle two buckets that is reporting season, and
    merging them would compare names that were never in the same peer group.
    """

    as_of: date
    #: 'reported' for the newest bucket present, 'awaiting' for every older one.
    label: str
    tickers: list[str]


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
    #: The layer holding this chain's LOWEST rank ('L1'..'L5' for a chain that
    #: sits on a taxonomy plane). Carried so the chain map can stack its planes
    #: without a second request; a property of the chain, not of the metric.
    layer: str
    layer_rank: int = Field(
        ...,
        description=(
            "0 means this chain sits on a taxonomy layer PLANE and can be "
            "placed on the chain map. A POSITIVE rank means it is a case "
            "chain — a ranked stage of a modelled flow — and belongs in a "
            "funnel instead. Read from research_chains, not from membership: "
            "the five dc_buildout chains carry an empty L3 row plus a ranked "
            "stage row holding every member, so a rank derived from "
            "memberships would call them stages and leave them off the map."
        ),
    )
    #: 'rev_yoy' | 'gross_margin' | 'valuation_percentile'
    metric: str
    median: float | None = Field(
        ...,
        description=(
            "UNWEIGHTED median of the non-null dot values — never "
            "revenue-weighted. ALWAYS null when metric = "
            "'valuation_percentile': own-history percentiles are NAME facts, "
            "so a chain aggregate over them is a claim about the chain that "
            "nothing measured. Also null when no member has a value."
        ),
    )
    dots: list[MemberDot]
    #: >=2 entries iff the chain's members straddle as_of buckets.
    cohorts: list[CohortSlice]
    coverage_missing: list[str] = Field(
        ...,
        description=(
            "The DISTINCT tickers with no value for this metric, BY NAME — "
            "never a bare count. '12/18' is decoration; 'missing: COHR' is "
            "actionable. An empty list means full coverage."
        ),
    )
    #: DISTINCT tickers. `chain_membership` is (chain, layer, ticker)-grained,
    #: so a name in two layers is two rows and must count ONCE.
    members_total: int


class DeskMatrixResponse(_UwBase):
    section: str
    #: Ordered by each chain's minimum `layer_rank`, ties alphabetically —
    #: never by any metric.
    chains: list[str]
    cells: list[ChainMetricCell]


class ProfitPoolLayer(_UwBase):
    """Where gross profit sits, layer by layer. Descriptive only.

    NO field for arrows, edges, propagation, or read-through exists here, by
    design — see the module docstring.
    """

    chain: str
    layer_rank: int
    #: Null when no member carries the metric — an abstention, never a 0.
    median_gross_margin: float | None
    median_rev_yoy: float | None
    dots: list[MemberDot]


class MembershipEvidenceCount(_UwBase):
    """How many memberships rest on each class of evidence.

    Counted at MEMBERSHIP grain deliberately — this is a statement about the
    taxonomy's evidential footing, not about how many companies there are.
    """

    #: 'disclosed' | 'analyst' | 'mirrored' | 'inferred'
    evidence_class: str
    memberships: int


class NonUsdFiler(_UwBase):
    """One name on this desk that does not file in USD.

    Why this is a LIMIT and not a footnote: summing gross profit across a
    chain put the Foundry chain at roughly $930B of quarterly gross profit,
    because TSM and UMC file in TWD and the store holds the FILED figure. So
    no dollar amount is summed across companies anywhere on this desk, and
    this list is the measured extent of the reason. Growth rates, margins and
    percentiles are unaffected — a ratio carries no currency.
    """

    ticker: str
    #: Every non-USD currency the store has ever recorded for this name,
    #: sorted. A name that has filed in two currencies carries both: the
    #: history is what a replay would read, and collapsing it to the latest
    #: would understate the hazard for exactly the periods it applies to.
    currencies: list[str]


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

    #: Comparable pairs whose two statements MATCH. Scoped to the section, and
    #: a sign-flipped pair is counted in neither this nor `ni_basis_differ` —
    #: it is a violation, and booking it here too would double-count it.
    ni_basis_agree: int
    #: They differ — NOT an error. See the class docstring.
    ni_basis_differ: int
    #: Named tickers, largest number of differing periods first.
    ni_largest_basis_differences: list[str]
    #: The one GENUINE integrity check on this axis, separate and rare:
    #: a literal sign inversion between the two statements (measured 5 of
    #: 28,973 rows). This one IS a violation and is labelled as such.
    ni_sign_flip_violations: int
    #: Spec §3f's fixed sentence — legitimately prose, because the reason a
    #: number is withheld is not itself a number.
    withheld_composite: str
    #: Membership semantics as NUMBERS (spec §3f: computed, not prose); the
    #: web layer writes captions OVER these, never instead of them.
    membership_evidence: list[MembershipEvidenceCount]
    exposure_coverage: list[ChainExposureCoverage]
    #: The section's non-USD filers, by name. Empty means every name on this
    #: desk files in USD — which is a real answer, not a missing one.
    non_usd_filers: list[NonUsdFiler]


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
    dio: float | None
    sbc_to_revenue: float | None
    shares_outstanding_yoy: float | None = Field(
        ...,
        description=(
            "Change in BASIC period-end shares outstanding against four "
            "quarters earlier. NOT a diluted share count — no diluted share "
            "key exists at any tier of the source store — so it measures "
            "issuance and buyback, NOT option/RSU/convertible overhang. Never "
            "label it 'dilution'."
        ),
    )
    filing_published_at: date | None
    #: Verbatim `raw_jsonb` strings — the filed line items themselves, copied
    #: not reformatted, so the figure above can be checked against them. Null
    #: means the provider served no such line for this period, which is a fact
    #: about the filing and must render as such rather than as a blank cell.
    inventory_raw: str | None
    cost_of_revenue_raw: str | None
    sbc_raw: str | None
    shares_outstanding_raw: str | None
    state: FundamentalResultState


class CapexQuarter(_UwBase):
    """One calendar quarter of the capex panel's combined spend.

    FISCAL QUARTERS ARE ASSIGNED TO THE CALENDAR QUARTER HOLDING THEIR END
    DATE. That is what lets a May-ending filer sit beside a June-ending one;
    it is an approximation, and it is the only one on this response.
    """

    #: '2026Q2' — the CALENDAR quarter containing each filer's period end.
    quarter: str
    #: Summed across the panel, in USD. Filed as a positive magnitude by this
    #: provider (verified), so it is NOT sign-flipped here — a reader who
    #: expects the cash-flow convention should read this as spend, not flow.
    capex_usd: float
    revenue_usd: float | None = Field(
        ...,
        description=(
            "Summed panel revenue for the same quarter, or null when ANY "
            "panel member is missing an income statement for it. Null rather "
            "than a partial sum: a ratio whose numerator counts five "
            "companies and whose denominator counts four is not an intensity, "
            "it is a bigger number."
        ),
    )
    #: The panel members that filed a capex figure for this quarter, by name.
    tickers: list[str]
    #: True iff `tickers` is the whole panel. A false here is why a quarter's
    #: level may step without anything having changed at the companies.
    complete: bool


class DeskCapexResponse(_UwBase):
    """The one exogenous input: what the panel commits to capital spending.

    Every revenue dollar in this chain is somebody else's capex, which is why
    this is the desk's first question rather than an appendix. It is also the
    single place on the desk where dollar amounts are summed across
    companies — permitted only because the panel is restricted to USD filers
    and the excluded names travel with the answer.
    """

    #: The taxonomy chain the panel is drawn from. Empty `included` means that
    #: chain holds no USD filer in this section — an answerless question, not
    #: an answer of zero.
    chain: str
    #: Panel members: chain members with no non-USD currency ever recorded.
    included: list[str]
    excluded: dict[str, str] = Field(
        ...,
        description=(
            "Chain members left OUT of the panel, mapped to the non-USD "
            "currency that excluded them. Printed with the figure, never "
            "behind it: an unexplained five-name panel reads as the whole "
            "chain."
        ),
    )
    #: Oldest quarter first.
    quarters: list[CapexQuarter]


class CaseStageMember(_UwBase):
    """One company at one stage of a case chain."""

    ticker: str
    #: Null means Argon holds no filed quarter for this name — it stays IN its
    #: stage, marked, and out of the stage median. Never dropped, never zero.
    rev_yoy: float | None
    gross_margin: float | None
    spot_percentile: float | None = Field(
        ...,
        description=(
            "Own-history YIELD percentile: 0.80 means CHEAP against this "
            "name's own past, not expensive. Never a cross-sectional rank — "
            "cross-sectional value measured INVERTED in this universe."
        ),
    )
    #: The name's non-USD filing currency, or null for a USD filer. Carried so
    #: a stage table can flag it without a second request.
    reported_currency: str | None


class CaseStage(_UwBase):
    """One ranked stage of a case chain."""

    #: The taxonomy layer, e.g. 'Module-Transceiver'. The display label is the
    #: web layer's business: a label map is editorial and does not belong in a
    #: contract that a replay has to reproduce.
    layer: str
    chain: str
    rank: int = Field(
        ...,
        description=(
            "`research_chains.layer_rank`. HIGHER IS FURTHER DOWNSTREAM — the "
            "customer stage carries the largest rank (Customer-Cloud 70, "
            "DC-REIT/Colo 50). Read the other way, every funnel is upside "
            "down and every amplification ratio inverts."
        ),
    )
    #: Alphabetical, DISTINCT. Never ordered by any metric.
    members: list[CaseStageMember]
    #: UNWEIGHTED median over reporting members; null when none report.
    median_rev_yoy: float | None
    median_gross_margin: float | None
    #: Members carrying a `rev_yoy` — the median's real denominator.
    reporting: int
    #: All members, reporting or not.
    total: int


class DeskCase(_UwBase):
    """A chain whose stages carry an explicit order, so a dollar's path
    through it is structure rather than inference.

    A domain becomes a case by having `layer_rank > 0` rows, nothing else. A
    domain with no ranked stages is deliberately absent here: placing chains
    is what the chain map does, and drawing flow without ranked stages would
    be inventing the very edges the desk refuses to draw.
    """

    domain: str
    #: URL identity for the case, e.g. 'optical'.
    slug: str
    label: str
    #: Ordered by `rank` ASCENDING — upstream first, customer last, the same
    #: read-through order the rest of the desk uses. A funnel drawing the
    #: customer on top reverses this itself.
    stages: list[CaseStage]


class ScopeGroup(_UwBase):
    """A taxonomy group this desk deliberately does not cover.

    NOT 'unclassified' and NOT a residual. These are the desk's own organising
    tags for names held for reasons unrelated to this chain, and they keep
    their own names — several (Sector-ETF, M7, Beta, Macro) are
    portfolio-construction tags with no stages to order, so modelling them as
    supply chains would be a category error rather than merely unbuilt work.
    """

    chain: str
    #: Every domain the chain's layers sit in. A list because a chain CAN span
    #: domains, and collapsing it to one would name a domain that owns only
    #: part of it.
    domains: list[str]
    #: DISTINCT tickers. Membership is (chain, layer, ticker)-grained, so a
    #: name in two layers must count once.
    members: int


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
    NonUsdFiler,
    ChainExposureCoverage,
    DeskLimitsResponse,
    NodeUnderwritingRow,
    CapexQuarter,
    DeskCapexResponse,
    CaseStageMember,
    CaseStage,
    DeskCase,
    ScopeGroup,
)
