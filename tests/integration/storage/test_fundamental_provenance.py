"""Typed provenance (migration 135): enforceable, and honest about legacy rows.

The two tests that carry the milestone are the schema ones. An array of ids can
name an observation that was deleted or never existed, and nothing complains —
which makes the result unfalsifiable rather than merely undocumented. Foreign
keys are the fix, and the DIRECTION of each one is a policy decision:

- `result_id` CASCADEs — provenance for a deleted result is meaningless;
- `obs_id` RESTRICTs — deleting evidence a published result cites must FAIL,
  because otherwise a reproducible result silently becomes unexplainable.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_provenance import (
    ROLE_EXCLUDED,
    ROLE_USED,
    STAGE_FEATURES,
    STAGE_PANEL,
    FundamentalProvenanceRepository,
)
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "total_assets": "259474000000",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "common_stock_shares_outstanding": "24391000000",
}
ENGINE = "fundamentals-v2:testeng1"


def _seed(seeded) -> tuple[int, int]:
    """(obs_id, result_id) for one observation and one score citing it."""
    schema = seeded._schema
    obs = FundamentalObsRepository(seeded.conn, schema=schema)
    payload = normalize(NVDA_BALANCE)
    obs.record_statements(
        [
            {
                "source": "uw",
                "ticker": "NVDA",
                "period_end": date(2026, 4, 30),
                "period_type": "quarterly",
                "statement": "balance",
                "content_hash": content_hash(payload),
                "provider_record_id": None,
                "filing_accession": None,
                "filing_published_at": None,
                "raw_jsonb": payload,
                "field_map_version": FIELD_MAP_VERSION,
            }
        ]
    )
    with seeded.conn.cursor() as cur:
        cur.execute(f"SELECT obs_id FROM {schema}.fundamental_statement_obs")
        obs_id = cur.fetchone()[0]

    scores = FundamentalScoresRepository(seeded.conn, schema=schema)
    scores.register_version(
        engine_version=ENGINE,
        code_version="fundamentals-v2",
        param_hash="0" * 64,
        params={"rev_growth": 1.0},
        note="test",
    )
    row = {
        "ticker": "NVDA",
        "as_of": date(2026, 6, 30),
        "engine_version": ENGINE,
        "inputs_hash": "h1",
        "period_end": date(2026, 4, 30),
        "knowledge_date": date(2026, 6, 1),
        "filing_date_known": True,
        "composite": 1.0,
        "features_present": 1,
        "source_obs_ids": [obs_id],
    }
    scores.insert_scores([row])
    result_id = scores.result_ids([row])[("NVDA", date(2026, 6, 30))]
    return obs_id, result_id


def test_a_result_enumerates_what_it_used_and_what_it_withheld(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    obs_id, result_id = _seed(seeded)
    prov = FundamentalProvenanceRepository(seeded.conn, schema=seeded._schema)

    prov.record(
        [
            {
                "result_id": result_id,
                "obs_id": obs_id,
                "role": ROLE_USED,
                "stage": STAGE_PANEL,
                "detail": {"period": "2026-04-30"},
            },
            {
                "result_id": result_id,
                "obs_id": obs_id,
                "role": ROLE_EXCLUDED,
                "stage": STAGE_FEATURES,
                "detail": {"withheld_fields": ["gross_profit"]},
            },
        ]
    )

    out = prov.for_result(result_id)
    assert out["state"] == "typed"
    assert len(out["used"]) == 1
    # The thing an id array cannot say: it was CONSIDERED and withheld, and here
    # is which check's field did it.
    assert out["excluded"][0]["detail"]["withheld_fields"] == ["gross_profit"]


def test_inventing_an_observation_is_refused_by_the_schema(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    _, result_id = _seed(seeded)
    prov = FundamentalProvenanceRepository(seeded.conn, schema=seeded._schema)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        prov.record(
            [
                {
                    "result_id": result_id,
                    "obs_id": 9_999_999,
                    "role": ROLE_USED,
                    "stage": STAGE_PANEL,
                }
            ]
        )
    seeded.conn.rollback()


def test_deleting_cited_evidence_is_refused_not_cascaded(seeded_db_empty_cards):
    """RESTRICT. A cascade here would silently unexplain a published result."""
    seeded = seeded_db_empty_cards
    obs_id, result_id = _seed(seeded)
    prov = FundamentalProvenanceRepository(seeded.conn, schema=seeded._schema)
    prov.record(
        [
            {
                "result_id": result_id,
                "obs_id": obs_id,
                "role": ROLE_USED,
                "stage": STAGE_PANEL,
            }
        ]
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with seeded.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {seeded._schema}.fundamental_statement_obs "
                f"WHERE obs_id = %s",
                (obs_id,),
            )
    seeded.conn.rollback()


def test_a_legacy_result_reads_as_legacy_not_as_citing_nothing(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    obs_id, result_id = _seed(seeded)
    prov = FundamentalProvenanceRepository(seeded.conn, schema=seeded._schema)

    out = prov.for_result(result_id)

    assert out["state"] == "legacy"
    assert out["used"] == []
    # and the array is surfaced, so a caller can still show SOMETHING
    assert out["legacy_source_obs_ids"] == [obs_id]


def test_recording_the_same_link_twice_is_a_no_op(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    obs_id, result_id = _seed(seeded)
    prov = FundamentalProvenanceRepository(seeded.conn, schema=seeded._schema)
    link = {
        "result_id": result_id,
        "obs_id": obs_id,
        "role": ROLE_USED,
        "stage": STAGE_PANEL,
    }

    assert prov.record([link]) == 1
    assert prov.record([link]) == 0
