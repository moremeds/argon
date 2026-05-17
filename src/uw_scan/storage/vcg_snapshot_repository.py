"""Persistence for Volatility-Credit Gap (VCG) snapshots.

New domain — own file, never extending repository.py. Append-only;
latest-wins on read. Mirrors CriSnapshotRepository.
"""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class VcgSnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def insert_snapshot(self, *, payload: dict, data_date: date | None = None) -> int:
        sql = """
            INSERT INTO vcg_snapshots (data_date, payload)
            VALUES (%s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (data_date, Jsonb(payload)))
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def fetch_latest(self, *, proxy: str | None = None) -> dict | None:
        """Return the most recent payload (optionally filtered by proxy).

        ``id DESC`` is the tie-breaker for the rare case where two snapshots
        share a ``scanned_at`` microsecond (manual scan racing the cron tick).
        """
        if proxy is None:
            sql = """
                SELECT payload, scanned_at
                  FROM vcg_snapshots
                 ORDER BY scanned_at DESC, id DESC
                 LIMIT 1
            """
            params: tuple = ()
        else:
            sql = """
                SELECT payload, scanned_at
                  FROM vcg_snapshots
                 WHERE credit_proxy = %s
                 ORDER BY scanned_at DESC, id DESC
                 LIMIT 1
            """
            params = (proxy,)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at = row
        out = dict(payload or {})
        if scanned_at is not None and not out.get("scan_time"):
            out["scan_time"] = scanned_at.isoformat()
        return out

    def fetch_history(self, *, proxy: str | None = None, limit: int = 30) -> list[dict]:
        """Return up to `limit` most-recent rows, ascending by scanned_at.

        Output rows expose the indexable scalars plus scan_time.
        """
        if proxy is None:
            sql = """
                SELECT scanned_at,
                       credit_proxy,
                       vcg_score::float8,
                       vcg_adj::float8,
                       interpretation,
                       regime,
                       tier,
                       ro,
                       edr,
                       bounce,
                       vix::float8,
                       vvix::float8,
                       credit_price::float8,
                       vvix_severity
                  FROM vcg_snapshots
                 ORDER BY scanned_at DESC, id DESC
                 LIMIT %s
            """
            params: tuple = (limit,)
        else:
            sql = """
                SELECT scanned_at,
                       credit_proxy,
                       vcg_score::float8,
                       vcg_adj::float8,
                       interpretation,
                       regime,
                       tier,
                       ro,
                       edr,
                       bounce,
                       vix::float8,
                       vvix::float8,
                       credit_price::float8,
                       vvix_severity
                  FROM vcg_snapshots
                 WHERE credit_proxy = %s
                 ORDER BY scanned_at DESC, id DESC
                 LIMIT %s
            """
            params = (proxy, limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        for r in rows:
            if r.get("scanned_at") is not None:
                r["scan_time"] = r["scanned_at"].isoformat()
        return rows
