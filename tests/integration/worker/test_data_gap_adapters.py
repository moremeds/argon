"""Heal-dispatch engine tests. Fake HealSpecs over daily_ohlc exercise every
strategy + the UW budget cap + verify->healed/no_data/failed, with no live
providers. Proves the executor maps dataset -> registry entry -> adapter spec
and only marks healed when the row is actually present."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.data_gap_healer import GapItem
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_adapters import (
    HealContext,
    HealSpec,
    RequestBudget,
    execute_run,
)

_TODAY = date(2026, 6, 30)


def _ctx(seeded, uw_cap=None) -> HealContext:
    gap = DataGapHealerRepository(seeded.conn, schema=seeded._schema)
    return HealContext(
        repo=seeded,
        gap=gap,
        schema=seeded._schema,
        today=_TODAY,
        budget=RequestBudget(uw_cap),
    )


def _insert_ohlc(repo, ticker: str, d: date) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.daily_ohlc (ticker, date, close, source) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (ticker, d, 1.0, "test-heal"),
        )
    repo.conn.commit()


def _run_with_items(seeded, items, spec, *, uw_cap=None) -> dict:
    ctx = _ctx(seeded, uw_cap=uw_cap)
    run_id = ctx.gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=["daily_ohlc"]
    )
    ctx.gap.upsert_items(run_id, items)
    outcome = execute_run(ctx, run_id, specs={"daily_ohlc": spec})
    return {"run_id": run_id, "outcome": outcome, "gap": ctx.gap}


def test_per_ticker_range_heals_when_rows_appear(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d1, d2 = date(2026, 6, 22), date(2026, 6, 23)
    items = [
        GapItem("daily_ohlc", "2026-06-22|KORU", d1, "KORU", 1, 0),
        GapItem("daily_ohlc", "2026-06-23|KORU", d2, "KORU", 1, 0),
    ]

    def fake_range(ctx, ticker, lo, hi):
        d = lo
        while d <= hi:
            _insert_ohlc(ctx.repo, ticker, d)
            d += timedelta(days=1)
        return 1

    spec = HealSpec("daily_ohlc", "massive", "per_ticker_range", fake_range)
    res = _run_with_items(repo, items, spec)
    assert res["outcome"] == {"healed": 2}
    assert res["gap"].count_items_by_status(res["run_id"]) == {"healed": 2}


def test_per_ticker_date_respects_uw_budget(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    items = [
        GapItem("daily_ohlc", "2026-06-22|AAA", date(2026, 6, 22), "AAA", 1, 0),
        GapItem("daily_ohlc", "2026-06-22|BBB", date(2026, 6, 22), "BBB", 1, 0),
        GapItem("daily_ohlc", "2026-06-22|CCC", date(2026, 6, 22), "CCC", 1, 0),
    ]

    def fake_one(ctx, ticker, d):
        _insert_ohlc(ctx.repo, ticker, d)
        return 1

    spec = HealSpec("daily_ohlc", "uw", "per_ticker_date", fake_one, est_per_item=1)
    res = _run_with_items(repo, items, spec, uw_cap=1)
    counts = res["gap"].count_items_by_status(res["run_id"])
    assert counts.get("healed") == 1
    assert counts.get("skipped_budget") == 2


def test_run_once_marks_no_data_when_nothing_appears(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    items = [
        GapItem("daily_ohlc", "2026-01-26|ZZZ", date(2026, 1, 26), "ZZZ", 1, 0),
    ]

    def fake_noop(ctx):
        return 0  # job ran but reconstructed nothing

    spec = HealSpec("daily_ohlc", "db", "run_once", fake_noop, est_per_item=0)
    res = _run_with_items(repo, items, spec)
    assert res["outcome"] == {"no_data": 1}
    rows = res["gap"].list_items(res["run_id"])
    assert rows[0]["status"] == "no_data"
    assert rows[0]["reason"] == "not_recomputed"


def test_failure_marks_item_failed(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    items = [
        GapItem("daily_ohlc", "2026-06-22|AAA", date(2026, 6, 22), "AAA", 1, 0),
    ]

    def fake_raises(ctx, ticker, d):
        raise RuntimeError("provider boom")

    spec = HealSpec("daily_ohlc", "uw", "per_ticker_date", fake_raises, est_per_item=1)
    res = _run_with_items(repo, items, spec)
    assert res["outcome"] == {"failed": 1}
    rows = res["gap"].list_items(res["run_id"])
    assert rows[0]["status"] == "failed"
    assert "boom" in rows[0]["last_error"]


def test_unmapped_adapter_marks_no_data(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    items = [GapItem("daily_ohlc", "2026-06-22|AAA", date(2026, 6, 22), "AAA", 1, 0)]
    # explicit empty specs -> no adapter for daily_ohlc
    ctx = _ctx(repo)
    run_id = ctx.gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=["daily_ohlc"]
    )
    ctx.gap.upsert_items(run_id, items)
    outcome = execute_run(ctx, run_id, specs={})
    assert outcome == {"no_data": 1}
    assert ctx.gap.list_items(run_id)[0]["reason"] == "no_adapter"
