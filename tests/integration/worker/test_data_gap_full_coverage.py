"""Full-coverage gate (T7): every temporal table in the schema is registered,
and the macro/FRED/rates/gold refresh path dispatches to existing ingest jobs."""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_healer import REGISTRY
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_adapters import (
    HealContext,
    HealSpec,
    RequestBudget,
    run_refresh_adapters,
)


def _gap(seeded) -> DataGapHealerRepository:
    return DataGapHealerRepository(seeded.conn, schema=seeded._schema)


def test_zero_unregistered_after_full_registry(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    gap = _gap(repo)
    gap.sync_dataset_registry(REGISTRY)
    unreg = gap.list_unregistered_time_tables()
    assert unreg == [], f"unregistered temporal tables remain: {unreg}"


def _ctx(seeded, uw_cap=None) -> HealContext:
    return HealContext(
        repo=seeded,
        gap=_gap(seeded),
        schema=seeded._schema,
        today=date(2026, 6, 30),
        budget=RequestBudget(uw_cap),
    )


def test_refresh_adapters_dispatch_and_budget(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    calls: list[tuple[str, int]] = []

    def fake_macro(ctx, lookback_days):
        calls.append(("macro", lookback_days))
        return 0

    def fake_uw(ctx):
        calls.append(("uw", 0))
        return 0

    specs = {
        "macro_fred": HealSpec(
            "macro_fred", "external", "run_once_lookback", fake_macro
        ),
        "gold_uw_options": HealSpec(
            "gold_uw_options", "uw", "run_once", fake_uw, est_per_item=50
        ),
    }

    # external is uncapped -> macro refreshes; uw cap 0 -> gold uw options skipped
    ctx = _ctx(repo, uw_cap=0)
    out = run_refresh_adapters(
        ctx,
        ["macro_series_daily", "uw_gold_options_daily"],
        lookback_days=45,
        specs=specs,
    )
    assert out["macro_series_daily"] == "refreshed"
    assert out["uw_gold_options_daily"] == "skipped_budget"
    assert ("macro", 45) in calls
    assert ("uw", 0) not in calls  # never ran (budget)


def test_refresh_adapter_unknown_dataset_is_no_adapter(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ctx = _ctx(repo)
    out = run_refresh_adapters(ctx, ["flow_events"], lookback_days=45, specs={})
    assert out["flow_events"] == "no_adapter"  # freshness_only, no heal
