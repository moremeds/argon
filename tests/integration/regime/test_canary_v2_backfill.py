"""Integration tests for canary v2-A backfill (in-process invocation).

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

import argparse
from datetime import date

import pytest

from scripts.canary_backfill import cmd_backfill
from tests.integration.regime._canary_v2a_fixture import seed_vol_index_full_history
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION

pytestmark = pytest.mark.integration


def _backfill_args(
    *,
    composite_version: int,
    start_date: str | None = None,
    end_date: str | None = None,
    overwrite_on_hash_mismatch: bool = False,
    days: int = 252,
) -> argparse.Namespace:
    return argparse.Namespace(
        composite_version=composite_version,
        start_date=start_date,
        end_date=end_date,
        overwrite_on_hash_mismatch=overwrite_on_hash_mismatch,
        days=days,
    )


def test_v2_backfill_writes_composite_version_2_rows(seeded_db_empty_cards):
    """cmd_backfill with composite_version=2 writes rows tagged composite_version=2."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 12, 30)
    )

    args = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-12-30",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        v2_count = cur.fetchone()[0]
    assert v2_count > 0, "v2 backfill wrote no rows"


def test_v2_backfill_uses_cal_composite_version_not_module_constant(
    seeded_db_empty_cards,
):
    """v2 rows MUST tag composite_version=2 (cal.composite_version, the loaded
    field), NOT the module-level COMPOSITE_VERSION=1 constant. Otherwise v2
    payloads would silently store as version 1. Spec §4 invariant 10."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    assert COMPOSITE_VERSION == 1, "PR 1 must not flip the module constant"
    seed_vol_index_full_history(
        conn, schema=schema, start=date(2018, 1, 1), end=date(2020, 3, 31)
    )

    args = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-03-31",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT composite_version FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 LIMIT 5"
        )
        rows = cur.fetchall()
    assert len(rows) == 5
    for row in rows:
        assert row[0] == 2


def test_v2_backfill_score_form_is_linear(seeded_db_empty_cards):
    """v2 calibration mandates score_form='linear' (form-sweep verdict). Spec §5.4."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=date(2018, 1, 1), end=date(2020, 2, 28)
    )

    args = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT score_form FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2"
        )
        forms = {row[0] for row in cur.fetchall()}
    assert forms == {"linear"}


def test_v2_backfill_is_idempotent_via_payload_hash(seeded_db_empty_cards):
    """Re-running the v2 backfill on the same date range is a no-op.
    Idempotency MUST be via canonical payload-hash compare (not SELECT 1),
    so stale rows from earlier buggy runs surface as RuntimeError.
    Spec §5.8."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=date(2018, 1, 1), end=date(2020, 2, 28)
    )

    args = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        first = cur.fetchone()[0]

    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        second = cur.fetchone()[0]
    assert first == second, "second backfill should be a no-op"


def test_v2_backfill_fails_loud_on_hash_mismatch_unless_overwrite(
    seeded_db_empty_cards,
):
    """If an existing v2 row has a DIFFERENT canonical hash from the freshly
    computed payload, raise unless --overwrite-on-hash-mismatch is passed.

    Simulates "stale row from buggy earlier run" — silent skip would mask
    the bug forever. Spec §5.8."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=date(2018, 1, 1), end=date(2020, 1, 31)
    )

    args = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-01-31",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {schema}.canary_snapshots "
            f"SET payload_hash = 'tampered-stale-hash' "
            f"WHERE composite_version=2 AND data_date = ("
            f"  SELECT data_date FROM {schema}.canary_snapshots "
            f"  WHERE composite_version=2 LIMIT 1"
            f")"
        )
    conn.commit()

    with pytest.raises(RuntimeError, match="hash mismatch"):
        cmd_backfill(conn, schema=schema, args=args)

    args_overwrite = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-01-31",
        overwrite_on_hash_mismatch=True,
    )
    cmd_backfill(conn, schema=schema, args=args_overwrite)


def test_v2_backfill_does_not_affect_v1_rows(seeded_db_empty_cards):
    """v1 rows untouched after v2 backfill. Spec §6 Layer 1."""
    from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=date(2018, 1, 1), end=date(2020, 2, 28)
    )

    args_v1 = _backfill_args(
        composite_version=1,
        start_date="2020-01-02",
        end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args_v1)

    repo = CanarySnapshotRepository(conn, schema=schema)
    v1_latest_before = repo.fetch_latest(composite_version=1)
    assert v1_latest_before is not None

    args_v2 = _backfill_args(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args_v2)

    v1_latest_after = repo.fetch_latest(composite_version=1)
    assert v1_latest_after["data_date"] == v1_latest_before["data_date"]
    assert v1_latest_after["score"] == v1_latest_before["score"]
    assert v1_latest_after["band"] == v1_latest_before["band"]
