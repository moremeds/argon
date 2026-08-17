import json
from pathlib import Path

import pytest


VERDICT = (
    Path(__file__).resolve().parents[3]
    / "docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md"
)
AUDIT = VERDICT.with_name("pre-hardening-audit.json")
PROBE = VERDICT.with_name("probe.json")
SMOKE = VERDICT.with_name("smoke-4x4.json")
PLAN = VERDICT.parents[2] / "plans/2026-08-13-macro-mc1-historical-release-hardening.md"
DESIGN = (
    VERDICT.parents[2]
    / "superpowers/specs/2026-08-13-macro-mc1-historical-release-durability-design.md"
)


def _assert_expected_fomc_coverage(coverage: dict[str, object]) -> None:
    failures = coverage["failed_releases"]
    assert isinstance(failures, list)
    assert (
        coverage["discovered"],
        coverage["parsed"],
        coverage["failed"],
    ) == (45, 17, 28)
    assert coverage["discovered"] == coverage["parsed"] + coverage["failed"]
    assert coverage["failed"] == len(failures) == 28
    assert len({item["release_key"] for item in failures}) == len(failures)


def test_verdict_claims_only_what_the_committed_evidence_measures() -> None:
    """PASS is a claim about two files, not a sentence someone typed.

    The pre-hardening PARTIAL was retired by evidence; this guard makes the
    reverse impossible -- a PASS that outruns probe.json or smoke-4x4.json fails
    here rather than shipping.
    """
    text = VERDICT.read_text()
    probe = json.loads(PROBE.read_text())
    smoke = json.loads(SMOKE.read_text())

    if "**Verdict:** PASS" not in text:
        assert "**Verdict:** PARTIAL" in text
        return

    assert smoke["verdict"] == "PASS"
    assert all(smoke["assertions"].values()), smoke["assertions"]
    assert smoke["releases_not_ok"] == []
    assert probe["years"][0] == 2020

    for source in ("federal_reserve_fomc", "federal_reserve_sep"):
        result = probe["sources"][source]
        assert result["state"] == "ok"
        assert result["releases_failed"] == 0
        assert result["releases_succeeded"] == result["releases_discovered"] > 0
        # The headline counts in the prose must be the measured ones.
        assert (
            f"{result['releases_discovered']}/{result['releases_succeeded']}"
            in text.replace("**", "")
        )

    # All four slots, and the shadow never stands in for an official path.
    assert all(slot["present"] for slot in smoke["api_slots"].values())
    for official in ("actual", "committee_projection", "dealer_expectations"):
        assert smoke["api_slots"][official]["source_kind"] != "third_party_shadow"
    assert smoke["api_slots"]["market_implied"]["source_kind"] == "third_party_shadow"


def test_verdict_preserves_the_pre_hardening_baseline_it_retired() -> None:
    """The failure that motivated the milestone must stay legible after the fix.

    Whitespace-normalized: the prose reflows when the verdict is rewritten, and a
    line break landing inside a frozen phrase is not a lost baseline.
    """
    text = " ".join(VERDICT.read_text().split())

    assert "FOMC statements | 10 | 0" in text
    assert "SEP | 4 | 0" in text
    assert "NY Fed SME | 2 | 1" in text
    assert "Frenzy shadow | 1 | 1" in text
    assert "45 discovered / 17 parsed / 28 failed" in text
    assert "10 Statement" in text
    assert "3 SEP" in text
    assert "all 13 currently unparsed" in text
    assert "discovery misses 2020" in text
    assert "all discovered 2020+ releases" in text
    assert "worker → DB → API" in text


def test_2020_emergency_release_taxonomy_matches_the_official_history_page() -> None:
    text = VERDICT.read_text()
    normalized = " ".join(text.split())
    plan = " ".join(PLAN.read_text().split())
    design = " ".join(DESIGN.read_text().split())
    audit = json.loads(AUDIT.read_text())

    assert (
        "March 3 and March 15 unscheduled statements and the March 23 notation-vote "
        "statement"
    ) in normalized
    assert "March 3, March 15, and March 23 unscheduled" not in normalized
    assert "March 23, 2020 notation-vote statement" in plan
    assert 'event_class: Literal["scheduled_meeting", "unscheduled_meeting", "notation_vote"]' in plan
    assert "March 23, 2020 notation-vote statement" in design
    assert "including March 23, 2020" not in design
    history = audit["official_2020_history"]
    expected = {
        "fomc-statement:monetary20200129a": "scheduled_meeting",
        "fomc-statement:monetary20200303a": "unscheduled_meeting",
        "fomc-statement:monetary20200315a": "unscheduled_meeting",
        "fomc-statement:monetary20200323a": "notation_vote",
        "fomc-statement:monetary20200429a": "scheduled_meeting",
        "fomc-statement:monetary20200610a": "scheduled_meeting",
        "fomc-statement:monetary20200729a": "scheduled_meeting",
        "fomc-statement:monetary20200916a": "scheduled_meeting",
        "fomc-statement:monetary20201105a": "scheduled_meeting",
        "fomc-statement:monetary20201216a": "scheduled_meeting",
    }
    assert history["event_classifications"] == expected
    assert set(history["event_classifications"]) == set(history["statement_candidates"])
    assert len(expected) == history["statement_candidate_count"] == 10


