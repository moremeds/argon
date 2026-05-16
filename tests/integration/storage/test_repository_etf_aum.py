"""Tests for the ETF AUM cache (A1 from backend code review addendum).

The cache table lets pipeline.py skip the per-scan UW /etf_info round trip
when the AUM is fresh — AUM moves weekly at most, so a 7-day TTL gives
near-100% cache hit rate in steady state.
"""

from __future__ import annotations

import os
import subprocess
from datetime import timedelta
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


def test_get_recent_etf_aum_returns_none_when_no_row(repo: Repository) -> None:
    assert repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7)) is None


def test_get_recent_etf_aum_returns_value_when_fresh(repo: Repository) -> None:
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))
    cached = repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7))
    assert cached == Decimal("500000000000")


def test_get_recent_etf_aum_returns_none_when_stale(repo: Repository) -> None:
    """Manually backdate fetched_at past the TTL."""
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.etf_aum_cache SET fetched_at = NOW() - INTERVAL '8 days' WHERE ticker='SPY'"
        )
    repo.conn.commit()
    assert repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7)) is None


def test_upsert_etf_aum_updates_fetched_at_and_value(repo: Repository) -> None:
    """A second upsert must bump fetched_at AND overwrite aum."""
    repo.upsert_etf_aum("SPY", Decimal("100"))
    repo.upsert_etf_aum("SPY", Decimal("200"))
    cached = repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7))
    assert cached == Decimal("200")


def test_etf_aum_cache_normalizes_case(repo: Repository) -> None:
    """Codex review ISSUE-8: mixed-case input must hit the same logical row."""
    repo.upsert_etf_aum("spy", Decimal("123"))  # lowercase upsert
    cached = repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7))
    assert cached == Decimal("123")
