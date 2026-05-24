"""GET /api/health — ok/unhealthy/reason states."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from uw_scan.api.routers.health import _record_health_cache_clear_for_tests, health
from uw_scan.config import Settings


@pytest.fixture(autouse=True)
def clear_record_health_cache():
    _record_health_cache_clear_for_tests()
    yield
    _record_health_cache_clear_for_tests()


def test_health_ok_when_recent_scan(client, seeded_db_with_cards):
    seeded_db_with_cards.upsert_heartbeat("worker")

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "up"
    assert body["scheduler_lag_seconds"] is not None
    assert body["last_full_scan_at"] is not None
    assert body["worker_lag_seconds"] is not None


def test_health_uses_dedicated_worker_heartbeat(client, seeded_db_empty_cards):
    seeded_db_empty_cards.upsert_heartbeat("worker")

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["worker_lag_seconds"] is not None
    assert body["worker_lag_seconds"] < 5
    assert body["scheduler_heartbeat_lag_seconds"] is not None
    assert body["scheduler_heartbeat_lag_seconds"] < 5
    assert body["scheduler_heartbeat_name"] == "worker"


def test_health_reports_rescan_heartbeat_separately(client, seeded_db_empty_cards):
    seeded_db_empty_cards.upsert_heartbeat("trade_insights_ai_tick")
    seeded_db_empty_cards.upsert_heartbeat("rescan_tick")

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["scheduler_heartbeat_lag_seconds"] is not None
    assert body["scheduler_heartbeat_name"] in {"trade_insights_ai_tick", "rescan_tick"}
    assert body["rescan_heartbeat_lag_seconds"] is not None
    assert body["rescan_heartbeat_lag_seconds"] < 5


def test_health_reports_spot_refresh_and_quote_freshness(client, seeded_db_empty_cards):
    seeded_db_empty_cards.upsert_heartbeat("spot_refresh")
    seeded_db_empty_cards.upsert_intraday_quote(
        "AAPL",
        Decimal("298.40"),
        datetime.now(UTC),
    )

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["spot_refresh_heartbeat_lag_seconds"] is not None
    assert body["spot_refresh_heartbeat_lag_seconds"] < 5
    assert body["spot_quote_lag_seconds"] is not None
    assert body["spot_quote_lag_seconds"] < 5
    assert body["latest_spot_quote_at"] is not None
    assert body["latest_spot_quote_fetched_at"] is not None


def test_health_reports_expected_provider_workers(seeded_db_with_cards):
    seeded_db_with_cards.upsert_heartbeat("worker:uw:0")
    seeded_db_with_cards.upsert_heartbeat("worker:massive:1")

    response = health(
        repo=seeded_db_with_cards,
        settings=Settings(
            api_key="test",
            uw_worker_count=2,
            massive_worker_count=2,
        ),
    )

    workers = {worker.heartbeat_name: worker for worker in response.workers}
    assert set(workers) == {
        "worker:uw:0",
        "worker:uw:1",
        "worker:massive:0",
        "worker:massive:1",
    }
    assert workers["worker:uw:0"].label == "UW 1"
    assert workers["worker:uw:0"].lag_seconds is not None
    assert workers["worker:uw:1"].lag_seconds is None
    assert workers["worker:massive:1"].label == "Massive 2"


def test_repository_get_heartbeats_returns_mapping_for_present_names(
    seeded_db_empty_cards,
):
    seeded_db_empty_cards.upsert_heartbeat("worker:uw:0")
    seeded_db_empty_cards.upsert_heartbeat("worker:massive:1")

    heartbeats = seeded_db_empty_cards.get_heartbeats(
        ["worker:uw:0", "worker:uw:1", "worker:massive:1"]
    )

    assert set(heartbeats) == {"worker:uw:0", "worker:massive:1"}
    assert heartbeats["worker:uw:0"].tzinfo is not None
    assert seeded_db_empty_cards.get_heartbeats([]) == {}


def test_health_includes_uw_provider_usage_stats(client, seeded_db_empty_cards):
    now = datetime.now(UTC)
    seeded_db_empty_cards.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=25,
        official_daily_count=33,
        official_daily_limit=1000,
    )
    seeded_db_empty_cards.insert_external_api_request(
        provider="massive",
        endpoint_key="daily_ohlc",
        method="GET",
        path="/v2/aggs/ticker/AAPL/range/1/day/2026-05-13/2026-05-14",
        ticker="AAPL",
        params={},
        status_code=503,
        status_family="5xx",
        started_at=now,
        finished_at=now,
        latency_ms=25,
    )
    seeded_db_empty_cards.conn.commit()

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["source"] == "UnusualWhales"
    assert body["http_2xx"] == 1
    assert body["http_4xx"] == 0
    assert body["http_5xx"] == 0
    assert body["latency_p95_ms"] == 25
    assert body["uw_today"] == 33


def test_health_includes_throughput_metrics(client, seeded_db_with_cards):
    now = datetime.now(UTC)
    seeded_db_with_cards.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=429,
        status_family="4xx",
        started_at=now,
        finished_at=now,
        latency_ms=25,
    )
    with seeded_db_with_cards.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {seeded_db_with_cards._schema}.jobs
              (ticker, status, requested_at, started_at, finished_at)
            VALUES ('TSLA', 'done', %s, %s, %s)
            """,
            (now, now, now),
        )
    seeded_db_with_cards.conn.commit()

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["throughput_window_minutes"] > 0
    assert body["requests_per_minute"] > 0
    assert body["http_429"] == 1
    assert body["avg_scan_duration_seconds"] is not None
    assert body["queue_drain_rate_per_minute"] > 0


