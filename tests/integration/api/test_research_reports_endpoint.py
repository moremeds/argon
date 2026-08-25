"""Report read + assemble endpoints (M7).

Two things these pin. A report that has never been assembled must NOT read as a
company with nothing to say — `no_report` and `no_coverage` are different
answers. And the frozen-version read must serve the stored blocks, not
re-assemble under today's data wearing an old version number.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from uw_scan.storage.research_reports import ResearchReportsRepository

MANIFEST = {
    "engine_version": "fundamentals-v2:aaaaaaaa",
    "taxonomy_version": "argon-research-v1",
    "evidence_policy": "true_pit_only",
    "as_of": "2026-08-25",
    "assembler_version": "report-assembler-v1",
    "scope": {"ticker": "NVDA"},
}


def _blocks(priority: float):
    return [
        {
            "ordinal": 0,
            "block_kind": "scope",
            "title": "NVDA — research scope",
            "payload": {"ticker": "NVDA"},
            "derivation": "the report manifest, restated for the reader",
        },
        {
            "ordinal": 1,
            "block_kind": "dimensions",
            "title": "Research-priority dimensions",
            "payload": {"priority": priority},
            "evidence": {"source": "fundamental_dimensions"},
            "authority": "research_priority",
        },
    ]


@pytest.fixture
def two_versions(seeded_db_empty_cards):
    repo = ResearchReportsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    repo.publish(
        report_key="company:NVDA",
        report_type="company",
        title="NVDA research report",
        manifest=MANIFEST,
        blocks=_blocks(1.20),
    )
    repo.publish(
        report_key="company:NVDA",
        report_type="company",
        title="NVDA research report",
        manifest={**MANIFEST, "engine_version": "fundamentals-v3:bbbbbbbb"},
        blocks=_blocks(0.10),
    )
    return repo


def test_a_report_nobody_asked_for_is_not_a_company_with_nothing_to_say(
    client: TestClient, seeded_db_empty_cards
):
    r = client.get("/api/research/reports/company/AMD")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "no_report"
    assert body["report"] is None
    assert "POST this path" in body["reason"]


def test_the_latest_read_carries_the_delta(client: TestClient, two_versions):
    body = client.get("/api/research/reports/company/nvda").json()
    assert body["state"] == "ok"
    assert body["report"]["version_no"] == 2
    assert [v["version_no"] for v in body["versions"]] == [2, 1]

    delta = body["delta"]
    assert delta["is_first_version"] is False
    assert delta["manifest"] == [
        {
            "field": "engine_version",
            "before": "fundamentals-v2:aaaaaaaa",
            "after": "fundamentals-v3:bbbbbbbb",
        }
    ]
    assert delta["summary"].startswith("1 manifest field(s) changed")
    assert delta["moved"][0]["changes"][0]["path"] == "priority"


def test_an_old_version_serves_its_frozen_content(client: TestClient, two_versions):
    body = client.get("/api/research/reports/company/NVDA/versions/1").json()
    assert body["report"]["version_no"] == 1
    assert body["report"]["status"] == "superseded"
    assert body["report"]["manifest"]["engine_version"] == "fundamentals-v2:aaaaaaaa"
    dims = next(
        b for b in body["report"]["blocks"] if b["block_kind"] == "dimensions"
    )
    assert dims["payload"]["priority"] == 1.20
    assert body["delta"]["is_first_version"] is True


def test_a_missing_version_is_a_404(client: TestClient, two_versions):
    assert client.get("/api/research/reports/company/NVDA/versions/9").status_code == 404


def test_an_unknown_report_type_is_a_404(client: TestClient, seeded_db_empty_cards):
    assert client.get("/api/research/reports/sector/tech").status_code == 404


def test_assemble_publishes_and_a_repeat_manufactures_no_history(
    client: TestClient, seeded_db_empty_cards
):
    """Double-clicking must not create a version whose delta is empty."""
    path = f"/api/research/reports/company/MU?as_of={date(2026, 8, 25)}"
    first = client.post(path).json()
    assert first["state"] == "ok"
    assert first["report"]["version_no"] == 1
    # No dimensions in an empty test DB: the report publishes and SAYS so.
    assert first["report"]["status"] == "partial"
    unsupported = next(
        b for b in first["report"]["blocks"] if b["block_kind"] == "unsupported"
    )
    assert unsupported["ordinal"] == 1

    again = client.post(path).json()
    assert again["report"]["version_no"] == 1
    assert len(again["versions"]) == 1


def test_the_listing_shows_the_newest_version_of_each_key(
    client: TestClient, two_versions
):
    body = client.get("/api/research/reports").json()
    keys = {r["report_key"]: r for r in body["reports"]}
    assert keys["company:NVDA"]["version_no"] == 2
    assert keys["company:NVDA"]["report_type"] == "company"


def test_a_comparison_keys_on_its_sorted_ticker_set(
    client: TestClient, seeded_db_empty_cards
):
    """Two orderings of one question must version one report, not fork two."""
    first = client.post(
        f"/api/research/reports/comparison/NVDA,AMD?as_of={date(2026, 8, 25)}"
    ).json()
    assert first["report"]["report_key"] == "comparison:AMD-NVDA"
    assert first["report"]["version_no"] == 1

    again = client.post(
        f"/api/research/reports/comparison/amd,nvda?as_of={date(2026, 8, 25)}"
    ).json()
    assert again["report"]["version_no"] == 1
    assert len(again["versions"]) == 1

    fetched = client.get("/api/research/reports/comparison/nvda,amd").json()
    assert fetched["state"] == "ok"
    coverage = next(
        b for b in fetched["report"]["blocks"]
        if b["block_kind"] == "comparison_coverage"
    )
    # Both requested names are named as absent rather than quietly dropped.
    assert coverage["payload"]["without_result"] == ["AMD", "NVDA"]


def test_an_empty_comparison_is_a_400(client: TestClient, seeded_db_empty_cards):
    assert client.get("/api/research/reports/comparison/,,").status_code == 400
