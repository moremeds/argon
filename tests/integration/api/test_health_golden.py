"""Golden of ``GET /api/health`` (I-36 proof).

Written BEFORE the handler's assembly moved out of ``routers/health.py``: the
endpoint is called with each query-param variant it supports on an empty DB
and on a DB where every block is populated (heartbeats, worker pools, AI
provider pools + queue depth, last full scan, spot quotes, provider usage and
throughput, record-health snapshot, freshness + autoheal breaker, gap healer,
WS consumer, job-failure streaks), then again after the seed is moved into each
degraded branch (stale record snapshot, missed full scans) and at an
out-of-session instant. Status + body must equal the committed
``golden/health.json``.

The clock is frozen, not normalised out of the bodies. ``/api/health`` reads
the wall clock twice: ``datetime.now(timezone.utc)`` in the handler and
``provider_day_bounds()`` (``storage/_helpers.py``). The freeze patches the
``datetime``/``date`` names of every loaded module on that path, by name, so
it still reaches the code after it moves between modules. Every seeded
timestamp is explicit and relative to the frozen instant; no read on this
path filters on SQL ``now()``/``CURRENT_DATE`` (``consecutive_frozen_counts``'s
``COALESCE(%s, CURRENT_DATE)`` always receives the newest ``run_date``), so
no block needs a DB-clock-relative case.

``APP_VERSION`` is pinned the same way the clock is: the real value is the
repo ``VERSION`` file, which every release bumps.

Settings are pinned explicitly (``Settings.from_env`` reads the developer's
``.env``), so worker counts, kill switches and thresholds are the same on
every machine.

Floats are rounded to 9 significant digits before comparing.

Regenerate (only for an intentional response change):
``HEALTH_GOLDEN_WRITE=1 uv run pytest tests/integration/api/test_health_golden.py``
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests.integration.storage.test_trade_insights_ai_repository import (
    _seed_snapshot,
)
from uw_scan.api.deps import get_settings
from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository

GOLDEN = Path(__file__).resolve().parent / "golden" / "health.json"

UTC = _dt.timezone.utc
# Fri 2026-05-15 11:00 ET: a regular session, inside the full-scan crons.
NOW_RTH = _dt.datetime(2026, 5, 15, 15, 0, 0, tzinfo=UTC)
# Sat 2026-05-16 11:00 ET: market closed, no full-scan cron due.
NOW_CLOSED = _dt.datetime(2026, 5, 16, 15, 0, 0, tzinfo=UTC)

_CLOCK = {"now": NOW_RTH}

_CLOCK_PREFIXES = (
    "uw_scan.api.routers.health",
    "uw_scan.reports.health_assembly",
    "uw_scan.storage._helpers",
    "uw_scan.storage.repository",
    "uw_scan.worker.market_session",
    "uw_scan.worker.schedule_expectations",
)

PINNED_VERSION = "0.0.0-golden"

PARAM_VARIANTS: list[tuple[str, dict]] = [
    ("default", {}),
    ("source=massive", {"source": "massive"}),
    ("source=uw", {"source": "uw"}),
    ("window=8", {"record_window_hours": 8}),
    (
        "window=8,tables=watchlist_card",
        {"record_window_hours": 8, "record_tables": "watchlist_card"},
    ),
    (
        "window=8,tables=watchlist_card,bogus_table",
        {"record_window_hours": 8, "record_tables": "watchlist_card,bogus_table"},
    ),
    (
        "window=8,tables=blank",
        {"record_window_hours": 8, "record_tables": " , "},
    ),
    ("window=8,min_coverage=0", {"record_window_hours": 8, "record_min_coverage": 0}),
    ("tables_without_window", {"record_tables": "flow_alerts"}),
]


class _FrozenDateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        now = _CLOCK["now"]
        return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):  # type: ignore[override]
        return _CLOCK["now"].replace(tzinfo=None)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):  # type: ignore[override]
        return _CLOCK["now"].date()


@pytest.fixture
def frozen_client(monkeypatch, client):
    # timestamptz values render in the DB session's timezone; pin it so the
    # golden is the same on a UTC CI runner and on a local +08:00 Postgres.
    monkeypatch.setenv("PGTZ", "UTC")
    _CLOCK["now"] = NOW_RTH
    # `client` first: create_app() has imported every router module by now.
    for name in [m for m in list(sys.modules) if m.startswith(_CLOCK_PREFIXES)]:
        mod = sys.modules[name]
        for attr in ("datetime", "_datetime", "date", "_date"):
            val = getattr(mod, attr, None)
            if val is _dt.datetime:
                monkeypatch.setattr(mod, attr, _FrozenDateTime)
            elif val is _dt.date:
                monkeypatch.setattr(mod, attr, _FrozenDate)
        if hasattr(mod, "APP_VERSION"):
            monkeypatch.setattr(mod, "APP_VERSION", PINNED_VERSION)

    base = client.app.dependency_overrides[get_settings]()
    pinned = base.model_copy(
        update={
            "db_schema": "uw_scan",
            "rth_tz": "America/New_York",
            "full_scan_crons": [
                "0 4 * * 0-4",
                "30 9 * * 0-4",
                "0,30 10-15 * * 0-4",
                "0 16 * * 0-4",
                "30 16 * * 0-4",
            ],
            "health_full_scan_missed_grace_hours": 1.0,
            "uw_worker_count": 2,
            "massive_worker_count": 1,
            "ai_worker_count": 1,
            "massive_ws_heartbeat_stale_after_seconds": 120.0,
            "trade_insights_ai_enabled": True,
            "trade_insights_ai_claude_enabled": False,
            "trade_insights_ai_deepseek_enabled": True,
            "trade_insights_ai_codex_worker_count": 2,
            "trade_insights_ai_claude_worker_count": 2,
            "trade_insights_ai_deepseek_worker_count": 1,
            "trade_insights_ai_poll_seconds": 3,
            "data_freshness_autoheal_enabled": True,
            "data_freshness_autoheal_circuit_breaker_nights": 3,
        }
    )
    client.app.dependency_overrides[get_settings] = lambda: pinned
    yield client
    _CLOCK["now"] = NOW_RTH


def _round_floats(value):
    if isinstance(value, float):
        return float(f"{value:.9g}")
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def _sweep(client) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for label, params in PARAM_VARIANTS:
        r = client.get("/api/health", params=params)
        try:
            body = r.json()
        except ValueError:
            body = r.text
        out[label] = {"status": r.status_code, "body": _round_floats(body)}
    return out


def _ago(**kw) -> _dt.datetime:
    return NOW_RTH - timedelta(**kw)


def _seed_heartbeats(cur) -> None:
    # Distinct instants: get_latest_heartbeat orders by last_beat_at only.
    beats = [
        ("worker", _ago(seconds=30)),
        ("rescan_tick", _ago(seconds=90)),
        ("worker:uw:0", _ago(seconds=10)),
        ("worker:massive:0", _ago(seconds=600)),
        ("worker:ai:0", _ago(seconds=45)),
        ("trade_insights_ai_tick_codex", _ago(seconds=20)),
        ("trade_insights_ai_tick", _ago(seconds=500)),
        ("trade_insights_ai_tick_deepseek", _ago(seconds=200)),
    ]
    for name, at in beats:
        cur.execute(
            "INSERT INTO uw_scan.worker_heartbeat (job_name, last_beat_at) "
            "VALUES (%s, %s)",
            (name, at),
        )


def _seed_quotes(cur) -> None:
    for ticker, price, quoted, fetched, source in [
        ("AAPL", Decimal("190.10"), _ago(minutes=15), _ago(minutes=14), "xenon_ws"),
        ("MSFT", Decimal("410.50"), _ago(minutes=5), _ago(minutes=4), "xenon_ws"),
    ]:
        cur.execute(
            "INSERT INTO uw_scan.intraday_quote "
            "(ticker, price, quoted_at, fetched_at, source) "
            "VALUES (%s, %s, %s, %s, %s)",
            (ticker, price, quoted, fetched, source),
        )


def _seed_scans_and_jobs(cur) -> None:
    for ticker, started, finished, status, notes in [
        # The full scan /api/health reports (notes NULL).
        ("TSLA", _ago(minutes=32), _ago(minutes=30), "ok", None),
        ("AAPL", _ago(minutes=95), _ago(minutes=92), "ok", ""),
        # A partial-write job: excluded from last scan and scan duration.
        ("SPX", _ago(minutes=2), _ago(minutes=1), "ok", "gex_scan_spx"),
        ("NVDA", _ago(minutes=50), _ago(minutes=49), "error", None),
    ]:
        cur.execute(
            "INSERT INTO uw_scan.scan_runs "
            "(ticker, started_at, finished_at, status, notes) "
            "VALUES (%s, %s, %s, %s, %s)",
            (ticker, started, finished, status, notes),
        )
    for ticker, status, requested, finished in [
        ("TSLA", "done", _ago(minutes=40), _ago(minutes=38)),
        ("AAPL", "failed", _ago(minutes=20), _ago(minutes=19)),
        ("MSFT", "queued", _ago(minutes=5), None),
    ]:
        cur.execute(
            "INSERT INTO uw_scan.jobs (ticker, status, requested_at, finished_at) "
            "VALUES (%s, %s, %s, %s)",
            (ticker, status, requested, finished),
        )


def _seed_external_api(cur) -> None:
    rows = [
        # provider, status_code, family, started, latency_ms, daily_count
        ("uw", 200, "2xx", _ago(hours=6), 100, 1000),
        ("uw", 200, "2xx", _ago(hours=3), 200, 1500),
        ("uw", 200, "2xx", _ago(minutes=30), 300, 2400),
        ("uw", 404, "4xx", _ago(minutes=25), 80, None),
        ("uw", 429, "4xx", _ago(minutes=20), 50, None),
        ("uw", 503, "5xx", _ago(minutes=10), 900, None),
        # Before the provider day (reset Thu 20:00 ET = Fri 00:00Z): excluded.
        ("uw", 200, "2xx", _ago(hours=16), 5000, 99999),
        ("massive", 200, "2xx", _ago(hours=2), 40, None),
        ("massive", 200, "2xx", _ago(hours=1), 60, None),
        ("massive", 429, "4xx", _ago(minutes=45), 30, None),
    ]
    for provider, code, family, started, latency, count in rows:
        cur.execute(
            "INSERT INTO uw_scan.external_api_requests "
            "(provider, endpoint_key, method, path, status_code, status_family, "
            " request_started_at, request_finished_at, latency_ms, "
            " official_daily_count, official_daily_limit) "
            "VALUES (%s, 'ep', 'GET', '/p', %s, %s, %s, %s, %s, %s, %s)",
            (
                provider,
                code,
                family,
                started,
                started + timedelta(milliseconds=latency),
                latency,
                count,
                120000 if count is not None else None,
            ),
        )


def _seed_record_snapshot(cur) -> None:
    for table, rows, tickers, latest, computed in [
        ("watchlist_card", 60, 54, _ago(minutes=3), _ago(minutes=5)),
        ("flow_alerts", 12, 10, _ago(minutes=7), _ago(minutes=6)),
    ]:
        cur.execute(
            "INSERT INTO uw_scan.record_health_snapshot "
            "(table_name, window_start, actual_rows, actual_tickers, latest_at, "
            " computed_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (table, _ago(hours=8), rows, tickers, latest, computed),
        )


def _seed_freshness(repo) -> None:
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)

    def row(name, frozen, coverage, stale):
        return FreshnessRow(
            name,
            "market_date",
            "watchlist",
            54,
            int(54 * coverage),
            coverage,
            date(2026, 5, 14) - timedelta(days=stale),
            stale,
            frozen,
            None,
        )

    for run_date in (date(2026, 5, 12), date(2026, 5, 13), date(2026, 5, 14)):
        last = run_date == date(2026, 5, 14)
        fr.upsert_snapshot(
            run_date,
            [
                # Frozen 3 nights, has a healer adapter -> circuit broken.
                row("daily_ohlc", True, 0.5, 6),
                # Frozen 3 nights, no healer adapter -> never in the breaker.
                row("intraday_quote", True, 0.0, 9),
                # Frozen only the newest night -> streak 1, below the breaker.
                row("option_surface_grid_daily", last, 0.8 if last else 1.0, 2),
                row("vrp_daily", False, 1.0, 1),
            ],
        )


def _seed_gap_healer(cur) -> None:
    cur.execute(
        "INSERT INTO uw_scan.data_gap_runs (started_at, finished_at, mode, status) "
        "VALUES (%s, %s, 'execute', 'complete') RETURNING id",
        (_ago(days=2), _ago(days=2) + timedelta(hours=1)),
    )
    old_run = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO uw_scan.data_gap_runs (started_at, mode, status) "
        "VALUES (%s, 'execute', 'running') RETURNING id",
        (_ago(hours=5),),
    )
    run_id = cur.fetchone()[0]
    items = [
        (old_run, "daily_ohlc", "old-1", "failed", None),
        (run_id, "daily_ohlc", "k1", "healed", _ago(hours=4)),
        (run_id, "daily_ohlc", "k2", "healed", _ago(hours=3)),
        (run_id, "daily_ohlc", "k3", "planned", None),
        (run_id, "greek_exposure_daily", "k4", "no_data", _ago(hours=2)),
        (run_id, "greek_exposure_daily", "k5", "failed", None),
        (run_id, "greek_exposure_daily", "k6", "skipped_budget", None),
        (run_id, "greek_exposure_daily", "k7", "planned", None),
        (run_id, "uw_gex_levels_daily", "k8", "running", None),
    ]
    for rid, dataset, scope, status, verified in items:
        cur.execute(
            "INSERT INTO uw_scan.data_gap_items "
            "(run_id, dataset, scope_key, status, verified_at, data_date) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (rid, dataset, scope, status, verified, date(2026, 5, 13)),
        )


def _seed_ws_state(cur) -> None:
    cur.execute(
        """
        UPDATE uw_scan.ws_consumer_state
           SET last_tick_at = %s, last_flush_at = %s, ticks_received = 1000,
               ticks_flushed = 990, connection_started_at = %s,
               last_error = 'ConnectionClosed()', last_error_at = %s,
               updated_at = %s, active_source = 'xenon_ws'
         WHERE id = 1
        """,
        (
            _ago(minutes=20),
            _ago(minutes=10),
            _ago(hours=3),
            _ago(hours=3, minutes=5),
            _ago(minutes=10),
        ),
    )


def _seed_job_failures(cur) -> None:
    # Distinct streaks: list_streaks orders by consecutive only.
    for job, consecutive, error, failed in [
        ("full_scan", 3, "TimeoutError('uw')", _ago(minutes=20)),
        ("gex_scan", 1, "ValueError('bad')", _ago(hours=2)),
        ("ohlc_refresh", 0, None, None),
    ]:
        cur.execute(
            "INSERT INTO uw_scan.job_failures "
            "(job_name, consecutive, last_error, last_failed_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (job, consecutive, error, failed, _ago(minutes=1)),
        )


def _seed_ai_queue(repo) -> None:
    run_id, snapshot_id = _seed_snapshot(repo)
    ids = {}
    for key, provider in [
        ("codex-1", "codex"),
        ("codex-2", "codex"),
        ("claude-1", "claude"),
        ("deepseek-1", "deepseek"),
        ("deepseek-2", "deepseek"),
    ]:
        ids[key] = repo.enqueue_trade_insight_ai_analysis(
            snapshot_id=snapshot_id,
            ticker="TSLA",
            run_id=run_id,
            trade_insights_input_hash="h",
            analysis_input_hash=key,
            analysis_input={"k": key},
            prompt_version="trade-insights-ai-v4",
            model=f"{provider}-default",
            provider=provider,
        )
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.trade_insight_ai_analyses SET status = 'running', "
            "started_at = %s, claim_token = gen_random_uuid() "
            "WHERE analysis_id = %s",
            (_ago(minutes=1), ids["codex-2"]),
        )
        cur.execute(
            "UPDATE uw_scan.trade_insight_ai_analyses SET status = 'succeeded', "
            "finished_at = %s WHERE analysis_id = %s",
            (_ago(minutes=2), ids["deepseek-2"]),
        )
    repo.conn.commit()


def _seed(repo) -> None:
    with repo.conn.cursor() as cur:
        _seed_heartbeats(cur)
        _seed_quotes(cur)
        _seed_scans_and_jobs(cur)
        _seed_external_api(cur)
        _seed_record_snapshot(cur)
        _seed_gap_healer(cur)
        _seed_ws_state(cur)
        _seed_job_failures(cur)
    repo.conn.commit()
    _seed_freshness(repo)
    repo.conn.commit()
    _seed_ai_queue(repo)


def _stale_record_snapshot(repo) -> None:
    """Record snapshot older than 45 min; WS heartbeat fresh again."""
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.record_health_snapshot SET computed_at = %s "
            "WHERE table_name = 'watchlist_card'",
            (_ago(minutes=60),),
        )
        cur.execute(
            "UPDATE uw_scan.record_health_snapshot SET computed_at = %s "
            "WHERE table_name = 'flow_alerts'",
            (_ago(minutes=50),),
        )
        # And the WS consumer flushed 30 s ago: the fresh-heartbeat branch.
        cur.execute(
            "UPDATE uw_scan.ws_consumer_state SET last_flush_at = %s WHERE id = 1",
            (_ago(seconds=30),),
        )
    repo.conn.commit()


def _miss_full_scans(repo) -> None:
    """Last ok full scan on Thu 16:30 ET: Friday's crons since are missed."""
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.scan_runs SET started_at = %s, finished_at = %s "
            "WHERE status = 'ok' AND (notes IS NULL OR notes = '')",
            (
                _dt.datetime(2026, 5, 14, 20, 28, tzinfo=UTC),
                _dt.datetime(2026, 5, 14, 20, 30, tzinfo=UTC),
            ),
        )
    repo.conn.commit()


def test_health_matches_golden(frozen_client, seeded_db_empty_cards):
    client = frozen_client
    repo = seeded_db_empty_cards
    result = {"empty": _sweep(client)}

    _seed(repo)
    result["seeded"] = _sweep(client)

    _CLOCK["now"] = NOW_CLOSED
    result["seeded_closed"] = _sweep(client)
    _CLOCK["now"] = NOW_RTH

    _stale_record_snapshot(repo)
    result["stale_record_snapshot"] = _sweep(client)

    _miss_full_scans(repo)
    result["missed_full_scans"] = _sweep(client)

    text = json.dumps(result, sort_keys=True, indent=1, default=str) + "\n"

    if os.environ.get("HEALTH_GOLDEN_WRITE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(text)
        pytest.skip("golden written")
    assert text == GOLDEN.read_text(), (
        "/api/health responses changed; diff against "
        "tests/integration/api/golden/health.json"
    )
