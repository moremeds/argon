"""Worker job — gold_posture_compute_job (Task 25)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.gold_jobs import gold_posture_compute_job


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set.", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def fresh_db(seeded_db_empty_cards) -> Settings:
    # seeded_db_empty_cards drives the session migrate + per-test baseline
    # restore. The job under test opens its own connection from settings.db_dsn().
    _ = seeded_db_empty_cards
    return _test_settings()


def test_gold_posture_compute_writes_row(fresh_db: Settings) -> None:
    target = date(2026, 5, 16)
    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        base = target - timedelta(days=300)
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
        conn.commit()

    gold_posture_compute_job(dsn=fresh_db.db_dsn(), as_of=target)

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        row = repo.fetch_gold_posture_latest()
    assert row is not None
    assert row["obs_date"] == target
    assert row["gauge_state"] in {"operative", "partial", "suspended"}


def test_gold_posture_compute_defaults_to_latest_gld_close_date(
    fresh_db: Settings,
) -> None:
    latest_market_date = date(2026, 5, 15)
    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        base = latest_market_date - timedelta(days=300)
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
        conn.commit()

    gold_posture_compute_job(dsn=fresh_db.db_dsn())

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        row = repo.fetch_gold_posture_latest()
    assert row is not None
    assert row["obs_date"] == latest_market_date


def test_gold_posture_compute_uses_uw_gld_flows(fresh_db: Settings) -> None:
    target = date(2026, 5, 16)
    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        base = target - timedelta(days=300)
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
        repo.insert_etf_flows_daily(
            ticker="GLD",
            obs_date=date(2026, 5, 15),
            share_change=Decimal("-900000"),
            premium_change_usd=Decimal("-375300000"),
            close=Decimal("417.29"),
            volume=Decimal("8801181"),
            # A knowable instant, not the wall clock. This job replays a PAST date, and
            # gold reads are bounded on the RETRIEVAL clock as well as the observation
            # period -- so a row stamped now() was fetched after the moment the posture
            # answers for, and is correctly invisible to it. Stamping retrieval at
            # datetime.now() made this assertion pass on lookahead.
            as_of=datetime.combine(date(2026, 5, 15), datetime.min.time(), tzinfo=UTC),
            source="UW",
        )
        conn.commit()

    gold_posture_compute_job(dsn=fresh_db.db_dsn(), as_of=target)

    with psycopg.connect(fresh_db.db_dsn()) as conn:
        repo = Repository(conn, schema=fresh_db.db_schema)
        row = repo.fetch_gold_posture_latest()
    assert row is not None
    assert row["gld_holdings_t"] is None
    assert row["gld_30d_net_flow_t"].quantize(Decimal("0.001")) == Decimal("-2.606")
