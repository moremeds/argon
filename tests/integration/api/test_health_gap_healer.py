"""The /api/health gap_healer block is wired and serialized (distinct from
freshness). Empty-state shape is enough here; populated logic is covered by the
repository test (gap_healer_health)."""

from __future__ import annotations


def test_health_includes_gap_healer_block(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    gh = resp.json()["gap_healer"]
    assert gh is not None
    assert {
        "latest_run_id",
        "latest_run_status",
        "open_gaps",
        "open_by_dataset",
        "healed",
        "no_data",
        "failed",
        "skipped_budget",
        "running",
        "last_verified_at",
    } <= set(gh.keys())
    # empty state defaults
    assert gh["open_gaps"] == 0
    assert gh["running"] == 0
    assert gh["open_by_dataset"] == {}
