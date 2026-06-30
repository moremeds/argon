from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    GapItem,
    registered_table_names,
)
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository


def _repo(seeded) -> DataGapHealerRepository:
    return DataGapHealerRepository(seeded.conn, schema=seeded._schema)


def test_run_lifecycle(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    run_id = repo.create_run(
        mode="audit",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 29),
        datasets=["option_surface_grid_daily", "daily_ohlc"],
        uw_budget_cap=20000,
    )
    got = repo.get_run(run_id)
    assert got["status"] == "running"
    assert got["mode"] == "audit"
    assert got["datasets"] == ["option_surface_grid_daily", "daily_ohlc"]
    assert got["uw_budget_cap"] == 20000

    repo.finish_run(run_id, status="complete", summary={"checked": 2})
    done = repo.get_run(run_id)
    assert done["status"] == "complete"
    assert done["finished_at"] is not None
    assert done["summary_jsonb"] == {"checked": 2}
    assert repo.latest_run()["id"] == run_id


def test_items_are_gaps_only_and_idempotent(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    run_id = repo.create_run(
        mode="audit", start_date=None, end_date=None, datasets=["daily_ohlc"]
    )
    items = [
        GapItem("daily_ohlc", "2026-06-22|KORU", date(2026, 6, 22), "KORU", 100, 99),
        GapItem("daily_ohlc", "2026-06-22|SOXL", date(2026, 6, 22), "SOXL", 100, 99),
    ]
    assert repo.upsert_items(run_id, items) == 2
    # Re-upserting the same scope_key updates, never duplicates.
    again = [
        GapItem(
            "daily_ohlc",
            "2026-06-22|KORU",
            date(2026, 6, 22),
            "KORU",
            100,
            99,
            reason="still missing",
        )
    ]
    repo.upsert_items(run_id, again)
    rows = repo.list_items(run_id)
    assert len(rows) == 2
    koru = next(r for r in rows if r["ticker"] == "KORU")
    assert koru["reason"] == "still missing"


def test_claim_and_mark_transitions(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    run_id = repo.create_run(
        mode="execute", start_date=None, end_date=None, datasets=["daily_ohlc"]
    )
    repo.upsert_items(
        run_id,
        [
            GapItem("daily_ohlc", "2026-06-22|KORU", date(2026, 6, 22), "KORU", 1, 0),
            GapItem("daily_ohlc", "2026-06-22|SOXL", date(2026, 6, 22), "SOXL", 1, 0),
            GapItem("daily_ohlc", "2026-06-23|KORU", date(2026, 6, 23), "KORU", 1, 0),
        ],
    )
    claimed = repo.claim_next_items(run_id, limit=2)
    assert len(claimed) == 2
    assert repo.count_items_by_status(run_id)["running"] == 2

    by_key = {c["scope_key"]: c for c in claimed}
    repo.mark_item_healed(by_key["2026-06-22|KORU"]["id"], actual_requests=1)
    repo.mark_item_no_data(
        by_key["2026-06-22|SOXL"]["id"], reason="provider_no_history"
    )

    counts = repo.count_items_by_status(run_id)
    assert counts.get("healed") == 1
    assert counts.get("no_data") == 1
    assert counts.get("planned") == 1  # the 06-23 item was never claimed

    healed = next(r for r in repo.list_items(run_id) if r["status"] == "healed")
    assert healed["verified_at"] is not None
    assert healed["actual_requests"] == 1

    # remaining planned item is claimable on the next pass (resume semantics)
    second = repo.claim_next_items(run_id, limit=5)
    assert len(second) == 1
    repo.mark_item_failed(second[0]["id"], last_error="boom")
    assert repo.count_items_by_status(run_id).get("failed") == 1


def test_spcx_caveat_seeded_once_and_upsert_idempotent(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    spcx = repo.list_caveats("option_surface_grid_daily")
    assert len(spcx) == 1
    assert spcx[0].ticker == "SPCX"
    assert spcx[0].end_date == date(2026, 6, 16)

    # re-inserting the identical caveat is a no-op (COALESCE unique index)
    repo.upsert_caveat(spcx[0])
    assert len(repo.list_caveats("option_surface_grid_daily")) == 1


def test_sync_registry_idempotent_and_lists(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    n1 = repo.sync_dataset_registry(REGISTRY)
    rows = repo.list_dataset_registry()
    assert n1 == len(REGISTRY)
    assert len(rows) == len(REGISTRY)
    # re-sync upserts, never duplicates
    repo.sync_dataset_registry(REGISTRY)
    assert len(repo.list_dataset_registry()) == len(REGISTRY)
    osg = next(r for r in rows if r["table_name"] == "option_surface_grid_daily")
    assert osg["audit_mode"] == "strict_ticker_date"
    assert osg["provider"] == "uw"


def test_gap_healer_health_summary(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    assert repo.gap_healer_health()["latest_run_id"] is None  # empty state

    run_id = repo.create_run(
        mode="execute", start_date=None, end_date=None, datasets=["daily_ohlc"]
    )
    repo.upsert_items(
        run_id,
        [
            GapItem("daily_ohlc", "2026-06-22|A", date(2026, 6, 22), "A", 1, 0),
            GapItem("daily_ohlc", "2026-06-23|B", date(2026, 6, 23), "B", 1, 0),
        ],
    )
    h = repo.gap_healer_health()
    assert h["latest_run_id"] == run_id
    assert h["latest_run_status"] == "running"
    assert h["open_by_dataset"]["daily_ohlc"] == 2
    assert h["counts"]["planned"] == 2
    assert h["last_verified_at"] is None


def test_unregistered_excludes_seeded_tables(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.sync_dataset_registry(REGISTRY)
    unreg = repo.list_unregistered_time_tables()
    # Core registry is not yet full coverage (T7), so some temporal tables remain.
    assert isinstance(unreg, list)
    # but no table we DID register may appear as unregistered
    assert registered_table_names(REGISTRY).isdisjoint(unreg)
    # and the healer's own tables (registered) must not show up
    assert "data_gap_runs" not in unreg
    assert "data_gap_dataset_registry" not in unreg
