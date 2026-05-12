"""Shared fixtures for tests/integration/{api,worker,...}.

Requires UW_SCAN_TEST_DB_NAME to point at a dedicated test DB. Fixtures
refuse to run otherwise — never touches the developer's working DB.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[2]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to point integration tests "
            "at the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _reset_and_migrate(settings: Settings) -> None:
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


@pytest.fixture
def seeded_db_empty_cards() -> Repository:
    """Freshly-migrated test DB + 54-ticker watchlist seed; zero card rows."""
    settings = _test_settings()
    _reset_and_migrate(settings)
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


@pytest.fixture
def seeded_db_with_cards(seeded_db_empty_cards) -> Repository:
    """seeded_db_empty_cards + one scan_run + one watchlist_card for TSLA.

    finished_at = now (fresh) so /api/health reports ok=True.
    """
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run(ticker="TSLA")
    repo.finish_scan_run(run_id, status="ok")
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=run_id,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("445.12"),
        iv_atm=Decimal("0.691"),
        iv_rank=Decimal("39.0"),
    )
    return repo


@pytest.fixture
def latest_tsla_run_id(seeded_db_with_cards) -> int:
    return seeded_db_with_cards.latest_run_id("TSLA")


@pytest.fixture
def seeded_db_with_stale_run(seeded_db_empty_cards) -> Repository:
    """A scan_runs row with finished_at = now - 6 hours.

    With the default hourly full_scan_cron, threshold = 2× ~1h = ~2h; 6h lag
    should report unhealthy in /api/health.
    """
    repo = seeded_db_empty_cards
    stale = datetime.now(timezone.utc) - timedelta(hours=6)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.scan_runs (ticker, started_at, finished_at, status)
            VALUES (%s, %s, %s, 'ok')
            """,
            ("TSLA", stale, stale),
        )
    repo.conn.commit()
    return repo


@pytest.fixture
def seeded_db_with_ohlc(seeded_db_empty_cards) -> Repository:
    repo = seeded_db_empty_cards
    today = datetime.now(timezone.utc).date()
    for i in range(30):
        repo.upsert_daily_ohlc(
            ticker="AAPL",
            date=today - timedelta(days=29 - i),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal(str(100 + i)),
            volume=10_000_000,
            source="massive.com",
        )
    return repo