def test_health_includes_massive_provider_usage_stats_when_source_is_massive(
    client, seeded_db_empty_cards
):
    now = datetime.now(UTC)
    seeded_db_empty_cards.insert_external_api_request(
        provider="uw",
        endpoint_key="iv_rank",
        method="GET",
        path="/api/stock/TSLA/iv-rank",
        ticker="TSLA",
        params={},
        status_code=200,
        status_family="2xx",
        started_at=now,
        finished_at=now,
        latency_ms=25,
        official_daily_count=33,
        official_daily_limit=1000,
    )
    seeded_db_empty_cards.insert_external_api_request(
        provider="massive",
        endpoint_key="daily_ohlc",
        method="GET",
        path="/v2/aggs/ticker/AAPL/range/1/day/2026-05-13/2026-05-14",
        ticker="AAPL",
        params={},
        status_code=503,
        status_family="5xx",
        started_at=now,
        finished_at=now,
        latency_ms=55,
    )
    seeded_db_empty_cards.conn.commit()

    r = client.get("/api/health?source=massive")

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "Massive.com"
    assert body["http_2xx"] == 0
    assert body["http_4xx"] == 0
    assert body["http_5xx"] == 1
    assert body["latency_p95_ms"] == 55
    assert body["uw_today"] is None


def test_health_record_check_alerts_on_low_recent_ticker_coverage(
    client, seeded_db_with_cards
):
    r = client.get(
        "/api/health?record_window_hours=8&record_min_coverage=0.9"
        "&record_tables=watchlist_card"
    )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["record_health_ok"] is False
    assert "record coverage below expected" in body["reason"]
    card_check = next(
        check for check in body["record_health"] if check["table"] == "watchlist_card"
    )
    assert card_check["actual_tickers"] == 1
    assert (
        card_check["expected_tickers"] == seeded_db_with_cards.count_active_watchlist()
    )
    assert card_check["ok"] is False


def test_health_record_check_passes_when_selected_table_covers_watchlist(
    client, seeded_db_empty_cards
):
    repo = seeded_db_empty_cards
    now = datetime.now(UTC)
    for row in repo.list_watchlist_cards():
        run_id = repo.insert_scan_run(ticker=row.ticker)
        repo.finish_scan_run(run_id, status="ok")
        repo.upsert_watchlist_card(
            ticker=row.ticker,
            run_id=run_id,
            scanned_at=now,
            spot=Decimal("100.00"),
        )

    r = client.get("/api/health?record_window_hours=8&record_tables=watchlist_card")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["record_health_ok"] is True
    assert body["record_health"][0]["table"] == "watchlist_card"
    assert body["record_health"][0]["actual_tickers"] == repo.count_active_watchlist()


