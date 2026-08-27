"""SEC publication evidence: the only path that can write a `true_pit` claim.

The negative tests carry the weight. `true_pit` is what a leak-free replay
admits, so a rule that grants it generously launders a restatement as
point-in-time history — and every backtest downstream inherits the leak with no
symptom. Each refusal below is a specific way that could happen.

NVDA figures are real (2026-04-30 quarterly balance sheet, the same fixture
`test_fundamental_obs.py` freezes); the SEC accessions and dates are NVDA's real
filings, fetched 2026-08-24.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from uw_scan.fundamentals.observation_time import EvidenceClass
from uw_scan.fundamentals.publication_evidence import CLAIM_KEY_SEC_PUBLICATION
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.sources.sec_submissions import SecFiling
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository
from uw_scan.worker.jobs.fundamental_publication_evidence import (
    fundamental_publication_evidence,
)

PERIOD = date(2026, 4, 30)

NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "total_assets": "259474000000",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "common_stock_shares_outstanding": "24391000000",
    "inserted_at": "2026-05-21T06:58:08Z",
    "updated_at": "2026-08-11T03:58:32Z",
}

# The real 10-Q for NVDA's April 2026 quarter. Note reportDate 2026-04-26 vs
# Argon's period_end 2026-04-30 — the 52/53-week gap the tolerance exists for.
NVDA_10Q = SecFiling(
    accession="0001045810-26-000052",
    form="10-Q",
    report_date=date(2026, 4, 26),
    filing_date=date(2026, 5, 20),
    is_amendment=False,
)


def _obs_row(raw: dict, *, mutate: dict | None = None) -> dict:
    payload = normalize({**raw, **(mutate or {})})
    return {
        "source": "uw",
        "ticker": "NVDA",
        "period_end": PERIOD,
        "period_type": "quarterly",
        "statement": "balance",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": date(2026, 5, 21),
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _setup(seeded, *, filings, rows=None):
    schema = seeded._schema
    obs = FundamentalObsRepository(seeded.conn, schema=schema)
    obs.seed_universe("ranked", [("NVDA", None, "test")])
    obs.record_statements(rows or [_obs_row(NVDA_BALANCE)])
    if filings:
        SecFilingIndexRepository(seeded.conn, schema=schema).record_filings(
            "0001045810", "NVDA", filings
        )
    return schema


def _claims(seeded, cls: EvidenceClass) -> list[tuple]:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT obs_id, claim_key, available_at, evidence_source, evidence_ref
              FROM {seeded._schema}.fundamental_obs_availability
             WHERE evidence_class = %s
            """,
            (cls.value,),
        )
        return cur.fetchall()


def test_a_clean_period_earns_true_pit_dated_at_the_filing(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    schema = _setup(seeded, filings=[NVDA_10Q])

    out = fundamental_publication_evidence(conn=seeded.conn, schema=schema)

    assert out["matched"] == 1
    assert out["claims_written"] == 1
    rows = _claims(seeded, EvidenceClass.TRUE_PIT)
    assert len(rows) == 1
    _, claim_key, available_at, source, ref = rows[0]
    assert claim_key == CLAIM_KEY_SEC_PUBLICATION
    assert source == "sec_edgar"
    assert ref == "0001045810-26-000052"
    # End of the filing day, not its start: SEC publishes a DATE, and a
    # midnight anchor would claim the content was public before it was filed.
    assert available_at == datetime(2026, 5, 20, 23, 59, 59, 999999, tzinfo=UTC)


def test_an_amendment_blocks_the_claim_entirely(seeded_db_empty_cards):
    """The clause that keeps this honest — UW serves CURRENT data."""
    seeded = seeded_db_empty_cards
    amendment = SecFiling(
        accession="0001045810-26-000099",
        form="10-Q/A",
        report_date=date(2026, 4, 26),
        filing_date=date(2026, 8, 1),
        is_amendment=True,
    )
    schema = _setup(seeded, filings=[NVDA_10Q, amendment])

    out = fundamental_publication_evidence(conn=seeded.conn, schema=schema)

    assert out["amended"] == 1
    assert out["matched"] == 0
    assert _claims(seeded, EvidenceClass.TRUE_PIT) == []


def test_two_content_versions_block_the_claim(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    restated = _obs_row(NVDA_BALANCE, mutate={"total_assets": "259999000000"})
    schema = _setup(
        seeded, filings=[NVDA_10Q], rows=[_obs_row(NVDA_BALANCE), restated]
    )

    out = fundamental_publication_evidence(conn=seeded.conn, schema=schema)

    assert out["multi_version"] == 1
    assert _claims(seeded, EvidenceClass.TRUE_PIT) == []


def test_no_index_row_is_distinct_from_no_filing(seeded_db_empty_cards):
    """Two different problems: run the index refresh, vs the period truly has none."""
    seeded = seeded_db_empty_cards
    schema = _setup(seeded, filings=[])

    out = fundamental_publication_evidence(conn=seeded.conn, schema=schema)

    assert out["no_index"] == 1
    assert out["no_filing"] == 0


def test_a_replay_writes_nothing_and_does_not_duplicate(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    schema = _setup(seeded, filings=[NVDA_10Q])

    first = fundamental_publication_evidence(conn=seeded.conn, schema=schema)
    second = fundamental_publication_evidence(conn=seeded.conn, schema=schema)

    assert first["claims_written"] == 1
    # Resumability: the identity is skipped outright, not re-decided and dropped
    # on the unique constraint.
    assert second["identities"] == 0
    assert second["claims_written"] == 0
    assert len(_claims(seeded, EvidenceClass.TRUE_PIT)) == 1


def test_the_capture_claim_is_untouched_by_a_true_pit_upgrade(seeded_db_empty_cards):
    """Evidence STRENGTHENS; it never overwrites. Both claims must coexist."""
    seeded = seeded_db_empty_cards
    schema = _setup(seeded, filings=[NVDA_10Q])
    avail = FundamentalObsAvailabilityRepository(seeded.conn, schema=schema)
    avail.seed_claims(EvidenceClass.CAPTURE_BOUNDED, tickers=["NVDA"])

    fundamental_publication_evidence(conn=seeded.conn, schema=schema)

    counts = avail.claim_counts()
    assert counts[EvidenceClass.TRUE_PIT] == 1
    assert counts[EvidenceClass.CAPTURE_BOUNDED] == 1
