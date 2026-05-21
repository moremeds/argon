from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.sources.fred import FredObservation
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.rates_jobs import rates_fred_ingest_job

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
def migrated_settings() -> Settings:
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
    return settings


class _Provider:
    def __init__(self, *, api_key, record_request=None, job_name=None):
        self.api_key = api_key
        self.record_request = record_request
        self.job_name = job_name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_observations(self, series_id, *, start=None, end=None):
        values = {
            "DGS2": "4.13",
            "DGS5": "4.32",
            "DGS10": "4.67",
            "DGS30": "5.18",
            "DFII10": "2.13",
            "T10YIE": "2.48",
            "T5YIFR": "2.35",
            "EFFR": "3.63",
            "SOFR": "3.65",
        }
        if series_id not in values:
            return []
        return [
            FredObservation(
                series_id=series_id,
                obs_date=date(2026, 5, 20),
                value=Decimal(values[series_id]),
                realtime_start=date(2026, 5, 20),
                realtime_end=date(2026, 5, 20),
            )
        ]


def test_rates_job_requires_fred_api_key(migrated_settings: Settings):
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        rates_fred_ingest_job(
            dsn=migrated_settings.db_dsn(),
            fred_api_key=None,
            provider_factory=_Provider,
            computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        )


def test_rates_job_persists_observations_and_snapshot(migrated_settings: Settings):
    result = rates_fred_ingest_job(
        dsn=migrated_settings.db_dsn(),
        fred_api_key="fred-test",
        provider_factory=_Provider,
        computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
    )

    assert result.inserted_observations > 0
    assert result.failed_series == []
    assert result.snapshot_date == date(2026, 5, 20)

    with psycopg.connect(migrated_settings.db_dsn()) as conn:
        repo = Repository(conn, schema=migrated_settings.db_schema)
        row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    assert row["payload"]["as_of"] == "2026-05-20"
    assert row["payload"]["decomposition"]["nominal_10y"] == 4.67


def test_rates_job_keeps_raw_observations_when_snapshot_build_fails(
    migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def fail_snapshot(*_args, **_kwargs):
        raise ValueError("snapshot assembler failed")

    monkeypatch.setattr("uw_scan.worker.jobs.rates_jobs.build_rates_snapshot", fail_snapshot)

    with pytest.raises(ValueError, match="snapshot assembler failed"):
        rates_fred_ingest_job(
            dsn=migrated_settings.db_dsn(),
            fred_api_key="fred-test",
            provider_factory=_Provider,
            computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        )

    with psycopg.connect(migrated_settings.db_dsn()) as conn:
        repo = Repository(conn, schema=migrated_settings.db_schema)
        rows = repo.fetch_rates_series("DGS10", from_date=date(2026, 5, 1))

    assert len(rows) == 1
    assert rows[0]["value"] == Decimal("4.67")
