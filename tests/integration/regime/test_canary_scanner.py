"""Scanner integration tests for the 5% Canary indicator.

Uses the project's real fixture `seeded_db_empty_cards` (defined in
tests/integration/conftest.py). The fixture freshly migrates a scratch DB
and yields a Repository — we read .conn and ._schema for the focused
canary repo.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.cards.canary_calibration import COMPOSITE_VERSION
from uw_scan.scanners.canary import run as canary_run
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository

pytestmark = pytest.mark.integration


def _seed_vol_index_daily(conn, schema: str, days: int = 400):
    """Seed vol_index_daily with constant calm-day values.

    Schema requires (symbol, trade_date, close) at minimum. Other columns
    are nullable per migration 038.
    """
    start = date(2024, 1, 1)
    rows = []
    for i in range(days):
        d = start + timedelta(days=i)
        rows.append((d, "VIX", 18.0))
        rows.append((d, "VVIX", 92.0))
        rows.append((d, "VIX3M", 19.0))
        rows.append((d, "COR1M", 30.0))
        rows.append((d, "SPX", 4000.0 + i * 1.0))
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {schema}.vol_index_daily (trade_date, symbol, close)
            VALUES (%s, %s, %s)
            ON CONFLICT (symbol, trade_date) DO UPDATE SET close = EXCLUDED.close
            """,
            [(d, sym, close) for (d, sym, close) in rows],
        )
    conn.commit()


def test_scanner_persists_snapshot(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    _seed_vol_index_daily(conn, schema, 400)
    row_id = canary_run(conn, schema=schema)
    assert row_id is not None
    repo = CanarySnapshotRepository(conn, schema=schema)
    latest = repo.fetch_latest(composite_version=COMPOSITE_VERSION)
    assert latest is not None
    assert latest["band"] in ("NONE", "WATCH", "BUY", "STRONG_BUY")


def test_scanner_idempotent_no_op_on_replay(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    _seed_vol_index_daily(conn, schema, 400)
    first = canary_run(conn, schema=schema)
    second = canary_run(conn, schema=schema)
    assert first is not None
    assert second is None  # no-op (data_date, composite_version) UNIQUE


def test_scanner_force_recompute_overwrites(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    _seed_vol_index_daily(conn, schema, 400)
    canary_run(conn, schema=schema)
    second = canary_run(conn, schema=schema, force_recompute=True)
    assert second is not None


def test_scanner_skips_when_under_min_aligned(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    _seed_vol_index_daily(conn, schema, 100)  # below MIN_ALIGNED_BARS=350
    assert canary_run(conn, schema=schema) is None
