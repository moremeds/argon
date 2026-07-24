"""Load-bearing Phase-4 verification: the 3 strict UW-alpha daily tables
self-heal a synthetically-missing (ticker, date) through the REAL execute_run
path — audit dispatch -> _run_<adapter> -> capture_*_for -> _verify_covered ->
mark_item_healed. No live UW: the sibling _FakeUwClient replays frozen fixtures.

This exercises the real HEAL_SPECS + REGISTRY (not a fake spec), so a broken
adapter, a missing registry entry, or a wrong granularity fails here.
"""

from __future__ import annotations


from uw_scan.reports.data_gap_healer import GapItem
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_adapters import (
    HealContext,
    RequestBudget,
    execute_run,
)

from .test_uw_alpha_capture import MD, _FakeUwClient


def _heal_one(seeded, dataset: str, ticker: str = "AAPL") -> dict:
    """Create one missing (ticker, MD) gap item for `dataset` and heal it via
    the real execute_run + real HEAL_SPECS. Returns the outcome counter."""
    gap = DataGapHealerRepository(seeded.conn, schema=seeded._schema)
    ctx = HealContext(
        repo=seeded,
        gap=gap,
        schema=seeded._schema,
        today=MD,
        budget=RequestBudget(100),
        _uw=_FakeUwClient(),  # replays fixtures; ctx.uw_client() returns this
    )
    run_id = gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=[dataset]
    )
    gap.upsert_items(
        run_id, [GapItem(dataset, f"{MD.isoformat()}|{ticker}", MD, ticker, 1, 0)]
    )
    return execute_run(ctx, run_id, datasets=[dataset])


def _row_count(repo, table: str, ticker: str = "AAPL") -> int:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {repo._schema}.{table} "
            "WHERE ticker=%s AND market_date=%s",
            (ticker, MD),
        )
        return cur.fetchone()[0]


def test_gex_levels_heal_closes_a_deleted_gap(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    assert _row_count(repo, "uw_gex_levels_daily") == 0  # precondition: gap
    outcome = _heal_one(repo, "uw_gex_levels_daily")
    assert outcome.get("healed") == 1
    assert _row_count(repo, "uw_gex_levels_daily") == 1  # gap closed


def test_volatility_signal_heal_closes_a_deleted_gap(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    assert _row_count(repo, "uw_volatility_signal_daily") == 0
    outcome = _heal_one(repo, "uw_volatility_signal_daily")
    assert outcome.get("healed") == 1
    assert _row_count(repo, "uw_volatility_signal_daily") == 1


def test_short_pressure_heal_closes_a_deleted_gap(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    assert _row_count(repo, "uw_short_pressure_daily") == 0
    outcome = _heal_one(repo, "uw_short_pressure_daily")
    assert outcome.get("healed") == 1
    assert _row_count(repo, "uw_short_pressure_daily") == 1
