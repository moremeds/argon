"""The product claim registry — what each surface is ALLOWED to say (M3.3).

Every dimension and every shipped method has a measured basis, an allowed
behaviour, an allowed vocabulary, a prohibited inference, and a condition that
would kill or downgrade it. This module is where those live as DATA, so a UI
cannot exceed a permission by writing a different sentence, and so a reviewer can
diff permissions against research rather than against prose.

WHY A REGISTRY AND NOT DOCUMENTATION
------------------------------------
Argon has repeatedly shipped a surface whose wording outran its evidence — a
composite that "orders names" rendered as a quality score, a percentile band
whose `buy_below` label asserts a price the IC never licensed. Documentation did
not stop either, because documentation is not consulted at render time. A
registry entry is: it names the exact artifact, and a test asserts that no entry
claims more than its artifact measured.

EVERY ENTRY NAMES A REAL ARTIFACT
---------------------------------
`evidence` is an artifact SLUG plus its `evidence_kind`, never a path. Two
reasons, and the second is the one that bites: a claim whose artifact does not
exist is unfalsifiable rather than merely weak, so a test resolves every slug and
fails if the file is missing — and `docs/` is NOT shipped inside the Docker
image, so a literal path here would be a runtime reference to something that does
not exist in production. `scripts/check_runtime_assets.py` enforces that, and it
caught this module's first draft.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from uw_scan.fundamentals.dimensions import Authority


@dataclass(frozen=True)
class Claim:
    """One product surface's permission, and the measurement behind it."""

    key: str
    #: What the surface computes over.
    universe: str
    #: The method/engine version whose output this describes.
    method: str
    authority: Authority
    #: What the surface may DO. Imperative, checkable against the code.
    allowed_behaviour: tuple[str, ...]
    #: Words the surface may use.
    allowed_language: tuple[str, ...]
    #: Inferences a reader must not be invited to draw.
    prohibited: tuple[str, ...]
    #: Artifact slug — a directory under docs/research/ or a plan filename.
    #: NOT a path: see the module docstring on the runtime-asset guard.
    evidence: str
    #: How to resolve `evidence`: "research" -> a VERDICT.md in a dated research
    #: directory; "plan" -> a plan document.
    evidence_kind: str
    #: What would revoke or downgrade this.
    kill_condition: str
    #: When the claim must be re-measured or expire.
    revalidate: str
    notes: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: tuple[Claim, ...] = (
    Claim(
        key="composite",
        universe="fundamental_universe tier 'ranked', active names only",
        method="fundamentals-v1/v2 equal-weight composite",
        authority=Authority.RESEARCH_PRIORITY,
        allowed_behaviour=(
            "order names within one knowledge quarter for analyst attention",
            "filter to a decile or a threshold",
        ),
        allowed_language=(
            "ranks higher than", "worth looking at first", "screening order",
        ),
        prohibited=(
            "expected return — measured gross alpha is zero",
            "risk score — the top decile is riskier than the middle",
            "a per-name forecast — the within-ticker test is a POWERED null "
            "(IC -0.0000, all 16 tests fail BH)",
        ),
        evidence="2026-08-11-fundamental-signal-validation",
        evidence_kind="research",
        kill_condition=(
            "leak-free rank IC t-stat falls below 2 on a rerun over a widened or "
            "delisting-inclusive universe"
        ),
        revalidate="on any change to FEATURES, weights, or universe membership rule",
        notes=(
            "rank IC 0.0391, t 2.672 over 66 quarters, leak-free",
            "the ranking earns nothing as a book and costs are not why "
            "(decile mean return-rank 0.475 -> 0.526 over 79 quarters)",
        ),
    ),
    Claim(
        key="valuation_own_history",
        universe="251 tickers with >=24 quarterly observations, active-only",
        method="sales_to_ev / ebitda_to_ev / fcf_yield, within-ticker z-score",
        # A separately validated WITHIN-NAME direction is exactly what spec 6.4
        # reserves this level for. It was raised from `descriptive` on
        # 2026-08-25 by the split-basis rerun, not by a decision.
        authority=Authority.DIRECTIONAL_MONITOR,
        allowed_behaviour=(
            "state where spot sits in a name's OWN yield history",
            "monitor one name against its own band over time",
            "LIST names newly entering a cheap zone, unordered",
        ),
        allowed_language=(
            "cheap versus its own history", "at the Nth percentile of its own range",
            "newly entered its own buy zone",
        ),
        prohibited=(
            "ordering names against EACH OTHER by cheapness — cross-sectionally "
            "value measured INVERTED in this universe (book_to_price IC -0.0365, "
            "t -2.32)",
            "treating `buy_below` as a validated PRICE — the IC licenses an "
            "ordering, not the inversion of a percentile into a level",
            "routing a company type to book_to_price or earnings_yield — both "
            "lose significance among split-exposed names once corrected",
        ),
        evidence="2026-08-25-valuation-split-basis-rerun",
        evidence_kind="research",
        kill_condition=(
            "sales_to_ev partial IC (reversal held constant) falls below t 3 on a "
            "delisting-inclusive rerun, or the split-only price basis changes"
        ),
        revalidate="on any change to TYPE_YIELD routing or the price basis",
        notes=(
            "sales_to_ev within-ticker 2q IC +0.0709 (t 5.55) on the corrected "
            "split-consistent basis; +0.0772 (t 6.74) holding reversal constant",
            "unmoved by the split correction on the exposed cohort "
            "(+0.0637 -> +0.0651), unlike the four other signals",
        ),
    ),
    Claim(
        key="operating_quality",
        universe="same as composite",
        method="mean of gross_margin and op_margin z-scores",
        authority=Authority.DESCRIPTIVE,
        allowed_behaviour=("render the margin", "filter on it"),
        allowed_language=("gross margin is", "operating margin is"),
        prohibited=(
            "any direction claim — BOTH inputs measured INVERTED "
            "(high-margin names underperformed)",
            "entering the priority aggregate",
        ),
        evidence="2026-08-12-fundamental-timeseries-test",
        evidence_kind="research",
        kill_condition="n/a — already at the floor",
        revalidate="if a rerun ever recovers the conventional sign out-of-sample",
    ),
    Claim(
        key="revenue_concentration",
        universe="names with a usable XBRL axis breakdown",
        method="top-share by segment / geography, read-time derivation",
        authority=Authority.DESCRIPTIVE,
        allowed_behaviour=("render the breakdown", "show its change over time"),
        allowed_language=("top segment share is", "geographic mix is"),
        prohibited=(
            "use as a composite input — withdrawn 2026-08-18",
            "reading the LEVEL as alpha; it is a factor loading",
        ),
        evidence="2026-08-13-fundamental-lane-next",
        evidence_kind="plan",
        kill_condition="n/a — already at the floor",
        revalidate="never; the null is the finding",
        notes=(
            "top share moves a median 1.20pp/quarter against p90 17.5pp of "
            "annual/quarterly basis contamination",
        ),
    ),
    Claim(
        key="evidence_quality",
        universe="every scored name",
        method="share of a result's observations carrying a true_pit claim",
        authority=Authority.DESCRIPTIVE,
        allowed_behaviour=(
            "disclose how well-evidenced an answer is",
            "gate a historical replay",
        ),
        allowed_language=("N of M observations are point-in-time",),
        prohibited=(
            "reading it as a quality score for the COMPANY — it describes what "
            "Argon knows, not the business",
        ),
        evidence="2026-08-25-sec-publication-evidence",
        evidence_kind="research",
        kill_condition="n/a — a coverage measure, not a signal",
        revalidate="on any change to the publication rule",
        notes=("true_pit yield 84.8%; 240 of 401 tickers at >=90% coverage",),
    ),
)

BY_KEY: Mapping[str, Claim] = {c.key: c for c in REGISTRY}


def claim_for(key: str) -> Claim:
    """The registry entry, or a refusal naming the gap.

    Raises rather than returning a permissive default: a surface with no
    registered claim must not silently inherit the strongest one on the page.
    """
    try:
        return BY_KEY[key]
    except KeyError as exc:
        raise KeyError(
            f"no registered claim for {key!r}; a surface without one may not "
            "render an ordering or a direction. Add it to REGISTRY with its "
            "measuring artifact."
        ) from exc


def permits(key: str, authority: Authority | str) -> bool:
    """Whether `key` is allowed to exercise `authority`."""
    from uw_scan.fundamentals.dimensions import AUTHORITY_ORDER

    want = Authority(authority)
    have = claim_for(key).authority
    return AUTHORITY_ORDER.index(want) <= AUTHORITY_ORDER.index(have)
