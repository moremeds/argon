"""What a chain analysis node IS, declared as data.

A "node" is one industry chain — optical communication, datacenter power,
datacenter cooling — analysed by the same fixed set of components. This module
is the catalogue: every component names its function, what it reads, what it
costs in vendor calls, the shape of its result, and the strongest claim it is
allowed to make. `test_chain_nodes.py` asserts the assembler emits exactly this,
so the catalogue cannot drift into decoration.

WHY THE COST FIELD IS PART OF THE DECLARATION
---------------------------------------------
Every component here costs ZERO vendor calls: they all read the warm store. The
vendor spend for a chain node sits entirely upstream, in the jobs that fill that
store, and it is shared across every chain at once. Measured on the argon
universe 2026-08-26: all 44 members of the five datacenter chains are already in
`fundamental_universe` and 42 of the 44 already carry statements (DC-REIT/Colo is
the gap, at 4 of 6), so adding those chains costs no incremental UW calls at all. A cost field that only appeared in a design doc
would let someone assume the opposite and budget for a spend that is not there.

WHAT ADDING A CHAIN ACTUALLY REQUIRES
-------------------------------------
Rows, not code. `assemble_chain_report` is already chain-generic. A new node is:

  1. `research_chains`   — one row per layer: domain, chain, layer, rank,
                           description. Ranks are sparse (10, 20, 30 ...) so a
                           layer discovered later slots between two existing ones
                           without renumbering the chain.
  2. `chain_membership`  — one row per (chain, layer, ticker). A company in two
                           layers is two rows; every count over this table must
                           therefore dedupe by ticker.
  3. `chain_segment_alias` — optional. Only needed to turn a filer's disclosed
                           segment into a magnitude. A longer pattern is a
                           narrower claim and wins; an equally specific tie
                           between two chains is refused, not guessed.

The one thing that is NOT optional is the layer set. 38 of argon's 39 chains were
seeded with a single placeholder layer `L3` at rank 0, which is why their reports
render a chain with no shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Report shapes a component can appear in.
CHAIN = "chain"
COMPANY = "company"
COMPARISON = "comparison"


@dataclass(frozen=True)
class Cost:
    """What one component spends to produce its block.

    `uw_calls` is deliberately an int and deliberately zero everywhere: the
    number is here so that a future component which DOES call a vendor cannot be
    added without stating it.
    """

    uw_calls: int
    reads: tuple[str, ...]
    writes: tuple[str, ...] = ("research_report_blocks",)


@dataclass(frozen=True)
class Component:
    """One block of a chain analysis node."""

    kind: str
    title: str
    purpose: str
    shapes: tuple[str, ...]
    cost: Cost
    #: Keys the payload carries. The page renders from these names, so a rename
    #: here is a contract change for every consumer.
    result: tuple[str, ...]
    #: Strongest claim the block may make. `None` means the block states facts
    #: and orders nothing. The schema enforces the ceiling separately
    #: (migrations 138 and 143); this field is the human-readable half.
    authority: str | None = None
    #: A component is REQUIRED unless it has nothing to say. `dimensions` is the
    #: only optional one: the assembler drops it when a name carries no computed
    #: dimensions, and the `unsupported` block declares the gap instead of
    #: emitting a block of nulls that reads like a measurement.
    required: bool = True
    notes: str = ""


_WARM = ("fundamental_scores", "fundamental_dimensions")

CHAIN_COMPONENTS: tuple[Component, ...] = (
    Component(
        kind="scope",
        title="research scope",
        purpose="Restate the frozen manifest: what was asked, under which "
        "engine and taxonomy version, as of when.",
        shapes=(CHAIN, COMPANY, COMPARISON),
        cost=Cost(uw_calls=0, reads=("research_taxonomy_versions",)),
        result=(
            "chain",
            "as_of",
            "engine_version",
            "taxonomy_version",
            "members",
            "member_placements",
        ),
        notes="`members` counts companies, `member_placements` counts "
        "chain x layer rows. Both are named because they are not equal and a "
        "reader must not discover that by subtraction.",
    ),
    Component(
        kind="unsupported",
        title="what this report cannot answer",
        purpose="Name the killed event classes, the dimensions capped at "
        "descriptive, and any abstention — before the numbers, not after.",
        shapes=(CHAIN, COMPANY, COMPARISON),
        cost=Cost(uw_calls=0, reads=("research_event_classes",)),
        result=("killed_event_classes", "capped_dimensions", "notes"),
        notes="Ordinal 1 on purpose. A report that omits what it cannot answer "
        "reads as complete.",
    ),
    Component(
        kind="chain_coverage",
        title="coverage and denominators",
        purpose="How much of the chain the report can actually speak for.",
        shapes=(CHAIN,),
        cost=Cost(uw_calls=0, reads=("chain_membership", "company_exposure")),
        result=(
            "members",
            "with_exposure",
            "with_magnitude",
            "magnitudes_non_member",
            "with_compatible_result",
        ),
        notes="`with_magnitude` counts MEMBERS; the exposure block lists every "
        "magnitude mapped to the chain. Different grains, so both are stated.",
    ),
    Component(
        kind="chain_members",
        title="members by layer",
        purpose="The chain's shape: who sits at which layer, and how each "
        "name's priority dimension stands.",
        shapes=(CHAIN,),
        cost=Cost(uw_calls=0, reads=("chain_membership",) + _WARM),
        result=("members",),
        authority="research_priority",
        notes="Ordering by priority exercises the composite's permission and "
        "nothing stronger. Rows carry the score's `as_of`, which identifies the "
        "cross-section a z-score was standardised against.",
    ),
    Component(
        kind="chain_aggregate",
        title="aggregate priority",
        purpose="One number for the chain, or an explicit abstention.",
        shapes=(CHAIN,),
        cost=Cost(uw_calls=0, reads=_WARM),
        result=("priority_mean", "n", "abstains"),
        authority="research_priority",
        notes="Mean over DISTINCT members, one vote per company; abstains below "
        "3. A mean taken over the placement grain would double-weight every "
        "two-layer company.",
    ),
    Component(
        kind="chain_exposure",
        title="disclosed economic exposure",
        purpose="Which members disclose a segment that maps to this chain, and "
        "how large that segment is against the consolidated total.",
        shapes=(CHAIN, COMPANY, COMPARISON),
        cost=Cost(
            uw_calls=0,
            reads=("company_exposure", "revenue_breakdown_obs", "chain_segment_alias"),
        ),
        result=(
            "exposures",
            "asserted_without_magnitude",
        ),
        notes="Each exposure carries `is_member` and `source_ref`. A magnitude "
        "for a company nobody placed in the chain is a claim the membership does "
        "not support, and stays visible rather than being filtered from sight.",
    ),
    Component(
        kind="dimensions",
        title="dimension detail",
        purpose="Per-dimension value, inputs present against expected, and the "
        "authority each dimension carries.",
        shapes=(COMPANY,),
        cost=Cost(uw_calls=0, reads=_WARM),
        result=("dimensions", "priority"),
        authority="research_priority",
        required=False,
    ),
    Component(
        kind="risks",
        title="risk facts",
        purpose="Deterministic checks: a measured number against a stated "
        "threshold, with what a breach invalidates.",
        shapes=(COMPANY,),
        cost=Cost(uw_calls=0, reads=("research_risk_facts",)),
        result=("risks",),
        notes="Evaluated per COMPANY. The chain shape does not carry this block, "
        "so a staleness breach flagged on one name is silent for a chain of "
        "seventeen — see the design doc's open item.",
    ),
    Component(
        kind="events",
        title="typed events",
        purpose="What happened to this company that the event registry admits.",
        shapes=(COMPANY,),
        cost=Cost(uw_calls=0, reads=("research_events",)),
        result=("events",),
    ),
    Component(
        kind="comparison_coverage",
        title="comparison coverage",
        purpose="Every requested ticker, whether or not it carries a result.",
        shapes=(COMPARISON,),
        cost=Cost(uw_calls=0, reads=_WARM),
        result=("requested", "with_result"),
        notes="A comparison that silently drops what it could not score reads "
        "as a complete ranking of the group the operator asked about.",
    ),
    Component(
        kind="comparison_table",
        title="side-by-side table",
        purpose="The requested names ordered, with the denominator named.",
        shapes=(COMPARISON,),
        cost=Cost(uw_calls=0, reads=_WARM),
        result=("rows",),
        authority="research_priority",
    ),
)

#: kind -> Component, for the renderer and the tests.
BY_KIND: dict[str, Component] = {c.kind: c for c in CHAIN_COMPONENTS}

#: The ORDER each shape emits its components in. Declared per shape rather than
#: inferred from `CHAIN_COMPONENTS` order, because the three shapes interleave
#: the shared components differently: `chain_exposure` is last in a chain report
#: and last in a company report, but it sits after two company-only blocks that
#: a chain report never emits. An inferred order silently agreed with the
#: assembler for `chain` and disagreed for the other two.
SHAPE_ORDER: dict[str, tuple[str, ...]] = {
    CHAIN: (
        "scope",
        "unsupported",
        "chain_coverage",
        "chain_members",
        "chain_aggregate",
        "chain_exposure",
    ),
    COMPANY: (
        "scope",
        "unsupported",
        "dimensions",
        "risks",
        "events",
        "chain_exposure",
    ),
    COMPARISON: (
        "scope",
        "unsupported",
        "comparison_coverage",
        "comparison_table",
        "chain_exposure",
    ),
}


def components_for(shape: str) -> tuple[Component, ...]:
    """The components a report shape emits, in emission order."""
    return tuple(BY_KIND[kind] for kind in SHAPE_ORDER[shape])


def _check_declaration() -> None:
    """`shapes` and `SHAPE_ORDER` are two statements of one fact; agree or fail.

    Import-time rather than test-time: a component added to one and not the other
    is a bug in the catalogue itself, and the catalogue is what other code reads.
    """
    for shape, order in SHAPE_ORDER.items():
        missing = [k for k in order if k not in BY_KIND]
        if missing:
            raise ValueError(f"{shape}: SHAPE_ORDER names unknown kinds {missing}")
        declared = {c.kind for c in CHAIN_COMPONENTS if shape in c.shapes}
        if declared != set(order):
            raise ValueError(
                f"{shape}: `shapes` says {sorted(declared)} but SHAPE_ORDER says "
                f"{sorted(order)}"
            )


_check_declaration()


@dataclass(frozen=True)
class Layer:
    """One rung of a chain. Ranks are sparse so a later discovery slots in."""

    layer: str
    rank: int
    description: str


@dataclass(frozen=True)
class AliasRule:
    """Maps a filer's disclosed segment tag to this chain.

    `pattern` is matched case-insensitively as a SUBSTRING of the tag's local
    name. Longer wins, because a longer pattern is a narrower claim; an equally
    specific tie across two chains is refused rather than guessed.
    """

    pattern: str
    role: str
    axis: str = "us-gaap:StatementBusinessSegmentsAxis"


@dataclass(frozen=True)
class ChainSpec:
    """Everything needed to stand up one chain analysis node."""

    domain: str
    chain: str
    layers: tuple[Layer, ...]
    aliases: tuple[AliasRule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ranks = [layer.rank for layer in self.layers]
        if len(set(ranks)) != len(ranks):
            raise ValueError(f"{self.chain}: duplicate layer ranks {ranks}")
        if sorted(ranks) != ranks:
            raise ValueError(f"{self.chain}: layers must be declared in rank order")


#: The one chain seeded with a real layer set. Every other chain in
#: `research_chains` carries a single placeholder layer and renders shapeless.
OPTICAL_COMMUNICATION = ChainSpec(
    domain="optical_communication",
    chain="Optical-Communication",
    layers=(
        Layer("Upstream-Components", 10, "lasers, photonic ICs, passive optics"),
        Layer("Semi-DSP-Switch", 20, "DSP and switch silicon"),
        Layer("Module-Transceiver", 30, "pluggable optical modules"),
        Layer("Systems-Networking", 40, "switches, routers, line systems"),
        Layer("Customer-Cloud", 70, "hyperscale buyers of optical capacity"),
    ),
    aliases=(
        AliasRule("opticalcommunication", "component"),
        AliasRule("photonic", "component"),
        AliasRule("datacenterandcommunications", "component"),
        AliasRule("datacenternetworking", "component"),
        AliasRule("communicationssolutions", "component"),
        AliasRule("blueplanetautomation", "integrator"),
    ),
)

#: The datacenter build-out siblings. Every member is already in the universe;
#: 42 of 44 carry statements (measured 2026-08-26, DC-REIT/Colo is the gap at
#: 4 of 6), so these chains cost no incremental UW calls at all.
#:
#: ONE REAL LAYER PER CHAIN. The chain IS a layer of the build-out — construction
#: before generation before distribution before cooling before the operator who
#: leases the result — and inventing an intra-chain split here would publish a
#: shape nobody measured. Ranks are sparse, so a split discovered later slots
#: between two of these without renumbering anything.
#:
#: EVERY SPEC IS `ai_infrastructure`, DELIBERATELY. `research_chains`' primary
#: key is (taxonomy_version, chain, layer), so `domain` is a per-LAYER attribute
#: and not part of a chain's identity. All five names are already mirrored from
#: `watchlist_chain` under `ai_infrastructure` with a placeholder layer; a spec
#: declaring a second domain would leave one chain carrying two layers under two
#: domains, and `chains(version, domain=...)` would answer with half of it.
#: `OPTICAL_COMMUNICATION` can carry its own domain only because its spec name
#: differs from the watchlist's (`Networking/Optical`), so it collides with
#: nothing. `test_no_chain_carries_two_domains` is the guard.
DATACENTER_CHAINS: tuple[ChainSpec, ...] = (
    ChainSpec(
        domain="ai_infrastructure",
        chain="EPC/Construction",
        layers=(
            Layer(
                "EPC-Construction",
                10,
                "design, engineering, construction of datacenter shells",
            ),
        ),
    ),
    ChainSpec(
        domain="ai_infrastructure",
        chain="Generation/Nuclear",
        layers=(Layer("Generation", 20, "power generation and nuclear capacity"),),
    ),
    ChainSpec(
        domain="ai_infrastructure",
        chain="Power/Electrical",
        layers=(
            Layer("Power-Electrical", 30, "electrical distribution, switchgear, UPS"),
        ),
    ),
    ChainSpec(
        domain="ai_infrastructure",
        chain="Cooling/Thermal",
        layers=(
            Layer("Cooling-Thermal", 40, "liquid and air cooling, thermal management"),
        ),
    ),
    ChainSpec(
        domain="ai_infrastructure",
        chain="DC-REIT/Colo",
        layers=(
            Layer("DC-REIT-Colo", 50, "datacenter REITs and colocation operators"),
        ),
    ),
)
