"""Integration tests for the new Repository methods on watchlist + watchlist_card
+ ohlc + intraday + pcr_history + jobs.

Each test gets a freshly migrated test DB (UW_SCAN_TEST_DB_NAME required) so
sequential runs don't leak state through the watchlist or jobs tables.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, datetime, timedelta, timezone
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
            "UW_SCAN_TEST_DB_NAME is not set; refusing to commit to the working DB. "
            "Create a dedicated test DB (e.g. `createdb option_wizard_test`) and "
            "export `UW_SCAN_TEST_DB_NAME=option_wizard_test` before running pytest.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    base = Settings.from_env()
    return base.model_copy(update={"db_name": test_db})


@pytest.fixture
def repo():
    """Repository against a FRESHLY migrated test DB.

    Repository methods commit internally, so writes from one test would persist
    across tests if we didn't reset. We DROP+CREATE the schema and re-apply
    migrations every test — slow but correct.
    """
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


def test_list_active_watchlist_excludes_soft_deleted(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    repo.soft_delete_watchlist_ticker("ZZTEST")
    actives = [t.ticker for t in repo.list_active_watchlist()]
    assert "ZZTEST" not in actives


def test_upsert_watchlist_card_idempotent(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    run1 = repo.insert_scan_run("ZZTEST", notes="t")
    repo.upsert_watchlist_card(
        ticker="ZZTEST",
        run_id=run1,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("100.00"),
        iv_atm=Decimal("0.25"),
    )
    run2 = repo.insert_scan_run("ZZTEST", notes="t")
    repo.upsert_watchlist_card(
        ticker="ZZTEST",
        run_id=run2,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("101.00"),
        iv_atm=Decimal("0.27"),
    )
    card = repo.get_watchlist_card("ZZTEST")
    assert card is not None
    assert card.run_id == run2
    assert card.spot == Decimal("101.0000")


def test_list_watchlist_cards_prefers_newer_intraday_quote(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    run_id = repo.insert_scan_run("ZZTEST", notes="t")
    repo.upsert_watchlist_card(
        ticker="ZZTEST",
        run_id=run_id,
        scanned_at=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("100.00"),
        spot_quoted_at=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot_source="uw_scan",
    )
    repo.upsert_intraday_quote(
        "ZZTEST",
        Decimal("101.25"),
        datetime(2026, 5, 13, 20, 15, tzinfo=timezone.utc),
    )

    cards = {card.ticker: card for card in repo.list_watchlist_cards()}

    assert cards["ZZTEST"].spot == Decimal("101.2500")
    assert cards["ZZTEST"].spot_source == "massive.com_intraday"


def test_upsert_daily_ohlc_dedupe_by_date(repo):
    repo.upsert_daily_ohlc(
        ticker="ZZTEST",
        date=date(2026, 5, 1),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=10_000,
        source="massive.com",
    )
    repo.upsert_daily_ohlc(
        ticker="ZZTEST",
        date=date(2026, 5, 1),
        open=Decimal("100"),
        high=Decimal("103"),
        low=Decimal("99"),
        close=Decimal("102"),
        volume=15_000,
        source="massive.com",
    )
    rows = repo.list_daily_ohlc("ZZTEST", limit=10)
    same_date = [r for r in rows if r.date == date(2026, 5, 1)]
    assert len(same_date) == 1
    assert same_date[0].close == Decimal("102.0000")


def test_enqueue_and_claim_job(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    job_id = repo.enqueue_rescan_job("ZZTEST")
    claimed = repo.claim_next_queued_job()
    assert claimed is not None
    assert str(claimed.id) == job_id
    assert claimed.status == "running"
    assert repo.claim_next_queued_job() is None


def test_enqueue_rescan_job_reuses_first_active_job(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")

    first_id = repo.enqueue_rescan_job("ZZTEST")
    second_id = repo.enqueue_rescan_job("ZZTEST")

    assert second_id == first_id
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM uw_scan.jobs
            WHERE ticker='ZZTEST' AND status IN ('queued', 'running')
            """
        )
        assert cur.fetchone()[0] == 1


def test_card_list_includes_active_queue_status(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    job_id = repo.enqueue_rescan_job("ZZTEST")

    cards = {card.ticker: card for card in repo.list_watchlist_cards()}

    queued = cards["ZZTEST"]
    assert str(queued.active_job_id) == job_id
    assert queued.active_job_status == "queued"
    assert queued.active_job_queue_position == 1


def test_queue_summary_counts_active_jobs(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    repo.add_watchlist_ticker(ticker="ZZALT", sector="ETF", notes="t")
    repo.enqueue_rescan_job("ZZTEST")
    repo.enqueue_rescan_job("ZZALT")
    repo.claim_next_queued_job()

    summary = repo.get_rescan_queue_summary()

    assert summary.total == 2
    assert summary.running == 1
    assert summary.queued == 1


def test_requeue_stale_running_jobs(repo):
    repo.add_watchlist_ticker(ticker="ZZTEST", sector="ETF", notes="t")
    job_id = repo.enqueue_rescan_job("ZZTEST")
    claimed = repo.claim_next_queued_job()
    assert claimed is not None

    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {repo._schema}.jobs
            SET started_at=NOW() - INTERVAL '31 minutes'
            WHERE id=%s
            """,
            (job_id,),
        )
    repo.conn.commit()

    assert repo.requeue_stale_running_jobs(timedelta(minutes=30)) == 1
    job = repo.get_job(job_id)
    assert job is not None
    assert job.status == "queued"
    assert job.started_at is None
