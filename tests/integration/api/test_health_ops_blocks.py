"""Ops-hardening health blocks surfaced on /api/health."""

from __future__ import annotations


def test_health_reports_job_failure_streak(client, seeded_db_empty_cards):
    from uw_scan.storage.ops_health import JobFailuresRepository

    repo = seeded_db_empty_cards
    JobFailuresRepository(repo.conn).record_failure("full_scan", "boom")
    repo.conn.commit()
    body = client.get("/api/health").json()
    assert any(f["job_name"] == "full_scan" for f in body["job_failures"])


def test_disabled_ai_provider_expects_zero_workers(seeded_db_empty_cards):
    """A kill-switched provider expects ZERO workers, not its pool width.

    The containerized deployment runs no codex/claude workers by design, so
    reading the worker-count setting unconditionally reported a permanent
    0-of-2 for both from the 2026-07-08 Docker cutover onward. Asserts both
    directions: disabled -> 0/0 (quiet), enabled-but-absent -> 2/0 (loud).
    """
    from datetime import UTC, datetime, timedelta

    from uw_scan.api.routers.health import _provider_ai_health

    common = {
        "repo": seeded_db_empty_cards,
        "now_utc": datetime.now(UTC),
        "provider": "codex",
        "expected_count": 2,
        "fresh_window": timedelta(seconds=66),
    }

    off = _provider_ai_health(enabled=False, **common)
    assert (off.workers_expected, off.workers_healthy) == (0, 0)

    # No heartbeat seeded, so an ENABLED pool must still read as unhealthy —
    # the fix must not silence a provider that is genuinely supposed to run.
    on = _provider_ai_health(enabled=True, **common)
    assert (on.workers_expected, on.workers_healthy) == (2, 0)
