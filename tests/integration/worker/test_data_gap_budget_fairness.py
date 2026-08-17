"""A big backlog must not consume the whole nightly cap (Task 9).

Measured against production config on the mini: enabled=True,
max_uw_calls=12000, start=2026-01-01, all datasets. option_surface_grid_daily
is the first UW spender in REGISTRY at est_per_item=20, so a 4,206-item
backlog needs ~84,120 calls — seven nights during which every other UW dataset
records skipped_budget.
"""

from __future__ import annotations

from uw_scan.worker.jobs.data_gap_adapters import RequestBudget


def test_dataset_slice_caps_one_dataset() -> None:
    b = RequestBudget(uw_cap=1000, dataset_share=0.4)  # slice = 400

    b.begin_dataset("option_surface_grid_daily")
    spent = 0
    while b.can_spend("uw", 20):
        b.record("uw", 20)
        spent += 20
    assert spent == 400, "one dataset must stop at its slice, not the global cap"

    # A second dataset still has room, which is the entire point.
    b.begin_dataset("uw_gex_levels_daily")
    assert b.can_spend("uw", 20)


def test_global_cap_still_binds_across_datasets() -> None:
    b = RequestBudget(uw_cap=1000, dataset_share=0.4)
    for i in range(3):  # 3 x 400 would be 1200 > 1000
        b.begin_dataset(f"ds{i}")
        while b.can_spend("uw", 100):
            b.record("uw", 100)
    assert b.spent["uw"] == 1000, "the global cap must still win"


def test_no_share_configured_behaves_exactly_as_before() -> None:
    b = RequestBudget(uw_cap=1000)
    b.begin_dataset("anything")
    while b.can_spend("uw", 100):
        b.record("uw", 100)
    assert b.spent["uw"] == 1000


def test_uncapped_provider_is_unaffected() -> None:
    b = RequestBudget(uw_cap=100, dataset_share=0.4)
    b.begin_dataset("lake_thing")
    assert b.can_spend("massive", 10_000)  # only uw is capped


# --- the permanent no_data tax ---------------------------------------------
# The audit is a set-difference against the real table, so an item the provider
# genuinely cannot serve is missing again tomorrow, re-planned as a fresh item,
# and re-attempted at full est_per_item every night, forever. upsert_caveat and
# eligible_tickers_for_date already existed to suppress this; nothing populated
# them automatically.


def _run_with_no_data(repo, dataset: str, ticker: str, d, *, settings, runs: int):
    """Drive N heal runs whose adapter writes nothing, so every item verifies
    false and is recorded provider_no_data."""
    from uw_scan.reports.data_gap_healer import GapItem
    from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
    from uw_scan.worker.jobs.data_gap_adapters import (
        HealContext,
        HealSpec,
        RequestBudget,
        execute_run,
    )

    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    spec = HealSpec(dataset, "uw", "per_ticker_date", lambda ctx, t, md: 0)
    for _ in range(runs):
        run_id = gap.create_run(
            mode="execute", start_date=None, end_date=None, datasets=[dataset]
        )
        gap.upsert_items(
            run_id, [GapItem(dataset, f"{d.isoformat()}|{ticker}", d, ticker, 1, 0)]
        )
        ctx = HealContext(
            repo=repo,
            gap=gap,
            schema=repo._schema,
            today=d,
            budget=RequestBudget(uw_cap=None),
            settings=settings,
        )
        ctx._uw = object()
        execute_run(ctx, run_id, specs={dataset: spec})
    return gap


def test_repeated_provider_no_data_auto_caveats_the_scope(
    seeded_db_empty_cards,
) -> None:
    from datetime import date

    from uw_scan.config import Settings

    repo = seeded_db_empty_cards
    settings = Settings.from_env().model_copy(
        update={"data_gap_healer_no_data_caveat_after": 3}
    )
    d = date(2026, 2, 3)
    gap = _run_with_no_data(
        repo, "greek_exposure_daily", "KORU", d, settings=settings, runs=4
    )

    auto = [c for c in gap.list_caveats("greek_exposure_daily") if c.source == "auto"]
    assert len(auto) == 1, "3 consecutive provider_no_data verdicts must caveat once"
    assert auto[0].ticker == "KORU"
    assert (auto[0].start_date, auto[0].end_date) == (d, d)


def test_our_own_bugs_are_never_caveated_away(seeded_db_empty_cards) -> None:
    """no_adapter is OUR defect, not the provider's answer. Caveating it would
    hide exactly the silent-no-op class this plan exists to surface."""
    from datetime import date

    from uw_scan.config import Settings
    from uw_scan.reports.data_gap_healer import GapItem
    from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
    from uw_scan.worker.jobs.data_gap_adapters import (
        HealContext,
        RequestBudget,
        execute_run,
    )

    repo = seeded_db_empty_cards
    settings = Settings.from_env().model_copy(
        update={"data_gap_healer_no_data_caveat_after": 1}
    )
    d = date(2026, 2, 3)
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    for _ in range(3):
        run_id = gap.create_run(
            mode="execute", start_date=None, end_date=None, datasets=["daily_ohlc"]
        )
        gap.upsert_items(
            run_id, [GapItem("daily_ohlc", f"{d.isoformat()}|KORU", d, "KORU", 1, 0)]
        )
        ctx = HealContext(
            repo=repo,
            gap=gap,
            schema=repo._schema,
            today=d,
            budget=RequestBudget(uw_cap=None),
            settings=settings,
        )
        # empty specs -> every item falls through to reason='no_adapter'
        execute_run(ctx, run_id, specs={})

    assert not [c for c in gap.list_caveats("daily_ohlc") if c.source == "auto"]
