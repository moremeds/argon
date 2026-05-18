"""GET /api/scanner — shape, empty state, type-F filter."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_empty_response_when_no_recent_scans(client, seeded_db_empty_cards):
    # 54 tickers seeded into watchlist, zero scan_runs -> empty candidates
    # AND empty gated (GATED is regime-only per spec §9; tickers with no
    # recent scanner-producing run are silently dropped).
    r = client.get("/api/scanner")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == []
    assert body["gated"] == []
    assert body["candidates_with_hits"] == 0
    assert body["scanned_universe_size"] >= 1


def test_dcf_candidate_appears_with_hits_and_gates(client, seeded_db_with_cards):
    """seeded_db_with_cards already inserts one scan_run + one
    watchlist_card for TSLA. We add the scanner outputs on top."""
    repo: Repository = seeded_db_with_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    # Use the run_id created by seeded_db_with_cards (TSLA's latest run)
    run_id = repo.latest_run_id("TSLA")
    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="TSLA",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.85"),
        evidence={"qualifying_alerts": 2},
        freshness="live",
    )
    sigs.upsert_gate(
        run_id=run_id,
        ticker="TSLA",
        earnings="pass",
        liquidity="pass",
        regime="pass",
    )
    repo.conn.commit()

    r = client.get("/api/scanner")
    assert r.status_code == 200
    body = r.json()
    candidates = body["candidates"]
    tsla = next((c for c in candidates if c["ticker"] == "TSLA"), None)
    assert tsla is not None
    assert any(h["signal_type"] == "deep_conviction_flow" for h in tsla["hits"])
    assert tsla["gates"]["regime"] == "pass"
    # spot is whatever seeded_db_with_cards inserted (445.12)
    assert Decimal(tsla["spot"]) == Decimal("445.12")


def test_type_f_only_filter_excludes_single_signal_candidate(
    client, seeded_db_with_cards
):
    repo: Repository = seeded_db_with_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.latest_run_id("TSLA")
    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="TSLA",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.85"),
        evidence={},
        freshness="live",
    )
    sigs.upsert_gate(
        run_id=run_id,
        ticker="TSLA",
        earnings="pass",
        liquidity="pass",
        regime="pass",
    )
    repo.conn.commit()

    r = client.get("/api/scanner?type_f_only=true")
    assert r.status_code == 200
    candidates = r.json()["candidates"]
    assert all(c["ticker"] != "TSLA" for c in candidates)


def test_regime_block_gate_row_is_ignored_by_scanner_endpoint(
    client, seeded_db_with_cards
):
    repo: Repository = seeded_db_with_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.latest_run_id("TSLA")
    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="TSLA",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.85"),
        evidence={},
        freshness="live",
    )
    sigs.upsert_gate(
        run_id=run_id,
        ticker="TSLA",
        earnings="pass",
        liquidity="pass",
        regime="block",
    )
    repo.conn.commit()

    r = client.get("/api/scanner")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] == []
    tsla = next(c for c in body["candidates"] if c["ticker"] == "TSLA")
    assert tsla["gates"]["regime"] == "pass"
