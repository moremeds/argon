"""Endpoint contract test for GET /api/regime/validation.

Source of truth is uw_scan.regime_backtest_runs (the file fallback was
removed once the prod gate in
docs/superpowers/specs/2026-05-24-regime-research-closure-design.md §10.4
was satisfied).
"""

from __future__ import annotations


def test_validation_endpoint_returns_backtest_md(seed_cri_backtest_run, client) -> None:
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 200
    body = resp.json()
    assert "backtest_md" in body
    assert body["backtest_md"].startswith("# CRI Backtest")
    assert "backtest_csv_rows" in body
    assert body["backtest_csv_rows"] > 0


def test_validation_endpoint_includes_oos_summary(
    seed_cri_backtest_run, client
) -> None:
    resp = client.get("/api/regime/validation")
    body = resp.json()
    assert body["oos"] is not None
    assert body["oos"]["interpretation"]
    assert len(body["oos"]["scores"]) >= 2


def test_validation_503_when_no_completed_run(seeded_db_empty_cards, client) -> None:
    """503 when uw_scan.regime_backtest_runs has no completed CRI row.

    seeded_db_empty_cards resets the schema so no completed run exists.
    The router has no on-disk fallback anymore — it must return 503 with
    an actionable message pointing operators at scripts/backtest_cri.py.
    """
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 503
    assert "scripts/backtest_cri.py" in resp.json()["detail"]
