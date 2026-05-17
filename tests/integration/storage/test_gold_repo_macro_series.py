"""Repository methods for macro_series_daily and macro_series_monthly."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
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


def test_insert_and_fetch_macro_series_daily(repo: Repository) -> None:
    now = datetime.now(UTC)
    repo.insert_macro_series_daily(
        series_id="DFII10",
        obs_date=date(2026, 5, 14),
        value=Decimal("1.97"),
        as_of=now,
        release_date=None,
        source="FRED",
        source_url=None,
    )
    rows = repo.fetch_macro_series_daily("DFII10", from_date=date(2026, 5, 1))
    assert len(rows) == 1
    assert rows[0]["value"] == Decimal("1.97")


def test_insert_macro_series_daily_keeps_vintages(repo: Repository) -> None:
    """Re-pulling a series writes a new vintage row, doesn't overwrite."""
    repo.insert_macro_series_daily(
        "CPIAUCSL_TEST",
        date(2026, 4, 1),
        Decimal("310.1"),
        datetime(2026, 5, 14, 12, tzinfo=UTC),
        date(2026, 5, 14),
        "FRED",
        None,
    )
    repo.insert_macro_series_daily(
        "CPIAUCSL_TEST",
        date(2026, 4, 1),
        Decimal("310.3"),
        datetime(2026, 5, 28, 12, tzinfo=UTC),
        date(2026, 5, 28),
        "FRED",
        None,
    )
    rows = repo.fetch_macro_series_vintages("CPIAUCSL_TEST", obs_date=date(2026, 4, 1))
    assert len(rows) == 2
    assert rows[0]["value"] == Decimal("310.3")  # latest first
    assert rows[1]["value"] == Decimal("310.1")


def test_fetch_macro_series_latest_returns_most_recent_vintage(
    repo: Repository,
) -> None:
    repo.insert_macro_series_daily(
        "DFII10",
        date(2026, 5, 14),
        Decimal("1.95"),
        datetime(2026, 5, 14, tzinfo=UTC),
        None,
        "FRED",
        None,
    )
    repo.insert_macro_series_daily(
        "DFII10",
        date(2026, 5, 14),
        Decimal("1.97"),
        datetime(2026, 5, 15, tzinfo=UTC),
        None,
        "FRED",
        None,
    )
    rows = repo.fetch_macro_series_daily("DFII10")
    assert len(rows) == 1
    assert rows[0]["value"] == Decimal("1.97")


def test_macro_series_monthly_round_trip(repo: Repository) -> None:
    repo.insert_macro_series_monthly(
        series_id="CPIAUCSL",
        obs_month=date(2026, 4, 1),
        value=Decimal("310.1"),
        as_of=datetime(2026, 5, 14, tzinfo=UTC),
        release_date=date(2026, 5, 14),
        source="FRED",
        source_url=None,
    )
    rows = repo.fetch_macro_series_monthly("CPIAUCSL", from_month=date(2026, 1, 1))
    assert len(rows) == 1
    assert rows[0]["obs_month"] == date(2026, 4, 1)