def test_health_record_check_cache_is_bounded_and_clearable(
    client, seeded_db_empty_cards
):
    repo = seeded_db_empty_cards
    now = datetime.now(UTC)
    for row in repo.list_watchlist_cards():
        run_id = repo.insert_scan_run(ticker=row.ticker)
        repo.finish_scan_run(run_id, status="ok")
        repo.upsert_watchlist_card(
            ticker=row.ticker,
            run_id=run_id,
            scanned_at=now,
            spot=Decimal("100.00"),
        )

    url = "/api/health?record_window_hours=8&record_tables=watchlist_card"
    first = client.get(url)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["record_health_ok"] is True

    stale = now - timedelta(days=2)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {repo._schema}.watchlist_card
               SET scanned_at = %s,
                   updated_at = %s
            """,
            (stale, stale),
        )
        cur.execute(
            f"""
            UPDATE {repo._schema}.scan_runs
               SET finished_at = %s
            """,
            (stale,),
        )
    repo.conn.commit()

    second = client.get(url)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["record_health_ok"] is True
    assert second_body["record_health"] == first_body["record_health"]

    _record_health_cache_clear_for_tests()
    third = client.get(url)
    assert third.status_code == 200
    third_body = third.json()
    assert third_body["record_health_ok"] is False
    assert third_body["record_health"] != first_body["record_health"]


def test_health_record_check_discovers_new_ticker_timestamp_tables(
    client, seeded_db_empty_cards
):
    repo = seeded_db_empty_cards
    now = datetime.now(UTC)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE {repo._schema}.synthetic_endpoint_snapshots (
                ticker text NOT NULL,
                inserted_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.executemany(
            f"""
            INSERT INTO {repo._schema}.synthetic_endpoint_snapshots
                (ticker, inserted_at)
            VALUES (%s, %s)
            """,
            [(row.ticker, now) for row in repo.list_watchlist_cards()],
        )
    repo.conn.commit()

    r = client.get(
        "/api/health?record_window_hours=8&record_tables=synthetic_endpoint_snapshots"
    )

    assert r.status_code == 200
    body = r.json()
    synthetic = body["record_health"][0]
    assert synthetic["table"] == "synthetic_endpoint_snapshots"
    assert synthetic["ok"] is True
    assert synthetic["actual_tickers"] == repo.count_active_watchlist()


def test_health_daily_window_passes_nightly_table_aged_under_26h(
    client, seeded_db_empty_cards
):
    """`iv_rank_history` is in _RECORD_HEALTH_DAILY_TABLES → 26h window
    applies. Rows from 20h ago should count as fresh; 8h would fail."""
    repo = seeded_db_empty_cards
    aged = datetime.now(UTC) - timedelta(hours=20)
    with repo.conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {repo._schema}.iv_rank_history
                (ticker, market_date, close, volatility, iv_rank_1y,
                 updated_at_src, inserted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    row.ticker,
                    aged.date(),
                    Decimal("100"),
                    Decimal("0.3"),
                    Decimal("50"),
                    aged,
                    aged,
                )
                for row in repo.list_watchlist_cards()
            ],
        )
    repo.conn.commit()

    r = client.get("/api/health?record_window_hours=8&record_tables=iv_rank_history")

    assert r.status_code == 200
    body = r.json()
    row = body["record_health"][0]
    assert row["table"] == "iv_rank_history"
    assert row["ok"] is True, f"expected daily window pass at 20h, got {row}"
    assert row["actual_tickers"] == repo.count_active_watchlist()


def test_health_excluded_tables_omitted_from_record_health(
    client, seeded_db_empty_cards
):
    """Cockpit-only + sparse tables should be filtered out of discovery so
    they cannot trigger a false coverage alert."""
    r = client.get("/api/health?record_window_hours=8")
    body = r.json()
    surfaced = {row["table"] for row in body["record_health"]}
    excluded = {
        "charm_signals",
        "vanna_signals",
        "matrix_state_snapshots",
        "vrp_30d_settlements",
        "signal_context_flags",
    }
    leaked = surfaced & excluded
    assert not leaked, f"excluded tables leaked into record_health: {leaked}"


def test_health_unhealthy_when_no_scans(client, seeded_db_empty_cards):
    r = client.get("/api/health")
    body = r.json()
    assert body["ok"] is False
    assert "no successful full scan" in (body.get("reason") or "")


def test_health_unhealthy_when_lag_exceeds_2x_interval(
    client, seeded_db_with_stale_run
):
    r = client.get("/api/health")
    body = r.json()
    assert body["ok"] is False
    assert "exceeds" in (body.get("reason") or "")
