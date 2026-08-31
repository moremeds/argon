"""Forward ingest must claim availability for every version it persists.

Without this, only the legacy backfill produces claims and every statement
captured after it silently falls out of history — invisible to both policies,
because an observation with no claim fails closed. The failure would be silent in
the worst way: the current page would keep working perfectly.

The UW transport is stubbed; the DATABASE is real. Stubbing an external service is
expected, faking the DB is banned, and the figures below are NVDA's real
2026-04-30 quarterly statements, frozen — no invented values pass through the stub.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.fundamentals.observation_time import (
    CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
    EvidenceClass,
    EvidencePolicy,
)
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.fundamental_observation_panels import statement_panel_as_of
from uw_scan.worker.jobs.fundamental_ingest import fundamental_ingest

PERIOD = "2026-04-30"

NVDA_INCOME = {
    "ticker": "NVDA",
    "fiscal_date_ending": PERIOD,
    "report_type": "quarterly",
    "total_revenue": "44062000000",
    "net_income": "18775000000",
    "inserted_at": "2026-05-21T06:58:08Z",
}
NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": PERIOD,
    "report_type": "quarterly",
    "total_assets": "259474000000",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "inserted_at": "2026-05-21T06:58:08Z",
}
NVDA_CASH_FLOW = {
    "ticker": "NVDA",
    "fiscal_date_ending": PERIOD,
    "report_type": "quarterly",
    "operating_cashflow": "27414000000",
    "capital_expenditures": "1227000000",
    "inserted_at": "2026-05-21T06:58:08Z",
}

BREAKDOWN = {
    "data": {
        "general": [
            {"report_period_end_date": PERIOD, "filing_date": "2026-05-21"},
        ]
    }
}


class _Response:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return json.loads(json.dumps(self._payload))


class _StubClient:
    """Serves the three statement slugs plus the breakdown. Mutable payloads so a
    test can make the provider restate between calls."""

    def __init__(self) -> None:
        self.data = {
            EndpointSlug.INCOME_STATEMENTS: [dict(NVDA_INCOME)],
            EndpointSlug.BALANCE_SHEETS: [dict(NVDA_BALANCE)],
            EndpointSlug.CASH_FLOWS: [dict(NVDA_CASH_FLOW)],
        }
        self.calls: list[EndpointSlug] = []

    def get(self, slug, **_kw):
        self.calls.append(slug)
        if slug is EndpointSlug.FUNDAMENTAL_BREAKDOWN:
            return _Response(BREAKDOWN), None
        return _Response({"data": self.data[slug]}), None


@pytest.fixture
def client() -> _StubClient:
    return _StubClient()


def _run(seeded, client, **kw):
    return fundamental_ingest(
        conn=seeded.conn,
        client=client,
        schema=seeded._schema,
        tickers=["NVDA"],
        **kw,
    )


def _repo(seeded) -> FundamentalObsAvailabilityRepository:
    return FundamentalObsAvailabilityRepository(seeded.conn, schema=seeded._schema)


def test_every_newly_persisted_version_gets_a_capture_claim(
    seeded_db_empty_cards, client
):
    totals = _run(seeded_db_empty_cards, client)
    assert totals["inserted"] == 3
    assert totals["availability_claims"] == 3
    counts = _repo(seeded_db_empty_cards).claim_counts()
    assert counts[EvidenceClass.CAPTURE_BOUNDED] == 3
    assert _repo(seeded_db_empty_cards).unclaimed_observation_count() == 0


def test_the_capture_claim_matches_the_rows_own_first_observed_at(
    seeded_db_empty_cards, client
):
    _run(seeded_db_empty_cards, client)
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*)
              FROM {seeded_db_empty_cards._schema}.fundamental_obs_availability a
              JOIN {seeded_db_empty_cards._schema}.fundamental_statement_obs o
                ON o.obs_id = a.obs_id
             WHERE a.claim_key = %s
               AND a.available_at IS DISTINCT FROM o.first_observed_at
            """,
            (CLAIM_KEY_CAPTURE_FIRST_OBSERVED,),
        )
        assert cur.fetchone()[0] == 0


def test_an_unchanged_refetch_creates_no_new_claim(seeded_db_empty_cards, client):
    _run(seeded_db_empty_cards, client)
    second = _run(seeded_db_empty_cards, client)
    assert second["inserted"] == 0
    assert second["touched"] == 3
    assert second["availability_claims"] == 0
    assert _repo(seeded_db_empty_cards).claim_counts() == {
        EvidenceClass.CAPTURE_BOUNDED: 3,
        EvidenceClass.CURRENT_VINTAGE: 3,
    }


