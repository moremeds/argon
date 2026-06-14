"""Persistence for Gamma Rotation Gap (GRG) snapshots.

New domain — own file rather than extending repository.py. Append-only;
latest-wins on read. Payloads are self-contained (embed the full 90-session
history), so this repo exposes only insert + fetch_latest.
"""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class GrgSnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def insert_snapshot(
        self, *, payload: dict, data_date: date | None = None, basis: str = "eod"
    ) -> int:
        sql = """
            INSERT INTO grg_snapshots (data_date, payload, basis)
            VALUES (%s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (data_date, Jsonb(payload), basis))
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def fetch_latest(self, *, basis: str = "eod") -> dict | None:
        """Most-recent payload for ``basis`` (full self-contained snapshot)."""
        sql = """
            SELECT payload, scanned_at
              FROM grg_snapshots
             WHERE basis = %s
             ORDER BY scanned_at DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (basis,))
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at = row
        out = dict(payload or {})
        if scanned_at is not None and not out.get("scan_time"):
            out["scan_time"] = scanned_at.isoformat()
        return out
