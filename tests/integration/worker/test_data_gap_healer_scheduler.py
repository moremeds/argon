"""Nightly gap-healer job: off by default, single-process scheduling, refresh
targets, and the guard that skips when a prior run is still active (so it never
fights a manual backfill)."""

from __future__ import annotations

import os
import types
from datetime import date

from uw_scan.config import Settings
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.worker.jobs.data_gap_healer import (
    _refresh_targets,
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
    # a prior execute run still 'running' must block the nightly job
    gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=[], status="running"
    )
    out = data_gap_healer_job(settings=_enabled_db_settings(), today=date(2026, 6, 30))
    assert out == {"skipped": "run_active"}
