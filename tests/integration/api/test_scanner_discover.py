"""GET /api/scanner/discover — thin read of the latest persisted discovery
snapshot (the live-fetch path moved into worker.jobs.discovery_scan)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_discover_reads_latest_snapshot(client, seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    sigs.insert_candidate_snapshots_bulk(
        run_id=run_id,
        section="discovery",
        rows=[
            {
                "ticker": "ZAAA",
                "scored_at": datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc),
                "bias": "bullish",
                "direction": "long",
                "score": Decimal("78.5"),
                "score_model": "edge_quality_v1",
                "score_breakdown": {"dp_strength": 24.0, "sweeps": 15.0},
                "spot_at_signal": Decimal("5.20"),
                "is_type_f": None,
                "evidence": {
                    "dp_direction": "ACCUMULATION",
                    "dp_strength": "80.0",
                    "dp_sustained_days": 2,
                    "confluence": True,
                    "vol_oi": "2.4",
                    "sweeps": 2,
                },
            }
        ],
    )
    sigs.upsert_discovery_run_meta(
        run_id, {"alerts_pulled": 180, "earnings_unknown_dropped": 5}
    )
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()

    resp = client.get("/api/scanner/discover?limit=20")
    assert resp.status_code == 200
    body = resp.json()
    assert body["alerts_pulled"] == 180
    assert body["earnings_unknown_dropped"] == 5
    assert body["source"] == "scanner_candidate_snapshots"
    assert len(body["candidates"]) == 1
    c = body["candidates"][0]
    assert c["ticker"] == "ZAAA"
    assert c["score_model"] == "edge_quality_v1"
    assert c["dp_direction"] == "ACCUMULATION"
    assert c["confluence"] is True
    assert c["sweeps"] == 2


def test_discover_empty_when_no_runs(client, seeded_db_empty_cards):
    resp = client.get("/api/scanner/discover")
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"] == []
    assert body["alerts_pulled"] == 0
