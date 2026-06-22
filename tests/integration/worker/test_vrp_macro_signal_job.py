from __future__ import annotations

from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.vrp_macro_signal import vrp_macro_signal_refresh

# The happy path (SPX/QQQ/IWM compute → persist) is verified end-to-end against
# the real dev DB — a faithful in-test happy path would need a ~273-row real
# VIX/SPX fixture (the rv/z windows are 20/252), which we don't fabricate. These
# tests pin the production-critical property instead: a name with missing/stale
# vol data must fail gracefully without crashing the scheduler.


def test_refresh_isolates_missing_vol_data(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    settings = Settings.from_env()

    out = vrp_macro_signal_refresh(
        repo=repo, settings=settings, snapshot_date=date(2026, 6, 22)
    )

    # Empty vol_index_daily → every name's compute fails, but the job returns a
    # clean per-name accounting and never raises.
    assert out["persisted"] == 0
    assert set(out["failed"]) == {"SPX", "QQQ", "IWM"}
    assert out["snapshot_date"] == date(2026, 6, 22)
    assert repo.fetch_latest_vrp_macro_signals() == []


def test_refresh_is_safe_to_rerun(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    settings = Settings.from_env()

    out = None
    for _ in range(2):
        out = vrp_macro_signal_refresh(
            repo=repo, settings=settings, snapshot_date=date(2026, 6, 22)
        )

    assert out is not None
    assert out["persisted"] == 0
    assert repo.fetch_latest_vrp_macro_signals() == []
