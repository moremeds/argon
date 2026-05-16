"""Backfill flow_footprint_label and aggressor_label_confidence on flow_events
rows where they are currently NULL.

The INSERT path in repository.insert_flow_events already computes these as a
fallback, but rows persisted before the fallback shipped (or before migration
028 added the columns) are still NULL. This script reuses the same helpers
so the backfill is bit-for-bit identical to what new inserts produce.

Idempotent: only touches rows where flow_footprint_label IS NULL.
Run: uv run python scripts/backfill_flow_footprint.py
"""

from __future__ import annotations

import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.storage.repository import (
    _aggressor_label_confidence,
    _flow_footprint_label,
)

logger = logging.getLogger("backfill_flow_footprint")
BATCH = 500


def _row_to_alert(row: dict) -> FlowAlert:
    """Build a FlowAlert from a DB row dict with the minimum fields the
    classifier helpers need."""

    return FlowAlert(
        id=str(row["alert_id"]),
        ticker=row["ticker"],
        total_premium=row["total_premium"],
        total_ask_side_prem=row["total_ask_side_prem"],
        total_bid_side_prem=row["total_bid_side_prem"],
        has_sweep=bool(row["has_sweep"]) if row["has_sweep"] is not None else None,
        has_floor=bool(row["has_floor"]) if row["has_floor"] is not None else None,
        has_multileg=bool(row["has_multileg"])
        if row["has_multileg"] is not None
        else None,
    )


def backfill(conn: psycopg.Connection, *, schema: str) -> tuple[int, int]:
    select_sql = (
        f"SELECT alert_id, ticker, total_premium, total_ask_side_prem, "
        f"total_bid_side_prem, has_sweep, has_floor, has_multileg "
        f"FROM {schema}.flow_events "
        f"WHERE flow_footprint_label IS NULL "
        f"ORDER BY created_at "
        f"LIMIT %s"
    )
    update_sql = (
        f"UPDATE {schema}.flow_events "
        f"SET flow_footprint_label = %s, aggressor_label_confidence = %s "
        f"WHERE alert_id = %s AND flow_footprint_label IS NULL"
    )

    total_scanned = 0
    total_updated = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(select_sql, (BATCH,))
            rows = cur.fetchall()
            if not rows:
                break
            cols = [d.name for d in cur.description or []]
            dict_rows = [dict(zip(cols, r, strict=False)) for r in rows]

        updates = []
        for r in dict_rows:
            alert = _row_to_alert(r)
            label = _flow_footprint_label(alert)
            confidence = _aggressor_label_confidence(alert)
            updates.append((label, confidence, r["alert_id"]))

        with conn.cursor() as cur:
            cur.executemany(update_sql, updates)
            total_updated += (
                cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(updates)
            )
        conn.commit()
        total_scanned += len(rows)
        logger.info("scanned=%d updated=%d", total_scanned, total_updated)
    return total_scanned, total_updated


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    settings = Settings.from_env()
    logger.info(
        "connecting host=%s db=%s schema=%s",
        settings.db_host,
        settings.db_name,
        settings.db_schema,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        scanned, updated = backfill(conn, schema=settings.db_schema)
    logger.info("done: scanned=%d updated=%d", scanned, updated)


if __name__ == "__main__":
    main()
