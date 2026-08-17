"""Nightly gap-healer job: off by default, single-process scheduling, refresh
targets, the guard that skips when a prior run is still active (so it never
fights a manual backfill), and the reaper that stops that guard from wedging
forever on a run whose process was killed."""

from __future__ import annotations

import os
import types
from datetime import date

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.reports.data_gap_healer import GapItem
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_healer import (
    HealerBusy,
    _another_run_active,
    _reap_stale_runs,
    _refresh_targets,
    _single_flight,
    data_gap_healer_job,
)
from uw_scan.worker.scheduler import _should_schedule_data_gap_healer


def _fake_settings(**kw):
    base = {
        "worker_role": "uw",
        "worker_index": 0,
        "data_gap_healer_enabled": True,
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_should_schedule_only_on_one_process_and_when_enabled():
    assert _should_schedule_data_gap_healer(_fake_settings()) is True
    assert _should_schedule_data_gap_healer(_fake_settings(worker_index=1)) is False
    assert (
        _should_schedule_data_gap_healer(_fake_settings(worker_role="massive")) is False
    )
    assert (
        _should_schedule_data_gap_healer(_fake_settings(data_gap_healer_enabled=False))
        is False
    )
    assert _should_schedule_data_gap_healer(_fake_settings(worker_role="all")) is True


def test_refresh_targets_include_macro_and_gold_but_not_strict_per_ticker():
    targets = _refresh_targets(None)
    assert "macro_series_daily" in targets  # run_once_lookback macro_fred
    assert "rates_observations" in targets  # run_once_lookback rates_fred
    assert "gold_posture_daily" in targets  # run_once db
    assert "daily_ohlc" not in targets  # per_ticker_range, item-driven not refresh
    assert "option_surface_grid_daily" not in targets  # per_ticker_date


def test_disabled_returns_skipped():
    out = data_gap_healer_job(settings=_fake_settings(data_gap_healer_enabled=False))
    assert out == {"skipped": "disabled"}


def _enabled_db_settings() -> Settings:
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy")
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]
    return Settings.from_env().model_copy(
        update={"db_name": test_db, "data_gap_healer_enabled": True}
    )


def test_run_active_guard_skips(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    # a prior execute run still 'running' must block the nightly job. It started
    # just now, so the reaper leaves it alone -- the guard is what fires.
    gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=[], status="running"
    )
    out = data_gap_healer_job(settings=_enabled_db_settings(), today=date(2026, 6, 30))
    assert out == {"skipped": "run_active"}


def _killed_run(
    gap: DataGapHealerRepository,
    conn,
    *,
    started_hours_ago: int,
    verified_hours_ago: int | None = None,
    mode: str = "execute",
) -> int:
    """A run whose process died: run row stuck 'running', one item stranded
    'running' (claim_next_items skips that status, so it is unhealable)."""
    run_id = gap.create_run(
        mode=mode, start_date=None, end_date=None, datasets=[], status="running"
    )
    gap.upsert_items(
        run_id,
        [
            GapItem(
                dataset="daily_ohlc",
                scope_key="2026-06-30|SPY",
                data_date=date(2026, 6, 30),
                ticker="SPY",
                expected_count=1,
                covered_count=0,
                status="running",
            )
        ],
    )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE data_gap_runs SET started_at = now() - make_interval(hours => %s) "
            "WHERE id = %s",
            (started_hours_ago, run_id),
        )
        if verified_hours_ago is not None:
            cur.execute(
                "UPDATE data_gap_items SET verified_at = now() - "
                "make_interval(hours => %s) WHERE run_id = %s",
                (verified_hours_ago, run_id),
            )
    conn.commit()
    return run_id


def test_stale_run_is_reaped_and_unwedges_the_guard(seeded_db_empty_cards):
    """The defect this fixes: nothing ever timed out a killed run, so
    _another_run_active stayed True and the nightly job skipped itself forever."""
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    run_id = _killed_run(gap, repo.conn, started_hours_ago=48)

    assert _another_run_active(gap) is True  # wedged
    assert _reap_stale_runs(gap) == [run_id]

    run = gap.get_run(run_id)
    assert run["status"] == "cancelled"  # not 'complete' -- it did not finish
    assert run["finished_at"] is not None
    assert "cancelled_reason" in run["summary_jsonb"]
    # the orphaned item is claimable again
    assert gap.count_items_by_status(run_id) == {"planned": 1}
    assert _another_run_active(gap) is False


