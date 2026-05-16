from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
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


def test_external_api_request_roundtrip(repo: Repository):
    now = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)

    request_id = repo.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path_template="/api/stock/{ticker}/iv-rank",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=42,
        official_daily_count=10,
        official_daily_limit=1000,
    )
    repo.conn.commit()

    assert request_id > 0
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT provider, endpoint_key, ticker, params_json, status_code,
                   status_family, latency_ms, official_daily_count,
                   official_daily_limit
            FROM uw_scan.external_api_requests
            WHERE request_id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()

    assert row == (
        "uw",
        "iv_rank",
        "TSLA",
        {},
        200,
        "2xx",
        42,
        10,
        1000,
    )


def test_external_api_usage_summary_counts_latency_and_latest_official(
    repo: Repository,
):
    start = datetime(2026, 5, 14, 0, 0, tzinfo=UTC)
    end = datetime(2026, 5, 15, 0, 0, tzinfo=UTC)

    for offset, status_code, status_family, latency, official_count in [
        (1, 200, "2xx", 50, 10),
        (2, 404, "4xx", 50, 11),
        (3, 503, "5xx", 50, 12),
        (4, None, "transport_error", 50, None),
    ]:
        now = datetime(2026, 5, 14, offset, 0, tzinfo=UTC)
        repo.insert_external_api_request(
            provider="uw",
            endpoint_key="iv_rank",
            method="GET",
            path="/api/stock/TSLA/iv-rank",
            ticker="TSLA",
            params={"ticker": "TSLA"},
            status_code=status_code,
            status_family=status_family,
            started_at=now,
            finished_at=now,
            latency_ms=latency,
            official_daily_count=official_count,
            official_daily_limit=1000 if official_count is not None else None,
        )
    repo.insert_external_api_request(
        provider="massive",
        endpoint_key="daily_ohlc",
        method="GET",
        path="/v2/aggs/ticker/AAPL/range/1/day/2026-05-13/2026-05-14",
        ticker="AAPL",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=datetime(2026, 5, 14, 5, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 14, 5, 0, tzinfo=UTC),
        latency_ms=50,
    )
    repo.conn.commit()

    summary = repo.get_external_api_usage_summary(None, start, end)

    assert summary.total_requests == 5
    assert summary.http_2xx == 2
    assert summary.http_4xx == 1
    assert summary.http_5xx == 1
    assert summary.transport_errors == 1
    assert summary.latency_p95_ms == 50
    assert summary.uw_latest_daily_count == 12
    assert summary.uw_latest_daily_limit == 1000


def test_throughput_summary_counts_provider_and_queue_rates(repo: Repository):
    start = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    end = datetime(2026, 5, 14, 14, 15, tzinfo=UTC)

    for minute, status_code, status_family in [
        (1, 200, "2xx"),
        (2, 429, "4xx"),
        (3, 200, "2xx"),
    ]:
        at = start + timedelta(minutes=minute)
        repo.insert_external_api_request(
            provider="uw",
            endpoint_key="iv_rank",
            method="GET",
            path="/api/stock/TSLA/iv-rank",
            ticker="TSLA",
            params={},
            status_code=status_code,
            status_family=status_family,
            started_at=at,
            finished_at=at,
            latency_ms=25,
        )

    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.scan_runs
              (ticker, started_at, finished_at, status, notes)
            VALUES
              ('TSLA', %s, %s, 'ok', ''),
              ('NVDA', %s, %s, 'ok', '')
            """,
            (
                start,
                start + timedelta(seconds=60),
                start,
                start + timedelta(seconds=180),
            ),
        )
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.jobs
              (ticker, status, requested_at, started_at, finished_at)
            VALUES
              ('TSLA', 'done', %s, %s, %s),
              ('NVDA', 'failed', %s, %s, %s)
            """,
            (
                start,
                start,
                start + timedelta(minutes=2),
                start,
                start,
                start + timedelta(minutes=3),
            ),
        )
    repo.conn.commit()

    summary = repo.get_throughput_summary("uw", start, end)

    assert summary.requests_per_minute == 0.2
    assert summary.http_429 == 1
    assert summary.avg_scan_duration_seconds == 120.0
    assert summary.queue_drain_rate_per_minute == pytest.approx(2 / 15)


def test_external_api_usage_breakdowns_and_request_filters(repo: Repository):
    now = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    start = datetime(2026, 5, 14, 0, 0, tzinfo=UTC)
    end = datetime(2026, 5, 15, 0, 0, tzinfo=UTC)

    repo.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={"ticker": "TSLA"},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=20,
    )
    repo.insert_external_api_request(
        provider="uw",
        endpoint_key="greek_exposure",
        method="GET",
        path="/api/stock/TSLA/greek-exposure",
        ticker="TSLA",
        params={"ticker": "TSLA"},
        status_code=429,
        status_family="4xx",
        started_at=now,
        finished_at=now,
        latency_ms=30,
    )
    repo.conn.commit()

    endpoint_rows = repo.list_external_api_endpoint_usage("uw", start, end)
    ticker_rows = repo.list_external_api_ticker_usage("uw", start, end)
    request_rows = repo.list_external_api_requests(
        provider="uw",
        start=start,
        end=end,
        ticker="TSLA",
        status_family="4xx",
        limit=10,
    )

    assert {row.key: row.total_requests for row in endpoint_rows} == {
        "greek_exposure": 1,
        "iv_rank": 1,
    }
    assert [(row.key, row.total_requests, row.http_4xx) for row in ticker_rows] == [
        ("TSLA", 2, 1)
    ]
    assert len(request_rows) == 1
    assert request_rows[0].endpoint_key == "greek_exposure"
    assert request_rows[0].params == {"ticker": "TSLA"}


def test_get_throughput_summary_returns_none_for_non_uw_provider(repo: Repository):
    """B2: scan_runs and jobs are UW-only data sources. When the caller asks
    about a provider that isn't UW (e.g., 'massive'), don't return UW values
    labelled as that provider's. Return None for the UW-derived fields."""
    start = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    end = datetime(2026, 5, 14, 14, 15, tzinfo=UTC)
    massive_ts = start + timedelta(minutes=5)

    repo.insert_external_api_request(
        provider="massive",
        endpoint_key="agg_intraday",
        method="GET",
        path="/v2/aggs/ticker/AAPL/range/1/minute/2026-05-16/2026-05-16",
        ticker="AAPL",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=massive_ts,
        finished_at=massive_ts,
        latency_ms=42,
        job_name="spot_refresh",
    )

    # Seed UW scan_runs + jobs in the same window so a missing provider filter
    # would 'leak' UW values into the massive response.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.scan_runs
              (ticker, started_at, finished_at, status, notes)
            VALUES ('TSLA', %s, %s, 'ok', '')
            """,
            (start, start + timedelta(seconds=60)),
        )
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.jobs
              (ticker, status, requested_at, started_at, finished_at)
            VALUES ('TSLA', 'done', %s, %s, %s)
            """,
            (start, start, start + timedelta(minutes=2)),
        )
    repo.conn.commit()

    summary = repo.get_throughput_summary("massive", start, end)

    assert summary.avg_scan_duration_seconds is None, (
        "avg_scan_duration_seconds is derived from scan_runs (UW-only) — "
        "must not be returned under provider='massive'"
    )
    assert summary.queue_drain_rate_per_minute is None, (
        "queue_drain_rate_per_minute is derived from jobs (UW rescans only) — "
        "must not be returned under provider='massive'"
    )
    # The HTTP-request-derived fields are still reported for massive.
    assert summary.requests_per_minute > 0
    assert summary.http_429 == 0
