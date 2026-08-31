"""The healer's own spend and progress must be observable.

Two blind spots this covers, both real as of 2026-08-24:

* `HealContext` built its UW and massive clients with `job_name=` but no
  `telemetry_recorder`, so `external_api_requests` never held a single healer
  row -- and `sources/uw_budget.read_snapshot` derives BOTH pool spend and the
  account counter from that table. An untelemetered healer is not merely
  unobserved by the governor, it is arithmetically invisible to it.
* Progress lived only in stdout. Four nightly runs stopped 50-88 minutes in
  with zero failures, and their containers were later recreated, so the
  evidence of where they stopped no longer exists anywhere.

The stub server returns an empty `{}` envelope on purpose: this asserts
telemetry, not payload parsing, and inventing a market value to decorate a
test would violate the no-synthetic-data rule for nothing.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.config import Settings
from uw_scan.reports.data_gap_healer import GapItem
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.data_gap_adapters import (
    HealContext,
    HealSpec,
    RequestBudget,
    execute_run,
)

_TODAY = date(2026, 6, 30)


class _UwStubHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        body = json.dumps({"data": {}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("x-uw-daily-req-count", "4211")
        self.send_header("x-uw-token-req-limit", "120000")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def uw_stub_base_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UwStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _settings_for(repo: Repository, base_url: str) -> Settings:
    return Settings.from_env().model_copy(
        update={"db_name": repo.conn.info.dbname, "base_url": base_url}
    )


def _ctx(seeded: Repository, **kwargs) -> HealContext:
    gap = DataGapHealerRepository(seeded.conn, schema=seeded._schema)
    return HealContext(
        repo=seeded,
        gap=gap,
        schema=seeded._schema,
        today=_TODAY,
        budget=RequestBudget(None),
        **kwargs,
    )


def _healer_rows(repo: Repository) -> list[tuple]:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT provider, endpoint_key, official_daily_count "
            f"FROM {repo._schema}.external_api_requests "
            "WHERE job_name = 'data_gap_healer' ORDER BY request_id"
        )
        return cur.fetchall()


def test_uw_spend_lands_in_external_api_requests(
    seeded_db_empty_cards: Repository, uw_stub_base_url: str
) -> None:
    """A heal's UW call must be attributable to the healer in the budget table."""
    repo = seeded_db_empty_cards
    settings = _settings_for(repo, uw_stub_base_url)

    with ExternalApiRequestRecorder(
        settings.db_dsn(), schema=settings.db_schema
    ) as recorder:
        ctx = _ctx(repo, settings=settings, recorder=recorder)
        ctx.uw_client().get(EndpointSlug.IV_RANK, ticker="TSLA")

    rows = _healer_rows(repo)
    assert len(rows) == 1, "the healer's UW call left no telemetry row"
    provider, endpoint_key, daily_count = rows[0]
    assert provider == "uw"
    assert endpoint_key == EndpointSlug.IV_RANK.value
    # read_snapshot keys the account guard off this column; a NULL here makes the
    # governor believe a quiet account no matter how much the healer spent.
    assert daily_count == 4211


def test_progress_heartbeat_survives_the_container(
    seeded_db_empty_cards: Repository,
) -> None:
    """The last stage reached must be readable from Postgres, not only stdout."""
    repo = seeded_db_empty_cards
    ctx = _ctx(repo)
    run_id = ctx.gap.create_run(
        mode="execute", start_date=None, end_date=None, datasets=["daily_ohlc"]
    )
    ctx.gap.upsert_items(
        run_id,
        [GapItem("daily_ohlc", "2026-06-22|KORU", date(2026, 6, 22), "KORU", 1, 0)],
    )

    def fake_range(ctx_, ticker, lo, hi):
        with ctx_.repo.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {ctx_.repo._schema}.daily_ohlc "
                "(ticker, date, close, source) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (ticker, lo, 1.0, "test-heal"),
            )
        ctx_.repo.conn.commit()
        return 1

    execute_run(
        ctx,
        run_id,
        specs={
            "daily_ohlc": HealSpec("daily_ohlc", "massive", "per_ticker_range", fake_range)
        },
    )

    beat = (ctx.gap.get_run(run_id)["summary_jsonb"] or {}).get("heartbeat")
    assert beat, "no durable heartbeat written to data_gap_runs.summary_jsonb"
    assert beat["dataset"] == "daily_ohlc"
    assert beat["stage"] == "marked"
    assert beat["ticker"] == "KORU"
    assert beat["at"]


def test_recorder_failure_is_counted_not_swallowed() -> None:
    """A dead recorder must be visible; today it logs and the heal walks on."""
    recorder = ExternalApiRequestRecorder.__new__(ExternalApiRequestRecorder)
    recorder._dsn = "postgresql://127.0.0.1:1/nope"
    recorder._schema = "uw_scan"
    recorder._conn = None
    recorder._repo = None
    recorder.failures = 0

    assert recorder.record(object()) is False  # type: ignore[arg-type]
    assert recorder.failures == 1
