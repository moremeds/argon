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


def test_vcg_validation_stress_history_contract(seed_vcg_backtest_run, client) -> None:
    """stress_history surfaces every daily row whose level is one of the
    three stress states (PANIC / RISK_OFF / EDR), in most-recent-first order.

    The conftest fixture seeds 4 daily rows: 3 stress + 1 NORMAL. The NORMAL
    row must NOT appear; the stress rows must appear in date-desc order with
    their payload fields surfaced verbatim.
    """
    resp = client.get("/api/regime/vcg-validation")
    body = resp.json()
    stress = body["stress_history"]
    # NORMAL row excluded; three stress rows present.
    assert len(stress) == 3
    # Most-recent-first ordering (date desc).
    assert [r["date"] for r in stress] == ["2024-06-10", "2024-03-01", "2024-01-15"]
    assert [r["interpretation"] for r in stress] == ["EDR", "RISK_OFF", "PANIC"]
    # PANIC row exposes the v2 percentile-rank payload fields verbatim.
    panic = stress[2]
    assert panic["pi_panic"] == 1.20
    assert panic["vix_percentile_rank"] == 0.992
    assert panic["vvix_percentile_rank"] == 0.985
    assert panic["sign_ok"] is True


def test_vcg_validation_includes_stress_history_summary(
    seed_vcg_backtest_run, client
) -> None:
    """The endpoint must expose stress_history_summary and per-entry
    forward-return fields. Values may be null on a fresh test DB with no
    SPX vol_index_daily rows — structural check only."""
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Per-entry structure: every stress row carries the three fwd keys.
    sh = body["stress_history"]
    assert sh, "expected non-empty stress_history in seeded backtest"
    for row in sh:
        for key in ("fwd_5d_pct", "fwd_20d_pct", "fwd_60d_pct"):
            assert key in row, f"missing {key} on stress_history entry {row['date']}"

    # Summary structure: non-None when stress_history is non-empty.
    assert "stress_history_summary" in body
    summary = body["stress_history_summary"]
    assert summary is not None
    assert "by_interpretation" in summary
    assert len(summary["by_interpretation"]) >= 1
    for row in summary["by_interpretation"]:
        for key in (
            "interpretation",
            "n",
            "mean_fwd_5d_pct",
            "mean_fwd_20d_pct",
            "mean_fwd_60d_pct",
            "winrate_20d_pct",
            "winrate_60d_pct",
        ):
            assert key in row


def test_vcg_validation_summary_values_match_published_probes(
    seed_vcg_backtest_run, client
) -> None:
    """Numeric check against the published probe note values.
    Gated by env flag — only runs when the local DB has the production
    backtest (run_id=31, 4,710 days). CI seeds do not satisfy this."""
    import math
    import os

    if os.getenv("VCG_FULL_BACKTEST_AVAILABLE") != "1":
        import pytest

        pytest.skip(
            "requires production backtest fixture (set VCG_FULL_BACKTEST_AVAILABLE=1 locally)"
        )

    resp = client.get("/api/regime/vcg-validation")
    body = resp.json()
    by = {
        row["interpretation"]: row
        for row in body["stress_history_summary"]["by_interpretation"]
    }

    # Published probe values (docs/research/regime/vcg-forward-return-probes-2026-05-28.md):
    assert by["PANIC"]["n"] == 83
    assert math.isclose(by["PANIC"]["mean_fwd_20d_pct"], 2.88, abs_tol=0.05)
    assert by["RISK_OFF"]["n"] == 133
    assert math.isclose(by["RISK_OFF"]["mean_fwd_60d_pct"], 3.04, abs_tol=0.05)


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
