"""Legacy availability classification — what every pre-existing row is worth.

The job walks observations Argon already holds and issues the only two claims
that can be DERIVED from them: a `current_vintage` classification (usable for
today's page, no historical claim) and a `capture_bounded` claim at the row's own
`first_observed_at`.

The test that matters most is the negative one. Every fixture row below carries a
populated `filing_published_at`, and none of them may come out `true_pit`. That
column describes when the ORIGINAL filing for the period was published; a later
content hash is a different artifact and inherits none of its authority.
Promoting on it would reintroduce the exact look-ahead this work removes, wearing
an honest label — and it would look like a coverage WIN while doing so.

Runs against a real database: the classification is an INSERT … SELECT, so a test
that did not exercise SQL would not be testing the thing that ships.
"""

from __future__ import annotations

import os
from datetime import date

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.worker.jobs.fundamental_observation_availability import (
    fundamental_observation_availability,
)

from uw_scan.fundamentals.observation_time import EvidenceClass
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)

PERIOD = date(2020, 3, 31)
BASE = {
    "fiscal_date_ending": "2020-03-31",
    "report_type": "quarterly",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
}


def _row(ticker: str, assets: int) -> dict:
    payload = normalize({**BASE, "ticker": ticker, "total_assets": str(assets)})
    return {
        "source": "uw",
        "ticker": ticker,
        "period_end": PERIOD,
        "period_type": "quarterly",
        "statement": "balance",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        # Present on every row on purpose — see the module docstring.
        "filing_published_at": date(2020, 5, 21),
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


@pytest.fixture
def legacy_rows(seeded_db_empty_cards):
    """Six observations across three tickers, no availability claims."""
    seeded = seeded_db_empty_cards
    repo = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    for ticker in ("AMD", "MSFT", "NVDA"):
        for assets in (1_000, 2_000):
            repo.record_statements([_row(ticker, assets)])
    return seeded


def _counts(seeded) -> dict[EvidenceClass, int]:
    return FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).claim_counts()


def test_every_legacy_row_gets_both_derivable_claims(legacy_rows):
    totals = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )
    assert totals["scanned"] == 6
    assert totals["current_vintage_inserted"] == 6
    assert totals["capture_inserted"] == 6
    assert _counts(legacy_rows) == {
        EvidenceClass.CURRENT_VINTAGE: 6,
        EvidenceClass.CAPTURE_BOUNDED: 6,
    }


def test_no_row_is_promoted_to_true_pit_by_a_filing_date(legacy_rows):
    """Every fixture row has one. None of them may buy version-level authority."""
    fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )
    assert EvidenceClass.TRUE_PIT not in _counts(legacy_rows)


def test_a_capture_claim_lands_on_the_rows_own_capture_time(legacy_rows):
    fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )
    with legacy_rows.conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*)
              FROM {legacy_rows._schema}.fundamental_obs_availability a
              JOIN {legacy_rows._schema}.fundamental_statement_obs o
                ON o.obs_id = a.obs_id
             WHERE a.evidence_class = 'capture_bounded'
               AND a.available_at IS DISTINCT FROM o.first_observed_at
            """
        )
        assert cur.fetchone()[0] == 0


def test_no_observation_is_left_unclaimed(legacy_rows):
    fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )
    repo = FundamentalObsAvailabilityRepository(
        legacy_rows.conn, schema=legacy_rows._schema
    )
    assert repo.unclaimed_observation_count() == 0


def test_a_rerun_writes_zero_duplicates(legacy_rows):
    first = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )
    second = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )
    assert first["capture_inserted"] == 6
    assert second["capture_inserted"] == 0
    assert second["current_vintage_inserted"] == 0
    assert second["already_present"] == 6
    assert _counts(legacy_rows)[EvidenceClass.CAPTURE_BOUNDED] == 6


def test_a_partial_run_resumes_without_reclassifying(legacy_rows):
    """A batch bound is a resume point, not a semantic change."""
    partial = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema, batch_size=2, max_batches=1
    )
    assert partial["scanned"] == 2
    assert partial["capture_inserted"] == 2

    rest = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema, batch_size=2
    )
    assert rest["capture_inserted"] == 4
    assert _counts(legacy_rows) == {
        EvidenceClass.CURRENT_VINTAGE: 6,
        EvidenceClass.CAPTURE_BOUNDED: 6,
    }


def test_scoping_to_tickers_does_not_change_classification(legacy_rows):
    totals = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema, tickers=["NVDA"]
    )
    assert totals["scanned"] == 2
    assert _counts(legacy_rows) == {
        EvidenceClass.CURRENT_VINTAGE: 2,
        EvidenceClass.CAPTURE_BOUNDED: 2,
    }


def test_an_empty_universe_is_nothing_to_do(seeded_db_empty_cards):
    totals = fundamental_observation_availability(
        conn=seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert totals["scanned"] == 0
    assert totals["capture_inserted"] == 0


def test_counters_reconcile_with_what_landed(legacy_rows):
    totals = fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema, batch_size=4
    )
    counts = _counts(legacy_rows)
    assert totals["current_vintage_inserted"] == counts[EvidenceClass.CURRENT_VINTAGE]
    assert totals["capture_inserted"] == counts[EvidenceClass.CAPTURE_BOUNDED]
    assert totals["scanned"] == 6


def test_claims_survive_a_new_connection_and_a_second_run(legacy_rows):
    """Durability, not just return values.

    A repository that ran, logged success and never committed is a failure this
    codebase has actually shipped. Re-reading through a connection that never saw
    the writing transaction is the only check that catches it — and running the
    job again from that connection proves the idempotency claim holds against
    committed state rather than against session-local rows.
    """
    fundamental_observation_availability(
        conn=legacy_rows.conn, schema=legacy_rows._schema
    )

    settings = Settings.from_env().model_copy(
        update={"db_name": os.environ["UW_SCAN_TEST_DB_NAME"]}
    )
    with psycopg.connect(settings.db_dsn()) as fresh:
        repo = FundamentalObsAvailabilityRepository(fresh, schema=legacy_rows._schema)
        assert repo.claim_counts() == {
            EvidenceClass.CURRENT_VINTAGE: 6,
            EvidenceClass.CAPTURE_BOUNDED: 6,
        }
        assert repo.unclaimed_observation_count() == 0

        with fresh.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM "
                f"{legacy_rows._schema}.fundamental_statement_obs"
            )
            observations_before = cur.fetchone()[0]

        second = fundamental_observation_availability(
            conn=fresh, schema=legacy_rows._schema
        )
        assert second["capture_inserted"] == 0
        assert second["current_vintage_inserted"] == 0

        with fresh.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM "
                f"{legacy_rows._schema}.fundamental_statement_obs"
            )
            assert cur.fetchone()[0] == observations_before
        assert repo.claim_counts() == {
            EvidenceClass.CURRENT_VINTAGE: 6,
            EvidenceClass.CAPTURE_BOUNDED: 6,
        }
