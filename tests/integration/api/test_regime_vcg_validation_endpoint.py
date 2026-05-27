"""Endpoint contract test for GET /api/regime/vcg-validation.

Source of truth is uw_scan.regime_backtest_runs. No on-disk fallback; the
endpoint returns 503 when there's no completed VCG run at the current
COMPOSITE_VERSION.
"""

from __future__ import annotations

from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION as VCG_COMPOSITE_VERSION


def test_vcg_validation_endpoint_returns_payload(seed_vcg_backtest_run, client) -> None:
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["credit_proxy"] == "HYG"
    assert body["n_days"] >= 1
    assert body["composite_version"] == str(VCG_COMPOSITE_VERSION)
    assert len(body["interpretation_distribution"]) >= 1
    # First entry is the largest count (router sorts desc by n).
    assert body["interpretation_distribution"][0]["interpretation"] == "SUPPRESSED"


def test_vcg_validation_named_crash_window_shape(seed_vcg_backtest_run, client) -> None:
    """Locks the named_crash_window contract the endpoint code asserts.

    Persisted JSON uses `offset_d` keys; the response must (a) translate to
    `offset_days`, (b) look up event labels via NAMED_CRASH_DATES, (c) emit
    offsets in ascending order, (d) preserve all 7 entries from the fixture.
    """
    resp = client.get("/api/regime/vcg-validation")
    body = resp.json()
    events = body["named_crash_window"]
    assert len(events) == 1, "fixture seeds exactly one event"
    ev = events[0]
    assert ev["date"] == "2008-09-15"
    assert ev["label"] == "Lehman bankruptcy"
    offsets = ev["offsets"]
    assert [o["offset_days"] for o in offsets] == [-5, -3, -1, 0, 1, 3, 5]
    assert all(isinstance(o["offset_days"], int) for o in offsets)


def test_vcg_validation_503_when_no_completed_run(
    seeded_db_empty_cards, client
) -> None:
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 503
    assert "scripts/backtest_vcg.py" in resp.json()["detail"]


def test_vcg_validation_handles_missing_extras(seeded_db_empty_cards, client) -> None:
    """Endpoint must not crash when summary.extras lacks distribution or window."""
    from datetime import date as _date

    from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION as V
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    run_id = rb.insert_run(
        indicator="vcg",
        composite_version=str(V),
        start_date=_date(2024, 1, 1),
        end_date=_date(2024, 1, 2),
        window_days=21,
        n_days=1,
        params={},
        summary={"oos": None, "extras": {"credit_proxy": "HYG"}},
        note="edge-case test",
    )
    rb.bulk_insert_daily(
        run_id,
        [
            {
                "trade_date": _date(2024, 1, 2),
                "score": 0.0,
                "level": "NORMAL",
                "payload": {},
            }
        ],
    )
    rb.mark_run_completed(run_id)
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["interpretation_distribution"] == []
    assert body["named_crash_window"] == []
