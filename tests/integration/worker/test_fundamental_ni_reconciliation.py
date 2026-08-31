"""Cross-statement net-income checks, wired into `fundamental_ingest`
(Task 10, spec §5-vi, fix round 1).

Uses a PRIVATE database (`option_wizard_test_nireconcile`), not the shared
`option_wizard_test` the rest of the integration suite resets per-fixture —
mirrors `test_fundamental_change_events.py`'s private-DB shape exactly (other
worktree sessions run integration tests against the shared DB concurrently,
and the shared DB has a known local ownership drift on this machine).

The UW transport is stubbed; the DATABASE is real. Stubbing an external
service is expected, faking the DB is banned.

TWO SEPARATE MECHANISMS UNDER TEST
-----------------------------------
`check_net_income_sign_flip` (a genuine vendor defect: opposite sign, matching
magnitude) is the only one persisted via `record_violations`, wired into
`fundamental_ingest`'s per-ticker loop. `net_income_basis_difference` (the
NCI/discontinued-ops-driven population — descriptive, never a violation) is
NOT called during ingest at all; it is read-time-only, exercised here via
`FundamentalObsRepository.net_income_basis_differences_by_ticker`, which
queries `fundamental_statement_obs` directly rather than the violations table.

FIXTURE PROVENANCE (queried live, 2026-08-28, dev warm store
postgresql://argon_app@127.0.0.1/option_wizard_local -- the mini,
100.66.147.98, answers ICMP/TCP:5432 from this session but has no SSH key or
DB password configured here, so `option_wizard` on the mini was unreachable
this session; recorded as a deviation, not a silent substitution)
------------------------------------------------------------------------
CVX's real 2023-06-30 quarterly pair -- a genuine sign-flip DEFECT (matching
magnitude, opposite sign; one of 5 across the full local historical store):

    SELECT statement, obs_id, raw_jsonb->>'net_income'
      FROM fundamental_statement_obs
     WHERE ticker='CVX' AND period_end='2023-06-30'
       AND statement IN ('income','cash_flow')
     ORDER BY statement, obs_id DESC;
    -> income    obs_id=30580  net_income='6010000000'
       cash_flow obs_id=30746  net_income='-6000000000'

NVDA's real 2026-04-30 quarterly pair AGREES exactly (same figures already
frozen in `tests/unit/fundamentals/test_statements.py` and
`tests/integration/storage/test_fundamental_obs.py`):

    income net_income='58321000000' (obs_id=1), cash_flow net_income=
    '58321000000' (obs_id=165) -- identical.

VZ's real 2010-09-30 quarterly pair -- Verizon's own disclosed NCI split
(Vodafone's 45% of Verizon Wireless: 881M + 1,817M = 2,698M). Same sign, large
magnitude gap, both figures correct -- must be descriptive, never a violation:

    -> income  obs_id=62195 net_income='881000000',
       net_income_from_continuing_operations='0'
       cash_flow obs_id=62361 net_income='2698000000'

Boeing's real 2017-03-31 quarterly pair -- cash-flow matches the income
statement's OWN `net_income_from_continuing_operations` (1,451,000,000), not
its headline (1,579,000,000). Must be neither a violation nor a basis gap:

    -> income  net_income='1579000000',
       net_income_from_continuing_operations='1451000000'
       cash_flow net_income='1451000000'
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import psycopg
import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.config import Settings
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.worker.jobs.fundamental_ingest import fundamental_ingest

# Per-xdist-worker: a module-private database dropped at teardown races itself under
# `-n auto`. Full rationale in tests/integration/storage/test_fundamental_change_events.py.
_XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER")
_TEST_DB_NAME = "option_wizard_test_nireconcile" + (
    f"_{_XDIST_WORKER}" if _XDIST_WORKER else ""
)

CHECK_NAME = "net_income_sign_flipped_across_statements"

CVX_INCOME = {
    "ticker": "CVX",
    "fiscal_date_ending": "2023-06-30",
    "report_type": "quarterly",
    "net_income": "6010000000",
}
CVX_CASH_FLOW_SIGN_FLIPPED = {
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

VZ_INCOME_NCI = {
    "ticker": "VZ",
    "fiscal_date_ending": "2010-09-30",
    "report_type": "quarterly",
    "net_income": "881000000",
    "net_income_from_continuing_operations": "0",
}
VZ_CASH_FLOW_NCI = {
    "ticker": "VZ",
    "fiscal_date_ending": "2010-09-30",
    "report_type": "quarterly",
    "net_income": "2698000000",
}
VZ_BALANCE = {
    "ticker": "VZ",
    "fiscal_date_ending": "2010-09-30",
    "report_type": "quarterly",
}

BA_INCOME_CONTINUING_OPS = {
    "ticker": "BA",
    "fiscal_date_ending": "2017-03-31",
    "report_type": "quarterly",
    "net_income": "1579000000",
    "net_income_from_continuing_operations": "1451000000",
}
BA_CASH_FLOW_MATCHES_CONTINUING_OPS = {
    "ticker": "BA",
    "fiscal_date_ending": "2017-03-31",
    "report_type": "quarterly",
    "net_income": "1451000000",
}
BA_BALANCE = {
    "ticker": "BA",
    "fiscal_date_ending": "2017-03-31",
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
            EndpointSlug.CASH_FLOWS: [dict(CVX_CASH_FLOW_SIGN_FLIPPED)],
        },
        "NVDA": {
            EndpointSlug.INCOME_STATEMENTS: [dict(NVDA_INCOME_AGREEING)],
            EndpointSlug.BALANCE_SHEETS: [dict(NVDA_BALANCE)],
            EndpointSlug.CASH_FLOWS: [dict(NVDA_CASH_FLOW_AGREEING)],
        },
        "VZ": {
            EndpointSlug.INCOME_STATEMENTS: [dict(VZ_INCOME_NCI)],
            EndpointSlug.BALANCE_SHEETS: [dict(VZ_BALANCE)],
            EndpointSlug.CASH_FLOWS: [dict(VZ_CASH_FLOW_NCI)],
        },
        "BA": {
            EndpointSlug.INCOME_STATEMENTS: [dict(BA_INCOME_CONTINUING_OPS)],
            EndpointSlug.BALANCE_SHEETS: [dict(BA_BALANCE)],
            EndpointSlug.CASH_FLOWS: [dict(BA_CASH_FLOW_MATCHES_CONTINUING_OPS)],
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


def test_real_sign_flip_defect_is_persisted_against_the_income_obs(conn):
    client = _StubClient(_base_data())
    totals = _run(conn, client, ["CVX"])
    assert totals["violations"] == 1

    rows = _violation_rows(conn)
    assert rows == [("CVX", "income", CHECK_NAME)]  # attached to INCOME, not cash_flow


def test_real_agreeing_pair_raises_nothing(conn):
    client = _StubClient(_base_data())
    _run(conn, client, ["NVDA"])
    assert _violation_rows(conn) == []


def test_real_nci_pair_is_never_persisted_as_a_violation(conn):
    """VZ's own disclosed NCI split must NEVER reach `fundamental_obs_violations`
    -- this is the entire point of narrowing the check."""
    client = _StubClient(_base_data())
    totals = _run(conn, client, ["VZ"])
    assert totals["violations"] == 0
    assert _violation_rows(conn) == []


def test_real_continuing_ops_match_raises_no_violation(conn):
    client = _StubClient(_base_data())
    totals = _run(conn, client, ["BA"])
    assert totals["violations"] == 0
    assert _violation_rows(conn) == []


def test_net_income_basis_differences_by_ticker_names_the_nci_ticker_not_the_defect(
    conn,
):
    """The descriptive read surfaces VZ (NCI-driven, real gap) but NEVER CVX
    (a genuine sign-flip defect, which lives in the violations table instead)
    and NEVER BA (its cash-flow matches continuing-ops, so there is no gap at
    all) -- proves the three populations (violation / descriptive / clean)
    stay mutually exclusive end to end, not just inside the pure function."""
    client = _StubClient(_base_data())
    _run(conn, client, ["CVX", "NVDA", "VZ", "BA"])
    diffs = _repo(conn).net_income_basis_differences_by_ticker()
    assert diffs == [{"ticker": "VZ", "basis_difference_count": 1}]


def test_late_arriving_cash_flow_is_caught_on_the_next_full_reingest(conn):
    """The cash-flow statement is NOT yet in the batch on run 1 (simulating it
    landing in a later provider publish); no check can fire because there is
    no pair. Run 2 re-fetches the ticker's FULL history (as `fundamental_ingest`
    always does) and now finds the sign-flipped pair -- this is exactly what
    the monthly full-tier sweep guarantees for every ticker it revisits, since
    the sweep calls this same function unfiltered by calendar (see
    scheduler.py's `_fundamental_ingest` and `fundamental_ingest`'s own module
    docstring)."""
    data = _base_data()
    data["CVX"][EndpointSlug.CASH_FLOWS] = []  # not yet published

    client = _StubClient(data)
    first = _run(conn, client, ["CVX"])
    assert first["violations"] == 0
    assert _violation_rows(conn) == []

    # The cash-flow statement is now available -- a subsequent full re-ingest
    # (daily calendar hit or monthly sweep) re-fetches everything again.
    client.data["CVX"][EndpointSlug.CASH_FLOWS] = [dict(CVX_CASH_FLOW_SIGN_FLIPPED)]
    second = _run(conn, client, ["CVX"])
    assert second["violations"] == 1
    assert _violation_rows(conn) == [("CVX", "income", CHECK_NAME)]


def test_a_third_reingest_is_idempotent(conn):
    """`record_violations` is ON CONFLICT DO NOTHING per (obs_id, check_name) --
    re-running the same sign-flipped pair must not write a second row nor
    count a second violation."""
    client = _StubClient(_base_data())
    _run(conn, client, ["CVX"])
    again = _run(conn, client, ["CVX"])
    assert again["violations"] == 0
    assert len(_violation_rows(conn)) == 1