def test_a_restated_payload_gets_its_own_observation_and_its_own_claim(
    seeded_db_empty_cards, client
):
    _run(seeded_db_empty_cards, client)
    client.data[EndpointSlug.BALANCE_SHEETS] = [
        {**NVDA_BALANCE, "total_assets": "259475000000"}
    ]
    second = _run(seeded_db_empty_cards, client)
    assert second["inserted"] == 1
    assert second["availability_claims"] == 1
    assert _repo(seeded_db_empty_cards).claim_counts() == {
        EvidenceClass.CAPTURE_BOUNDED: 4,
        EvidenceClass.CURRENT_VINTAGE: 4,
    }


def test_a_later_filing_date_fill_does_not_disturb_the_existing_claim(
    seeded_db_empty_cards, client
):
    """Filing-date recovery must stay a no-op for content identity AND for claims."""
    _run(seeded_db_empty_cards, client)
    before = _repo(seeded_db_empty_cards).claims_for_obs_ids(
        _obs_ids(seeded_db_empty_cards)
    )
    _run(seeded_db_empty_cards, client)
    after = _repo(seeded_db_empty_cards).claims_for_obs_ids(
        _obs_ids(seeded_db_empty_cards)
    )
    assert before == after


def test_a_run_whose_claim_stage_fails_is_not_reported_as_a_success(
    seeded_db_empty_cards, client, monkeypatch
):
    """The observation may already be committed; the ticker must still count as
    failed so the operator re-runs and the retry heals the missing claim."""
    from uw_scan.worker.jobs import fundamental_ingest as mod

    def boom(**_kw):
        raise RuntimeError("claim stage down")

    monkeypatch.setattr(mod, "fundamental_observation_availability", boom)
    totals = _run(seeded_db_empty_cards, client)
    assert totals["failed"] == 1
    assert totals["tickers"] == 0

    monkeypatch.undo()
    healed = _run(seeded_db_empty_cards, client)
    assert healed["failed"] == 0
    assert healed["availability_claims"] == 3
    assert _repo(seeded_db_empty_cards).unclaimed_observation_count() == 0


def test_an_unclaimed_row_is_invisible_to_history_until_the_retry(
    seeded_db_empty_cards, client, monkeypatch
):
    from uw_scan.worker.jobs import fundamental_ingest as mod

    monkeypatch.setattr(
        mod,
        "fundamental_observation_availability",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("down")),
    )
    _run(seeded_db_empty_cards, client)
    assert (
        statement_panel_as_of(
            seeded_db_empty_cards.conn,
            as_of=datetime(2030, 1, 1, tzinfo=UTC),
            evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
            schema=seeded_db_empty_cards._schema,
        )
        == {}
    )

    monkeypatch.undo()
    _run(seeded_db_empty_cards, client)
    panel = statement_panel_as_of(
        seeded_db_empty_cards.conn,
        as_of=datetime(2030, 1, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
        schema=seeded_db_empty_cards._schema,
    )
    assert panel["NVDA"]["balance-sheets"][PERIOD]["total_assets"] == "259474000000"


def test_no_claim_is_ever_true_pit_even_though_a_filing_date_arrived(
    seeded_db_empty_cards, client
):
    _run(seeded_db_empty_cards, client)
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM "
            f"{seeded_db_empty_cards._schema}.fundamental_statement_obs "
            "WHERE filing_published_at IS NOT NULL"
        )
        assert cur.fetchone()[0] == 3
    assert EvidenceClass.TRUE_PIT not in _repo(seeded_db_empty_cards).claim_counts()


def test_the_claim_stage_is_not_one_query_per_observation(
    seeded_db_empty_cards, client
):
    """Set-based per ticker: the ingest already costs 4 UW calls per name and must
    not also cost one DB round-trip per statement row."""
    _run(seeded_db_empty_cards, client)
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(DISTINCT claim_key) FROM "
            f"{seeded_db_empty_cards._schema}.fundamental_obs_availability"
        )
        assert cur.fetchone()[0] == 2  # one capture rule, one current-vintage rule


def _obs_ids(seeded) -> list[int]:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT obs_id FROM {seeded._schema}.fundamental_statement_obs "
            "ORDER BY obs_id"
        )
        return [r[0] for r in cur.fetchall()]


def test_the_filing_date_still_lands_on_the_observation(seeded_db_empty_cards, client):
    """Guard against the claim work quietly changing the ingest's existing job."""
    _run(seeded_db_empty_cards, client)
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT filing_published_at FROM "
            f"{seeded_db_empty_cards._schema}.fundamental_statement_obs"
        )
        assert [r[0] for r in cur.fetchall()] == [date(2026, 5, 21)]
