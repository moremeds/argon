"""Integration tests for scanner_candidate_snapshots persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_insert_and_fetch_latest_discovery_snapshot(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    scored = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)

    sigs.insert_candidate_snapshots_bulk(
        run_id=run_id,
        section="discovery",
        rows=[
            {
                "ticker": "ZAAA",
                "scored_at": scored,
                "bias": "bullish",
                "direction": "long",
                "score": Decimal("78.500"),
                "score_model": "edge_quality_v1",
                "score_breakdown": {"dp_strength": 24.0, "sweeps": 15.0},
                "spot_at_signal": Decimal("5.20"),
                "is_type_f": None,
                "evidence": {"vol_oi": "2.4", "sweeps": 2},
            },
            {
                "ticker": "ZBBB",
                "scored_at": scored,
                "bias": "bearish",
                "direction": "short",
                "score": Decimal("55.000"),
                "score_model": "edge_quality_v1",
                "score_breakdown": {"dp_strength": 0.0},
                "spot_at_signal": Decimal("40.00"),
                "is_type_f": None,
                "evidence": {},
            },
        ],
    )
    sigs.upsert_discovery_run_meta(
        run_id, {"alerts_pulled": 180, "earnings_unknown_dropped": 12, "dp_enriched": 2}
    )
    repo.finish_scan_run(run_id, status="ok")  # fetch filters status='ok'
    repo.conn.commit()

    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["run_id"] == run_id
    assert snap["alerts_pulled"] == 180
    assert snap["earnings_unknown_dropped"] == 12
    # Ordered by score desc.
    assert [c["ticker"] for c in snap["candidates"]] == ["ZAAA", "ZBBB"]
    assert snap["candidates"][0]["score"] == Decimal("78.500")
    assert snap["candidates"][0]["score_breakdown"]["sweeps"] == 15.0


def test_run_meta_survives_zero_candidate_nonempty_feed(seeded_db_empty_cards):
    """A feed fully filtered to zero candidates still records run counts."""
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    sigs.upsert_discovery_run_meta(
        run_id, {"alerts_pulled": 200, "earnings_unknown_dropped": 200}
    )
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()

    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["candidates"] == []
    assert snap["alerts_pulled"] == 200
    assert snap["earnings_unknown_dropped"] == 200


def test_fetch_latest_discovery_snapshot_empty_run(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()

    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["run_id"] == run_id
    assert snap["candidates"] == []
    assert snap["alerts_pulled"] == 0
    assert snap["earnings_unknown_dropped"] == 0


def test_fetch_latest_discovery_snapshot_none_when_no_runs(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    assert sigs.fetch_latest_discovery_snapshot(limit=20) is None
