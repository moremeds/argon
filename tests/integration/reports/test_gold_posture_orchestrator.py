"""Integration test for the gold_posture orchestrator."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
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


def _seed_minimum(repo: Repository, today: date) -> None:
    """Seed enough data for the orchestrator to produce a non-empty posture."""
    base = today - timedelta(days=300)
    for i in range(301):
        d = base + timedelta(days=i)
        repo.insert_macro_series_daily(
            "GLD_CLOSE",
            d,
            Decimal(str(1800 + i * 0.5)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "MASSIVE",
            None,
        )
        repo.insert_macro_series_daily(
            "DFII10",
            d,
            Decimal(str(2.0 - i * 0.005)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "FRED",
            None,
        )
    repo.insert_macro_series_monthly(
        "CPIAUCSL",
        date(today.year, today.month, 1),
        Decimal("315.0"),
        datetime.now(UTC),
        date(today.year, today.month, 14),
        "FRED",
        None,
    )
    repo.insert_macro_series_daily(
        "T5YIFR",
        today,
        Decimal("2.31"),
        datetime.now(UTC),
        None,
        "FRED",
        None,
    )


def test_orchestrator_writes_posture_row(repo: Repository) -> None:
    today = date(2026, 5, 16)
    _seed_minimum(repo, today)
    compute_and_persist_gold_posture(
        repo,
        as_of=today,
        computed_at=datetime(2026, 5, 17, tzinfo=UTC),
    )
    row = repo.fetch_gold_posture_for_obs_date(today)
    assert row is not None
    assert row["obs_date"] == today
    assert row["gauge_state"] in {"operative", "partial", "suspended"}
    assert row["inputs_jsonb"] is not None
    assert "DFII10" in row["inputs_jsonb"]
    # GOLD COMPASS extensions populated
    assert row["valuation_posture_chip"] in {
        "FAVORABLE",
        "NEUTRAL",
        "STRETCHED",
        "SUSPENDED",
        "DEGRADED",
    }


def test_orchestrator_idempotent_same_inputs(repo: Repository) -> None:
    """Running twice with same (obs_date, computed_at) is a no-op."""
    today = date(2026, 5, 16)
    _seed_minimum(repo, today)
    computed_at = datetime(2026, 5, 17, tzinfo=UTC)
    compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
    compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.gold_posture_daily WHERE obs_date = %s",
            (today,),
        )
        assert cur.fetchone()[0] == 1
