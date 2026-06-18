from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from uw_scan.benchmark.collector import build_pipeline_benchmark_inputs
from uw_scan.benchmark.pipeline import compute_component_scores
from uw_scan.config import Settings
from uw_scan.models import MarketAggregates


def test_build_pipeline_benchmark_inputs_from_warm_store(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    tickers = ["FRESHX", "NOGATEX", "STALEX", "DEADX", "NEVERX"]
    _replace_watchlist(repo, tickers)
    _insert_scanner_scan(repo, "FRESHX", now - timedelta(hours=2), seconds=60)
    _insert_finished_scan(repo, "NOGATEX", now - timedelta(hours=2), seconds=60)
    _insert_scanner_scan(repo, "STALEX", now - timedelta(hours=10), seconds=120)
    _insert_scanner_scan(repo, "DEADX", now - timedelta(hours=80), seconds=300)
    _insert_flow_refresh_scan(repo, "NEVERX", now - timedelta(hours=1))
    _insert_provider_request(repo, now, status_code=200, latency_ms=120)
    _insert_provider_request(repo, now, status_code=429, latency_ms=480)
    _insert_queue_job(repo, "NEVERX", now - timedelta(minutes=20))
    _insert_heartbeat(repo, "worker:uw:0", now - timedelta(seconds=15))
    _insert_heartbeat(repo, "worker:massive:0", now - timedelta(seconds=20))
    _insert_ws_tick(repo, now - timedelta(seconds=30))
    _insert_watchlist_card(repo, "FRESHX", now - timedelta(hours=2))
    repo.conn.commit()

    inputs = build_pipeline_benchmark_inputs(
        repo,
        Settings(api_key="test", uw_worker_count=1, massive_worker_count=1),
        now_utc=now,
    )
    scores, reasons = compute_component_scores(inputs)

    assert inputs.watchlist_size == 5
    assert inputs.scanner_fresh_count == 1
    assert inputs.scanner_stale_count == 1
    assert inputs.scanner_dead_count == 1
    assert inputs.scanner_never_scanned_count == 2
    assert inputs.uw_latency_p95_ms is not None
    assert inputs.uw_http_429 == 1
    assert inputs.queue_depth == 1
    assert inputs.oldest_queue_age_seconds == 1200
    assert inputs.scan_duration_avg_seconds is not None
    assert inputs.scan_duration_p95_seconds is not None
    assert inputs.record_health_ok is False
    assert inputs.uw_worker_online_count == 1
    assert inputs.massive_worker_online_count == 1
    assert scores.coverage < 60
    assert any(reason.component == "coverage" for reason in reasons)


def test_pipeline_inputs_do_not_count_noop_full_scan_windows_as_missed(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    now = datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
    _insert_finished_scan(
        repo,
        "TSLA",
        datetime(2026, 5, 13, 13, 35, tzinfo=UTC),
        seconds=60,
    )
    repo.conn.commit()

    inputs = build_pipeline_benchmark_inputs(
        repo,
        Settings(api_key="test"),
        now_utc=now,
    )

    assert inputs.expected_full_scan_miss_count == 0


def _replace_watchlist(repo, tickers: list[str]) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.watchlist SET removed_at = %s",
            (datetime.now(UTC),),
        )
    for index, ticker in enumerate(tickers):
        repo.add_watchlist_ticker(
            ticker=ticker,
            sector="Benchmark",
            sort_rank=index,
        )


def _insert_finished_scan(
    repo, ticker: str, finished_at: datetime, *, seconds: int
) -> int:
    started_at = finished_at - timedelta(seconds=seconds)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.scan_runs
              (ticker, started_at, finished_at, status, notes)
            VALUES (%s, %s, %s, 'ok', 'benchmark-test')
            RETURNING run_id
            """,
            (ticker, started_at, finished_at),
        )
        row = cur.fetchone()
    run_id = int(row[0])
    # A real full/scanner scan persists aggregates; the duration metric and
    # latest_run_id both key on that to count it as a canonical run.
    repo.set_aggregates(run_id, MarketAggregates(call_oi_total=1000))
    return run_id


def _insert_flow_refresh_scan(repo, ticker: str, finished_at: datetime) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.scan_runs
              (ticker, started_at, finished_at, status, notes)
            VALUES (%s, %s, %s, 'ok', 'flow_data_refresh')
            """,
            (ticker, finished_at - timedelta(seconds=30), finished_at),
        )


def _insert_scanner_scan(
    repo, ticker: str, finished_at: datetime, *, seconds: int
) -> None:
    run_id = _insert_finished_scan(repo, ticker, finished_at, seconds=seconds)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.signal_gates
              (run_id, ticker, earnings, liquidity, regime)
            VALUES (%s, %s, 'pass', 'pass', 'pass')
            """,
            (run_id, ticker),
        )


def _insert_provider_request(
    repo, now: datetime, *, status_code: int, latency_ms: int
) -> None:
    family = "4xx" if 400 <= status_code < 500 else "2xx"
    repo.insert_external_api_request(
        provider="uw",
        endpoint_key="benchmark-test",
        method="GET",
        path="/api/benchmark-test",
        ticker="FRESHX",
        params={},
        status_code=status_code,
        status_family=family,
        started_at=now - timedelta(minutes=1),
        finished_at=now - timedelta(minutes=1, milliseconds=-latency_ms),
        latency_ms=latency_ms,
    )


def _insert_queue_job(repo, ticker: str, requested_at: datetime) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.jobs (ticker, status, requested_at)
            VALUES (%s, 'queued', %s)
            """,
            (ticker, requested_at),
        )


def _insert_heartbeat(repo, name: str, beat_at: datetime) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.worker_heartbeat (job_name, last_beat_at)
            VALUES (%s, %s)
            ON CONFLICT (job_name) DO UPDATE SET last_beat_at = EXCLUDED.last_beat_at
            """,
            (name, beat_at),
        )


def _insert_ws_tick(repo, tick_at: datetime) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {repo._schema}.ws_consumer_state
            SET last_tick_at = %s, last_flush_at = %s, updated_at = %s
            WHERE id = 1
            """,
            (tick_at, tick_at, tick_at),
        )


def _insert_watchlist_card(repo, ticker: str, scanned_at: datetime) -> None:
    run_id = _insert_finished_scan(repo, ticker, scanned_at, seconds=60)
    repo.upsert_watchlist_card(
        ticker=ticker,
        run_id=run_id,
        scanned_at=scanned_at,
        spot=Decimal("100.00"),
    )
