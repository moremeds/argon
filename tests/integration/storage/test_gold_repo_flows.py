"""Repository methods for cb_gold_reserves, cot_gold_weekly, uw_gold_options."""

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


def test_cb_reserves_round_trip(repo: Repository) -> None:
    repo.insert_cb_gold_reserves_monthly(
        country_iso3="CHN",
        obs_month=date(2026, 4, 1),
        reserves_t=Decimal("2235.0"),
        bucket="strategic_accumulator",
        is_reported=True,
        is_estimated=False,
        as_of=datetime.now(UTC),
        release_date=date(2026, 5, 8),
        source="WGC",
    )
    rows = repo.fetch_cb_gold_reserves_monthly(
        bucket="strategic_accumulator", from_month=date(2026, 1, 1)
    )
    assert any(r["country_iso3"] == "CHN" for r in rows)


def test_cot_round_trip_pins_release_date(repo: Repository) -> None:
    repo.insert_cot_gold_weekly(
        obs_date=date(2026, 5, 13),
        release_date=date(2026, 5, 16),
        mm_long=Decimal("210500"),
        mm_short=Decimal("85300"),
        mm_net=Decimal("125200"),
        comm_long=Decimal("180100"),
        comm_short=Decimal("295400"),
        comm_net=Decimal("-115300"),
        open_interest=Decimal("512000"),
        as_of=datetime.now(UTC),
        source_url=None,
    )
    rows = repo.fetch_cot_gold_weekly(
        from_release_date=date(2026, 5, 1),
        to_release_date=date(2026, 5, 20),
    )
    assert len(rows) == 1
    assert rows[0]["release_date"] == date(2026, 5, 16)
    assert rows[0]["mm_net"] == Decimal("125200")


def test_uw_gold_options_round_trip(repo: Repository) -> None:
    repo.insert_uw_gold_options_daily(
        ticker="GLD",
        obs_date=date(2026, 5, 16),
        atm_iv_30d=Decimal("0.21"),
        atm_iv_60d=Decimal("0.22"),
        put_25d_iv_30d=Decimal("0.27"),
        call_25d_iv_30d=Decimal("0.18"),
        skew_25d_30d=Decimal("0.09"),
        put_call_oi_ratio=None,
        dealer_gamma_est=None,
        as_of=datetime.now(UTC),
    )
    rows = repo.fetch_uw_gold_options_daily("GLD", from_date=date(2026, 5, 1))
    assert len(rows) == 1
    assert rows[0]["skew_25d_30d"] == Decimal("0.09")
