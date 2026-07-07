"""Ops-hardening health blocks surfaced on /api/health."""

from __future__ import annotations


def test_health_reports_job_failure_streak(client, seeded_db_empty_cards):
    from uw_scan.storage.ops_health import JobFailuresRepository

    repo = seeded_db_empty_cards
    JobFailuresRepository(repo.conn).record_failure("full_scan", "boom")
    repo.conn.commit()
    body = client.get("/api/health").json()
    assert any(f["job_name"] == "full_scan" for f in body["job_failures"])
