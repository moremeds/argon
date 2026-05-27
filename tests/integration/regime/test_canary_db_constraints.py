"""DB CHECK-constraint smoke tests for uw_scan.canary_snapshots.

See plan Task 1 and spec §9. Every pytest.raises(CheckViolation) is followed
by conn.rollback() so the next test starts on a clean transaction.
"""

from __future__ import annotations

import pytest
from psycopg.errors import CheckViolation

pytestmark = pytest.mark.integration


def _insert_minimal(conn, schema: str, **overrides):
    payload = '{"date":"2026-05-26"}'
    row = {
        "data_date": "2026-05-26",
        "composite_version": 1,
        "score_form": "linear",
        "score": 47.3,
        "raw_score": 47.3,
        "band": "WATCH",
        "tactical_score": 12.4,
        "structural_score": 26.9,
        "speed_score": 8,
        "warning_state": "NONE",
        "payload": payload,
        "payload_hash": "abc",
    }
    row.update(overrides)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f"%({k})s" for k in row)
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {schema}.canary_snapshots ({cols}) VALUES ({placeholders})",
            row,
        )


def test_score_above_100_rejected(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    with pytest.raises(CheckViolation):
        _insert_minimal(conn, schema, score=150)
    conn.rollback()


def test_invalid_band_rejected(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    with pytest.raises(CheckViolation):
        _insert_minimal(conn, schema, band="PANIC")
    conn.rollback()


def test_invalid_warning_state_rejected(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    with pytest.raises(CheckViolation):
        _insert_minimal(conn, schema, warning_state="WATCH")
    conn.rollback()


def test_speed_score_other_than_0_8_20_rejected(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    with pytest.raises(CheckViolation):
        _insert_minimal(conn, schema, speed_score=12)
    conn.rollback()


def test_invalid_score_form_rejected(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    with pytest.raises(CheckViolation):
        _insert_minimal(conn, schema, score_form="exponential")
    conn.rollback()


def test_valid_row_accepted(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _insert_minimal(conn, schema)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE data_date='2026-05-26'"
        )
        assert cur.fetchone()[0] == 1