def test_reaping_never_rolls_back_a_verdict(seeded_db_empty_cards):
    """The property that makes the one reachable false positive harmless: a live
    run reaped mid-flight (provider hard-down, every request burning its timeout,
    so verified_at never advances) must keep every verdict it already reached.
    Only 'running' rows move."""
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    run_id = _killed_run(gap, repo.conn, started_hours_ago=48)
    # give the run one item in each terminal-ish status alongside the 'running' one
    gap.upsert_items(
        run_id,
        [
            GapItem(
                dataset="daily_ohlc",
                scope_key=f"2026-06-30|{ticker}",
                data_date=date(2026, 6, 30),
                ticker=ticker,
                expected_count=1,
                covered_count=0,
                status=status,
            )
            for ticker, status in (
                ("AAPL", "healed"),
                ("NVDA", "no_data"),
                ("MSFT", "failed"),
                ("AMD", "skipped_budget"),
                ("TSLA", "planned"),
            )
        ],
    )

    assert _reap_stale_runs(gap) == [run_id]

    counts = gap.count_items_by_status(run_id)
    assert counts["healed"] == 1
    assert counts["no_data"] == 1
    assert counts["failed"] == 1
    assert counts["skipped_budget"] == 1
    assert counts["planned"] == 2  # the pre-existing one + the requeued 'running'
    assert "running" not in counts


def test_reaper_spares_live_runs(seeded_db_empty_cards):
    """Three runs the reaper must not touch: a young one, a long-running manual
    backfill that is still verifying items, and an audit-mode run (the gate only
    looks at execute runs, so cancelling those would be pure collateral damage)."""
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    young = _killed_run(gap, repo.conn, started_hours_ago=1)
    busy = _killed_run(gap, repo.conn, started_hours_ago=72, verified_hours_ago=0)
    auditing = _killed_run(gap, repo.conn, started_hours_ago=72, mode="audit")

    assert _reap_stale_runs(gap) == []
    for run_id in (young, busy, auditing):
        assert gap.get_run(run_id)["status"] == "running"


def test_single_flight_refuses_a_second_connection(seeded_db_empty_cards):
    """The lock is what makes the reaper safe: it is session-scoped, so Postgres
    frees it when a process dies, and a LIVE heal therefore blocks the nightly job
    at `{"skipped": "locked"}` before the reaper ever inspects a row. Without it a
    live-but-idle run could be reaped and then raced by a fresh nightly run over
    the same still-missing gaps -- double-charging the provider budget."""
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    settings = _enabled_db_settings()

    with psycopg.connect(settings.db_dsn()) as other_conn:
        other = DataGapHealerRepository(other_conn, schema=repo._schema)
        with _single_flight(gap):  # stands in for a live manual heal
            with pytest.raises(HealerBusy):
                with _single_flight(other):
                    pass
            # ...and the nightly job stands down entirely rather than reaping
            out = data_gap_healer_job(settings=settings, today=date(2026, 6, 30))
            assert out == {"skipped": "locked"}
        # released on exit, so the next caller gets it
        with _single_flight(other):
            pass


def test_single_flight_is_reentrant_on_one_connection(seeded_db_empty_cards):
    """data_freshness_monitor takes this lock and then calls execute_into_run,
    which takes it again on the same connection. Session locks are counted, so
    the nested acquire must succeed and the counter must balance."""
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    settings = _enabled_db_settings()

    with _single_flight(gap):
        with _single_flight(gap):  # nested, same session
            pass
    # fully released: a different connection can now take it
    with psycopg.connect(settings.db_dsn()) as other_conn:
        with _single_flight(DataGapHealerRepository(other_conn, schema=repo._schema)):
            pass


def test_job_reaps_before_it_checks_the_guard(seeded_db_empty_cards):
    """The job itself must reap, not just the helper. A genuinely live run is kept
    alongside so the job still short-circuits at the guard instead of running a
    full audit+heal (which would reach out to providers) inside a test."""
    repo = seeded_db_empty_cards
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    stale = _killed_run(gap, repo.conn, started_hours_ago=48)
    gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=[], status="running"
    )

    out = data_gap_healer_job(settings=_enabled_db_settings(), today=date(2026, 6, 30))
    assert out == {"skipped": "run_active"}
    # the durable effect is the proof the reap ran inside the job, before the gate
    assert gap.get_run(stale)["status"] == "cancelled"
