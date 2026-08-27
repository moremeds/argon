"""Cross-statement net-income reconciliation, wired into `fundamental_ingest`
(Task 10, spec §5-vi).

Uses a PRIVATE database (`option_wizard_test_nireconcile`), not the shared
`option_wizard_test` the rest of the integration suite resets per-fixture —
mirrors `test_fundamental_change_events.py`'s private-DB shape exactly (other
worktree sessions run integration tests against the shared DB concurrently,
and the shared DB has a known local ownership drift on this machine).

The UW transport is stubbed; the DATABASE is real. Stubbing an external
service is expected, faking the DB is banned.

FIXTURE PROVENANCE (queried live, 2026-08-28, dev warm store
postgresql://argon_app@127.0.0.1/option_wizard_local -- the mini,
100.66.147.98, answers ICMP/TCP:5432 from this session but has no SSH key or
DB password configured here, so `option_wizard` on the mini was unreachable
this session; recorded as a deviation, not a silent substitution)
------------------------------------------------------------------------
CVX's real 2023-06-30 quarterly pair (obs identity, not the row values --
those are reproduced inline below):

    SELECT statement, obs_id, raw_jsonb->>'net_income'
      FROM fundamental_statement_obs
     WHERE ticker='CVX' AND period_end='2023-06-30'
       AND statement IN ('income','cash_flow')
     ORDER BY statement, obs_id DESC;
    -> income    obs_id=30580  net_income='6010000000'
       cash_flow obs_id=30746  net_income='-6000000000'

NVDA's real 2026-04-30 quarterly pair AGREES (same figures already frozen in
`tests/unit/fundamentals/test_statements.py` and
`tests/integration/storage/test_fundamental_obs.py`):

    income net_income='58321000000' (obs_id=1), cash_flow net_income=
    '58321000000' (obs_id=165) -- identical.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import psycopg
import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.config import Settings
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.worker.jobs.fundamental_ingest import fundamental_ingest

_TEST_DB_NAME = "option_wizard_test_nireconcile"

CHECK_NAME = "net_income_disagrees_across_statements"

CVX_INCOME = {
    "ticker": "CVX",
    "fiscal_date_ending": "2023-06-30",
    "report_type": "quarterly",
    "net_income": "6010000000",
}
CVX_CASH_FLOW_DISAGREEING = {
    "ticker": "CVX",
    "fiscal_date_ending": "2023-06-30",
    "report_type": "quarterly",
    "net_income": "-6000000000",
}
CVX_BALANCE = {
    "ticker": "CVX",
    "fiscal_date_ending": "2023-06-30",
    "report_type": "quarterly",
}

NVDA_INCOME_AGREEING = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "net_income": "58321000000",
}
NVDA_CASH_FLOW_AGREEING = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "net_income": "58321000000",
}
NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
}

EMPTY_BREAKDOWN: dict = {"data": {"general": []}}


def _maint_settings() -> Settings:
    import os

    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": "postgres"})


@pytest.fixture(scope="module")
def _ni_settings() -> Iterator[Settings]:
    maint = _maint_settings()
    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB_NAME,)
            )
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')

    settings = maint.model_copy(update={"db_name": _TEST_DB_NAME})
    yield settings

    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"')


@pytest.fixture
def conn(_ni_settings: Settings) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_ni_settings.db_dsn(), autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
        apply_migrations(admin, log=lambda _msg: None)

    connection = psycopg.connect(_ni_settings.db_dsn())
    try:
        yield connection
    finally:
        connection.close()


class _Response:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return json.loads(json.dumps(self._payload))


class _StubClient:
    """Serves the three statement slugs plus the breakdown for a fixed set of
    tickers. `data[ticker][slug]` is mutable so a test can simulate a
    statement landing in a LATER run by starting it empty."""

    def __init__(self, data: dict[str, dict[EndpointSlug, list[dict]]]) -> None:
        self.data = data
        self.calls: list[tuple[str, EndpointSlug]] = []

    def get(self, slug, *, ticker, **_kw):
        self.calls.append((ticker, slug))
        if slug is EndpointSlug.FUNDAMENTAL_BREAKDOWN:
            return _Response(EMPTY_BREAKDOWN), None
        rows = self.data.get(ticker, {}).get(slug, [])
        return _Response({"data": rows}), None


def _base_data() -> dict[str, dict[EndpointSlug, list[dict]]]:
    return {
        "CVX": {
            EndpointSlug.INCOME_STATEMENTS: [dict(CVX_INCOME)],
            EndpointSlug.BALANCE_SHEETS: [dict(CVX_BALANCE)],
            EndpointSlug.CASH_FLOWS: [dict(CVX_CASH_FLOW_DISAGREEING)],
        },
        "NVDA": {
            EndpointSlug.INCOME_STATEMENTS: [dict(NVDA_INCOME_AGREEING)],
            EndpointSlug.BALANCE_SHEETS: [dict(NVDA_BALANCE)],
            EndpointSlug.CASH_FLOWS: [dict(NVDA_CASH_FLOW_AGREEING)],
        },
    }


def _repo(connection: psycopg.Connection) -> FundamentalObsRepository:
    return FundamentalObsRepository(connection, schema="uw_scan")


def _run(connection, client, tickers):
    return fundamental_ingest(
        conn=connection, client=client, schema="uw_scan", tickers=tickers
    )


def _violation_rows(connection) -> list[tuple[str, str, str]]:
    """(ticker, statement, check_name) for every recorded violation."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT o.ticker, o.statement, v.check_name
              FROM uw_scan.fundamental_obs_violations v
              JOIN uw_scan.fundamental_statement_obs o USING (obs_id)
             WHERE v.check_name = %s
            """,
            (CHECK_NAME,),
        )
        return cur.fetchall()


def test_real_disagreeing_pair_is_persisted_against_the_income_obs(conn):
    client = _StubClient(_base_data())
    totals = _run(conn, client, ["CVX"])
    assert totals["violations"] == 1

    rows = _violation_rows(conn)
    assert rows == [("CVX", "income", CHECK_NAME)]  # attached to INCOME, not cash_flow


def test_real_agreeing_pair_raises_nothing(conn):
    client = _StubClient(_base_data())
    _run(conn, client, ["NVDA"])
    assert _violation_rows(conn) == []


def test_worst_ni_offenders_names_the_ticker(conn):
    client = _StubClient(_base_data())
    _run(conn, client, ["CVX", "NVDA"])
    offenders = _repo(conn).worst_ni_offenders()
    assert offenders == [{"ticker": "CVX", "violation_count": 1}]


def test_late_arriving_cash_flow_is_caught_on_the_next_full_reingest(conn):
    """The cash-flow statement is NOT yet in the batch on run 1 (simulating it
    landing in a later provider publish); no cross-check can fire because there
    is no pair. Run 2 re-fetches the ticker's FULL history (as `fundamental_ingest`
    always does) and now finds the disagreeing pair -- this is exactly what the
    monthly full-tier sweep guarantees for every ticker it revisits, since the
    sweep calls this same function unfiltered by calendar (see scheduler.py's
    `_fundamental_ingest` and `fundamental_ingest`'s own module docstring)."""
    data = _base_data()
    data["CVX"][EndpointSlug.CASH_FLOWS] = []  # not yet published

    client = _StubClient(data)
    first = _run(conn, client, ["CVX"])
    assert first["violations"] == 0
    assert _violation_rows(conn) == []

    # The cash-flow statement is now available -- a subsequent full re-ingest
    # (daily calendar hit or monthly sweep) re-fetches everything again.
    client.data["CVX"][EndpointSlug.CASH_FLOWS] = [dict(CVX_CASH_FLOW_DISAGREEING)]
    second = _run(conn, client, ["CVX"])
    assert second["violations"] == 1
    assert _violation_rows(conn) == [("CVX", "income", CHECK_NAME)]


def test_a_third_reingest_is_idempotent(conn):
    """`record_violations` is ON CONFLICT DO NOTHING per (obs_id, check_name) --
    re-running the same disagreeing pair must not write a second row nor count
    a second violation."""
    client = _StubClient(_base_data())
    _run(conn, client, ["CVX"])
    again = _run(conn, client, ["CVX"])
    assert again["violations"] == 0
    assert len(_violation_rows(conn)) == 1
