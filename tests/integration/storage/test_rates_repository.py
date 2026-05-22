from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.models import (
    RatesSnapshotResponse,
    RatesSynthesisPanel,
)
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set; refusing to write into the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def repo() -> Repository:
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        yield Repository(conn, schema=settings.db_schema)


def test_rates_observations_are_idempotent_across_ingest_runs(repo: Repository):
    rows = [
        {
            "series_id": "DGS10",
            "obs_date": date(2026, 5, 18),
            "value": Decimal("4.47"),
            "realtime_start": date(2026, 5, 20),
            "realtime_end": date(2026, 5, 20),
            "release_date": None,
            "source_url": None,
        }
    ]

    assert (
        repo.upsert_rates_observation_rows(
            rows, seen_at=datetime(2026, 5, 20, 21, tzinfo=UTC), source="FRED"
        )
        == 1
    )
    assert (
        repo.upsert_rates_observation_rows(
            rows, seen_at=datetime(2026, 5, 21, 21, tzinfo=UTC), source="FRED"
        )
        == 1
    )

    fetched = repo.fetch_rates_series("DGS10")
    assert len(fetched) == 1
    assert fetched[0]["value"] == Decimal("4.47")
    assert fetched[0]["last_seen_at"] == datetime(2026, 5, 21, 21, tzinfo=UTC)


def test_rates_observations_normalize_current_fred_vintages(repo: Repository):
    first = {
        "series_id": "DGS10",
        "obs_date": date(2026, 5, 18),
        "value": Decimal("4.47"),
        "realtime_start": date(2026, 5, 20),
        "realtime_end": date(2026, 5, 20),
        "release_date": None,
        "source_url": None,
    }
    revised_current_vintage = {
        **first,
        "value": Decimal("4.48"),
        "realtime_start": date(2026, 5, 21),
        "realtime_end": date(2026, 5, 21),
    }

    repo.upsert_rates_observation_rows(
        [first], seen_at=datetime(2026, 5, 20, 21, tzinfo=UTC), source="FRED"
    )
    repo.upsert_rates_observation_rows(
        [revised_current_vintage],
        seen_at=datetime(2026, 5, 21, 21, tzinfo=UTC),
        source="FRED",
    )

    fetched = repo.fetch_rates_series("DGS10")
    assert len(fetched) == 1
    assert fetched[0]["value"] == Decimal("4.48")
    assert fetched[0]["realtime_start"] == date(2026, 5, 21)
    assert fetched[0]["first_seen_at"] == datetime(2026, 5, 20, 21, tzinfo=UTC)
    assert fetched[0]["last_seen_at"] == datetime(2026, 5, 21, 21, tzinfo=UTC)


def test_rates_snapshot_round_trips_json_native_payload(repo: Repository):
    snapshot = RatesSnapshotResponse(
        as_of=date(2026, 5, 20),
        computed_at=datetime(2026, 5, 20, 21, tzinfo=UTC),
        synthesis=RatesSynthesisPanel(
            duration_view="Live FRED snapshot",
            curve_view="Live curve snapshot",
        ),
    )
    repo.insert_rates_snapshot(
        snapshot_date=snapshot.as_of,
        computed_at=snapshot.computed_at,
        payload=snapshot.model_dump(mode="json"),
        source_freshness=[],
    )

    row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    restored = RatesSnapshotResponse.model_validate(row["payload"])
    assert restored.as_of == date(2026, 5, 20)
    assert restored.computed_at == datetime(2026, 5, 20, 21, tzinfo=UTC)
    assert restored.synthesis.duration_view == "Live FRED snapshot"


def test_fetch_latest_rates_snapshot_uses_newest_compute_time(repo: Repository):
    older_compute_later_market_date = RatesSnapshotResponse(
        as_of=date(2026, 5, 20),
        computed_at=datetime(2026, 5, 20, 21, tzinfo=UTC),
        synthesis=RatesSynthesisPanel(
            duration_view="old compute",
            curve_view="old compute",
        ),
    )
    newer_compute_earlier_market_date = RatesSnapshotResponse(
        as_of=date(2026, 5, 19),
        computed_at=datetime(2026, 5, 21, 21, tzinfo=UTC),
        synthesis=RatesSynthesisPanel(
            duration_view="new compute",
            curve_view="new compute",
        ),
    )
    for snapshot in (older_compute_later_market_date, newer_compute_earlier_market_date):
        repo.insert_rates_snapshot(
            snapshot_date=snapshot.as_of,
            computed_at=snapshot.computed_at,
            payload=snapshot.model_dump(mode="json"),
            source_freshness=[],
        )

    row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    restored = RatesSnapshotResponse.model_validate(row["payload"])
    assert restored.as_of == date(2026, 5, 19)
    assert restored.computed_at == datetime(2026, 5, 21, 21, tzinfo=UTC)
    assert restored.synthesis.duration_view == "new compute"