def test_plan_requires_release_type_and_event_class_consistency() -> None:
    plan = " ".join(PLAN.read_text().split())
    design = " ".join(DESIGN.read_text().split())

    assert "def __post_init__(self) -> None:" in plan
    assert "statement candidates require a non-null event_class" in plan
    assert "SEP candidates require event_class=None" in plan
    assert "test_statement_candidate_rejects_null_event_class" in plan
    assert "test_sep_candidate_rejects_non_null_event_class" in plan
    assert "test_migration_rejects_statement_without_event_class" in plan
    assert "test_migration_rejects_sep_with_event_class" in plan
    assert "tests/integration/storage/test_migrations.py" in plan
    assert "release_type TEXT NOT NULL CHECK" in plan
    assert "release_type = 'statement' AND event_class IS NOT NULL" in plan
    assert "release_type = 'sep' AND event_class IS NULL" in plan
    assert "Every statement candidate has a non-null official event class" in design
    assert "SEP candidates have no statement event class" in design


def test_pre_hardening_audit_machine_evidence_is_internally_consistent() -> None:
    audit = json.loads(AUDIT.read_text())

    assert audit["worker_results_2026"] == [
        {
            "source": "federal_reserve_fomc",
            "label": "FOMC statements",
            "artifacts_seen": 10,
            "observations_seen": 0,
            "status": "degraded",
            "bounded_error": "FOMC statement missing required fields: target range",
        },
        {
            "source": "federal_reserve_sep",
            "label": "SEP",
            "artifacts_seen": 4,
            "observations_seen": 0,
            "status": "degraded",
            "bounded_error": "SEP participant count declaration is missing",
        },
        {
            "source": "new_york_fed_sme",
            "label": "NY Fed SME",
            "artifacts_seen": 2,
            "observations_seen": 1,
            "status": "ok",
            "bounded_error": None,
        },
        {
            "source": "frenzy_capital",
            "label": "Frenzy shadow",
            "artifacts_seen": 1,
            "observations_seen": 1,
            "status": "ok",
            "bounded_error": None,
        },
    ]
    coverage = audit["fomc_coverage_2021_2026"]
    _assert_expected_fomc_coverage(coverage)
    history = audit["official_2020_history"]
    assert 13 == history["statement_candidate_count"] + history["sep_candidate_count"]
    assert history["statement_candidate_count"] == len(history["statement_candidates"])
    assert history["sep_candidate_count"] == len(history["sep_candidates"])
    assert audit["pass_gates"]
    assert all(value is False for value in audit["pass_gates"].values())


def test_pre_hardening_coverage_rejects_count_drift_that_still_adds_up() -> None:
    audit = json.loads(AUDIT.read_text())
    drifted = dict(audit["fomc_coverage_2021_2026"])
    drifted.update(discovered=46, parsed=18, failed=28)

    with pytest.raises(AssertionError):
        _assert_expected_fomc_coverage(drifted)


def test_plan_parses_march_23_notation_vote_without_using_adjacent_vote() -> None:
    plan = " ".join(PLAN.read_text().split())
    design = " ".join(DESIGN.read_text().split())

    assert 'vote_status="stated"' in plan
    assert 'vote_split="10-0"' in plan
    assert "Voting (by notation) for the monetary policy action were" in plan
    assert "mutation" in plan
    assert "Committee voted unanimously to authorize and direct" in plan
    assert "must not supply the monetary-policy vote" in plan
    assert 'vote_status="stated"' in design
    assert 'vote_split="10-0"' in design
    assert "March 23, 2020" in design
    assert "including March 23, 2020" not in design
    assert "An official release with no published monetary-policy voting clause" in design


def test_plan_never_invents_missing_baseline_reproduce_provenance() -> None:
    plan = " ".join(PLAN.read_text().split())
    audit = json.loads(AUDIT.read_text())
    boundary = audit["data_boundary"]

    assert "record the exact reproduce command only when it was saved" in plan
    assert "store null plus a provenance note" in plan
    assert "never reconstruct or invent a command" in plan
    assert boundary["worker_smoke_command"] is None
    assert boundary["fomc_parser_audit_command"] is None
    assert boundary["worker_smoke_provenance_note"]
    assert boundary["fomc_parser_audit_provenance_note"]
