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

    def insert_snapshot(
        self, *, payload: dict, data_date: date | None = None, basis: str = "eod"
    ) -> int:
        sql = """
            INSERT INTO cri_snapshots (data_date, payload, basis)
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
        """Most-recent payload for ``basis`` ('eod' default keeps the
        pre-live /api/regime contract: full payload with history arrays)."""
        sql = """
            SELECT payload, scanned_at
              FROM cri_snapshots
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
             WHERE basis = 'eod'
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

    # ---- live charting reads (regime tab) ----

    _POINT_COLS = """
                   cri_score::float8        AS cri_score,
                   vix::float8              AS vix,
                   vvix::float8             AS vvix,
                   spx::float8              AS spx,
                   cor1m::float8            AS cor1m,
                   vix3m::float8            AS vix3m,
                   realized_vol::float8     AS realized_vol,
                   vrp::float8              AS vrp,
                   vix_zscore_30d::float8   AS vix_zscore_30d,
                   vix_vix3m_ratio::float8  AS vix_vix3m_ratio,
                   spx_distance_pct::float8 AS spx_distance_pct
    """

    def fetch_intraday_sessions(
        self, *, sessions: int = 5, rth_only: bool = True
    ) -> list[dict]:
        """Last N ET sessions of basis='live' rows, grouped server-side.
        Mirrors _GexMixin.fetch_intraday_sessions (storage/gex.py)."""
        rth_filter = (
            "AND (scanned_at AT TIME ZONE 'America/New_York')::time "
            "BETWEEN '09:30' AND '16:00'"
            if rth_only
            else ""
        )
        sql = f"""
            WITH recent_sessions AS (
                SELECT DISTINCT
                       (scanned_at AT TIME ZONE 'America/New_York')::date AS et_date
                  FROM cri_snapshots
                 WHERE basis = 'live'
                   {rth_filter}
                 ORDER BY et_date DESC
                 LIMIT %s
            )
            SELECT (c.scanned_at AT TIME ZONE 'America/New_York')::date AS et_date,
                   c.scanned_at,
                   {self._POINT_COLS}
              FROM cri_snapshots c
              JOIN recent_sessions rs
                ON (c.scanned_at AT TIME ZONE 'America/New_York')::date = rs.et_date
             WHERE c.basis = 'live'
               {rth_filter}
             ORDER BY c.scanned_at ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (sessions,))
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        out: dict[object, list[dict]] = {}
        for r in rows:
            et_date = r.pop("et_date")
            r["ts"] = r.pop("scanned_at")
            out.setdefault(et_date, []).append(r)
        return [{"et_date": d, "points": pts} for d, pts in sorted(out.items())]

    def fetch_daily_history(self, *, days: int = 90) -> list[dict]:
        """Latest basis='eod' row per data_date, ASC, for the daily grid."""
        sql = f"""
            SELECT DISTINCT ON (data_date)
                   data_date AS date,
                   {self._POINT_COLS}
              FROM cri_snapshots
             WHERE basis = 'eod' AND data_date IS NOT NULL
             ORDER BY data_date DESC, scanned_at DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (days,))
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows
