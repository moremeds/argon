"""Persistence for Crash Risk Indicator (CRI) snapshots.

New domain — own file rather than extending repository.py.
Append-only; latest-wins on read.
"""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class CriSnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def insert_snapshot(self, *, payload: dict, data_date: date | None = None) -> int:
        sql = """
            INSERT INTO cri_snapshots (data_date, payload)
            VALUES (%s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (data_date, Jsonb(payload)))
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def fetch_latest(self) -> dict | None:
        """Return most-recent payload, or None."""
        sql = """
            SELECT payload, scanned_at
              FROM cri_snapshots
             ORDER BY scanned_at DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at = row
        out = dict(payload or {})
        if scanned_at is not None and not out.get("scan_time"):
            out["scan_time"] = scanned_at.isoformat()
        return out

    def fetch_history(self, *, limit: int = 30) -> list[dict]:
        """Return up to `limit` most-recent rows, ascending by scanned_at.

        Output rows include the indexable scalars (cri_score, cri_level,
        trigger_fired, vix, vvix, cor1m, spx_distance_pct, realized_vol)
        plus scan_time.
        """
        sql = """
            SELECT scanned_at,
                   cri_score::float8,
                   cri_level,
                   trigger_fired,
                   vix::float8,
                   vvix::float8,
                   cor1m::float8,
                   spx_distance_pct::float8,
                   realized_vol::float8
              FROM cri_snapshots
             ORDER BY scanned_at DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        for r in rows:
            if r.get("scanned_at") is not None:
                r["scan_time"] = r["scanned_at"].isoformat()
        return rows
