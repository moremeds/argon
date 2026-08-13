from pathlib import Path


VERDICT = (
    Path(__file__).resolve().parents[3]
    / "docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md"
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
