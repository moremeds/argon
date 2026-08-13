import json
from pathlib import Path


VERDICT = (
    Path(__file__).resolve().parents[3]
    / "docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md"
)
AUDIT = VERDICT.with_name("pre-hardening-audit.json")
PLAN = VERDICT.parents[2] / "plans/2026-08-13-macro-mc1-historical-release-hardening.md"
DESIGN = (
    VERDICT.parents[2]
    / "superpowers/specs/2026-08-13-macro-mc1-historical-release-durability-design.md"
)


def test_verdict_stays_partial_until_all_release_and_4x4_gates_pass() -> None:
    text = VERDICT.read_text()

    assert "**Verdict:** PARTIAL" in text
    assert "FOMC statements | 10 | 0" in text
    assert "SEP | 4 | 0" in text
    assert "NY Fed SME | 2 | 1" in text
    assert "Frenzy shadow | 1 | 1" in text
    assert "45 discovered / 17 parsed / 28 failed" in text
    assert "10 Statement" in text
    assert "3 SEP" in text
    assert "all 13 currently unparsed" in text
    assert "production discovery misses 2020" in text
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
    assert audit["official_2020_history"]["event_classifications"] == {
        "fomc-statement:monetary20200303a": "unscheduled_meeting",
        "fomc-statement:monetary20200315a": "unscheduled_meeting",
        "fomc-statement:monetary20200323a": "notation_vote",
    }
