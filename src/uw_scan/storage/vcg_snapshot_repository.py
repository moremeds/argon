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

    def insert_snapshot(
        self, *, payload: dict, data_date: date | None = None, basis: str = "eod"
    ) -> int:
        sql = """
            INSERT INTO vcg_snapshots (data_date, payload, basis)
            VALUES (%s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (data_date, Jsonb(payload), basis))
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def fetch_latest(
        self, *, proxy: str | None = None, basis: str = "eod"
    ) -> dict | None:
        """Return the most recent payload for ``basis`` (optionally filtered
        by proxy). 'eod' default keeps the pre-live /api/regime/vcg contract.

        ``id DESC`` is the tie-breaker for the rare case where two snapshots
        share a ``scanned_at`` microsecond (manual scan racing the cron tick).
        """
        if proxy is None:
            sql = """
                SELECT payload, scanned_at
                  FROM vcg_snapshots
                 WHERE basis = %s
                 ORDER BY scanned_at DESC, id DESC
                 LIMIT 1
            """
            params: tuple = (basis,)
        else:
            sql = """
                SELECT payload, scanned_at
                  FROM vcg_snapshots
                 WHERE credit_proxy = %s AND basis = %s
                 ORDER BY scanned_at DESC, id DESC
                 LIMIT 1
            """
            params = (proxy, basis)
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
                 WHERE basis = 'eod'
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
                 WHERE credit_proxy = %s AND basis = 'eod'
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

    # ---- live charting reads (regime tab) ----

    _POINT_COLS = """
                   vcg_score::float8        AS vcg,
                   vcg_adj::float8          AS vcg_adj,
                   residual::float8         AS residual,
                   credit_price::float8     AS credit_price,
                   credit_5d_return::float8 AS credit_5d_return_pct,
                   vix::float8              AS vix,
                   vvix::float8             AS vvix,
                   beta1::float8            AS beta1,
                   beta2::float8            AS beta2
    """

    def fetch_intraday_sessions(
        self, *, proxy: str = "HYG", sessions: int = 5, rth_only: bool = True
    ) -> list[dict]:
        """Last N ET sessions of basis='live' rows, grouped server-side.
        Mirrors CriSnapshotRepository.fetch_intraday_sessions."""
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
                  FROM vcg_snapshots
                 WHERE basis = 'live' AND credit_proxy = %s
                   {rth_filter}
                 ORDER BY et_date DESC
                 LIMIT %s
            )
            SELECT (v.scanned_at AT TIME ZONE 'America/New_York')::date AS et_date,
                   v.scanned_at,
                   {self._POINT_COLS}
              FROM vcg_snapshots v
              JOIN recent_sessions rs
                ON (v.scanned_at AT TIME ZONE 'America/New_York')::date = rs.et_date
             WHERE v.basis = 'live' AND v.credit_proxy = %s
               {rth_filter}
             ORDER BY v.scanned_at ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (proxy, sessions, proxy))
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        out: dict[object, list[dict]] = {}
        for r in rows:
            et_date = r.pop("et_date")
            r["ts"] = r.pop("scanned_at")
            out.setdefault(et_date, []).append(r)
        return [{"et_date": d, "points": pts} for d, pts in sorted(out.items())]

    def fetch_daily_history(self, *, proxy: str = "HYG", days: int = 90) -> list[dict]:
        """Latest basis='eod' row per data_date, ASC, for the daily grid."""
        sql = f"""
            SELECT DISTINCT ON (data_date)
                   data_date AS date,
                   {self._POINT_COLS}
              FROM vcg_snapshots
             WHERE basis = 'eod' AND credit_proxy = %s AND data_date IS NOT NULL
             ORDER BY data_date DESC, scanned_at DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (proxy, days))
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows
