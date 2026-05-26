"""API endpoint tests for /api/regime/canary*.

Uses the shared `client` + `seeded_db_empty_cards` fixtures from
tests/integration/conftest.py and tests/integration/api/conftest.py.

The validation gate test asserts `regime_backtest_runs` widening (Task 19.5)
is not strictly required for /canary/validation to return 503 — the row
simply does not exist yet at the canary composite_version, so the
endpoint returns 503 cleanly.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_latest_503_when_no_snapshot(client, seeded_db_empty_cards):
    resp = client.get("/api/regime/canary")
    assert resp.status_code == 503


def test_history_returns_empty_when_no_snapshots(client, seeded_db_empty_cards):
    resp = client.get("/api/regime/canary/history?days=10")
    assert resp.status_code == 200
    assert resp.json() == {"rows": []}


def test_validation_503_when_no_run(client, seeded_db_empty_cards):
    resp = client.get("/api/regime/canary/validation")
    assert resp.status_code == 503
