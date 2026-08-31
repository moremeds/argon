"""The claim registry: every permission points at a real, existing measurement.

Argon has shipped surfaces whose wording outran their evidence more than once.
Documentation did not stop it because documentation is not consulted at render
time. These tests are: a claim whose artifact does not exist on disk is not a
weaker claim, it is an unfalsifiable one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uw_scan.fundamentals.claims import BY_KEY, REGISTRY, claim_for, permits
from uw_scan.fundamentals.dimensions import (
    DIMENSION_AUTHORITY,
    PROGRAM_CEILING,
    Authority,
)


def _artifact(claim) -> Path:
    """Resolve a claim's slug to its file.

    The registry stores a SLUG, not a path — `docs/` is not shipped inside the
    Docker image, so a literal path in `src/` would be a runtime reference to
    something absent in production (`scripts/check_runtime_assets.py` enforces
    that, and it caught the first draft of the registry).
    """
    if claim.evidence_kind == "research":
        return Path("docs/research") / claim.evidence / "VERDICT.md"
    if claim.evidence_kind == "plan":
        return Path("docs/superpowers/plans") / f"{claim.evidence}.md"
    raise AssertionError(f"unknown evidence_kind {claim.evidence_kind!r}")


def test_every_claim_points_at_an_artifact_that_exists():
    missing = [c.key for c in REGISTRY if not _artifact(c).exists()]
    assert missing == [], f"claims with no measuring artifact on disk: {missing}"


def test_every_claim_is_fully_specified():
    """A blank field is a permission nobody decided — the default failure mode."""
    for c in REGISTRY:
        assert c.universe, c.key
        assert c.method, c.key
        assert c.allowed_behaviour, c.key
        assert c.allowed_language, c.key
        assert c.prohibited, c.key
        assert c.kill_condition, c.key
        assert c.revalidate, c.key
        assert c.evidence and c.evidence_kind, c.key
        assert not c.evidence.startswith("docs/"), (
            f"{c.key}: evidence must be a slug, not a path — docs/ is not "
            "shipped in the image"
        )


def test_no_claim_reaches_investment_ranking():
    for c in REGISTRY:
        assert c.authority is not Authority.INVESTMENT_RANKING, c.key


def test_an_unregistered_surface_refuses_rather_than_inheriting():
    with pytest.raises(KeyError, match="no registered claim"):
        claim_for("some_new_panel")


def test_permits_is_an_upper_bound_not_an_equality():
    # composite is research_priority: it may also do descriptive things
    assert permits("composite", Authority.DESCRIPTIVE)
    assert permits("composite", Authority.RESEARCH_PRIORITY)
    assert not permits("composite", Authority.DIRECTIONAL_MONITOR)
    # operating_quality is at the floor
    assert permits("operating_quality", Authority.DESCRIPTIVE)
    assert not permits("operating_quality", Authority.RESEARCH_PRIORITY)


def test_valuation_may_monitor_a_name_and_may_not_rank_names():
    """The measured license is WITHIN-name; a stronger authority is not wider."""
    assert permits("valuation_own_history", Authority.DIRECTIONAL_MONITOR)
    claim = claim_for("valuation_own_history")
    joined = " ".join(claim.prohibited)
    assert "against EACH OTHER" in joined
    assert "buy_below" in joined


def test_the_composite_forbids_the_three_readings_it_measured_as_false():
    forbidden = " ".join(claim_for("composite").prohibited)
    for phrase in ("expected return", "risk score", "per-name forecast"):
        assert phrase in forbidden


def test_dimension_authorities_do_not_exceed_their_claims():
    """The registry is the ceiling; a dimension may not out-rank its evidence."""
    from uw_scan.fundamentals.dimensions import AUTHORITY_ORDER

    pairs = {
        "operating_quality": "operating_quality",
        "valuation": "valuation_own_history",
    }
    for dim, claim_key in pairs.items():
        assert AUTHORITY_ORDER.index(DIMENSION_AUTHORITY[dim]) <= AUTHORITY_ORDER.index(
            BY_KEY[claim_key].authority
        ), dim


def test_the_program_ceiling_is_research_priority():
    """Anything above it needs the GX gate this program does not provide."""
    assert PROGRAM_CEILING is Authority.RESEARCH_PRIORITY
