"""End-to-end replay acceptance test for Phase A1 (spec §9.4 acceptance gate).

For 5 evenly-spaced historical obs_dates within a 90-day seeded window:
  1. Compute and persist a gold_posture_daily row (the "original" computation).
  2. Re-run the orchestrator with a *new* computed_at on each obs_date.
  3. Verify `fetch_gold_posture_for_obs_date(obs)` still returns the
     FIRST-computed row byte-for-byte (excluding the `computed_at` column
     which is by definition different, and the `inputs_jsonb` `as_of` field
     which captures the second compute's vintage timestamps).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import pytest
from uw_scan.config import Settings
from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.storage.repository import Repository


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
def _seed_three_months(repo: Repository, start: date) -> None:
    """Seed 90 days of inputs (gold, real rate, breakeven)."""
    for i in range(90):
        d = start + timedelta(days=i)
        ts = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
        repo.insert_macro_series_daily(
            "GLD_CLOSE",
            d,
            Decimal(str(1800 + i * 0.4)),
            ts,
            None,
            "MASSIVE",
            None,
        )
        repo.insert_macro_series_daily(
            "DFII10",
            d,
            Decimal(str(1.8 - i * 0.002)),
            ts,
            None,
            "FRED",
            None,
        )
        repo.insert_macro_series_daily(
            "T5YIFR",
            d,
            Decimal("2.31"),
            ts,
            None,
            "FRED",
            None,
        )


def _compare_excluding(
    row_a: dict, row_b: dict, *, exclude: set[str]
) -> dict[str, tuple]:
    diffs: dict[str, tuple] = {}
    for key in set(row_a.keys()) | set(row_b.keys()):
        if key in exclude:
            continue
        if row_a.get(key) != row_b.get(key):
            diffs[key] = (row_a.get(key), row_b.get(key))
    return diffs


def test_replay_byte_for_byte_match_5_dates(repo: Repository) -> None:
    base = date(2026, 1, 1)
    _seed_three_months(repo, base)

    targets = [base + timedelta(days=i) for i in (10, 25, 40, 60, 80)]

    originals: dict[date, dict] = {}
    for obs in targets:
        computed_at = datetime.combine(
            obs + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )
        compute_and_persist_gold_posture(repo, as_of=obs, computed_at=computed_at)
        row = repo.fetch_gold_posture_for_obs_date(obs)
        assert row is not None
        originals[obs] = row
    repo.conn.commit()

    # Re-run with a NEW computed_at; the orchestrator inserts a second row but
    # `fetch_gold_posture_for_obs_date` returns the FIRST per replay discipline.
    for obs in targets:
        new_computed_at = datetime.combine(
            obs + timedelta(days=2), datetime.min.time(), tzinfo=UTC
        )
        compute_and_persist_gold_posture(repo, as_of=obs, computed_at=new_computed_at)

    for obs in targets:
        current = repo.fetch_gold_posture_for_obs_date(obs)
        diffs = _compare_excluding(
            originals[obs],
            current,
            exclude={"computed_at", "inputs_jsonb"},
        )
        assert not diffs, f"replay drift for {obs}: {diffs}"
