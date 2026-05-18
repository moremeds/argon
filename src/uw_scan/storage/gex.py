"""GEX snapshot compatibility helpers."""

from __future__ import annotations


import psycopg
from psycopg.types.json import Jsonb



class _GexMixin:
    _conn: psycopg.Connection
    _schema: str

    def fetch_latest_gex(self, *, ticker: str = "SPX") -> dict | None:
        """Return the most recent GEX snapshot payload for ``ticker``, or None.

        ``scan_time`` and ``ticker`` are populated from the row when absent
        from the payload so the API response always carries them.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, scanned_at, ticker "
                f"FROM {self._schema}.gex_snapshots "
                f"WHERE ticker = %s ORDER BY scanned_at DESC LIMIT 1",
                (ticker.upper(),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at, row_ticker = row
        out = dict(payload or {})
        if not out.get("scan_time") and scanned_at is not None:
            out["scan_time"] = scanned_at.isoformat()
        out.setdefault("ticker", row_ticker)
        return out

    def fetch_flip_strike_history(self, *, ticker: str, limit: int = 90) -> dict:
        """Return ``{trade_date: gex_flip_strike}`` for the most recent N days.

        Multiple snapshots per day may exist; the latest scan wins (max
        ``scanned_at`` per ``data_date``). Days without a flip strike are
        omitted — UI renders sparse.
        """
        sql = f"""
            SELECT DISTINCT ON (data_date)
                   data_date,
                   level_gex_flip_strike::float8 AS flip
              FROM {self._schema}.gex_snapshots
             WHERE ticker = %s
               AND data_date IS NOT NULL
               AND level_gex_flip_strike IS NOT NULL
             ORDER BY data_date DESC, scanned_at DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), limit))
            return {row[0]: row[1] for row in cur.fetchall()}

    def upsert_gex_snapshot(
        self,
        *,
        ticker: str,
        payload: dict,
        data_date=None,
    ) -> int:
        """Insert a new gex_snapshots row. Returns the inserted row id.

        Each scan appends a row — the table is append-only so we can
        reconstruct history from gex_snapshots later. Latest-wins via
        ``ORDER BY scanned_at DESC LIMIT 1`` in ``fetch_latest_gex``.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._schema}.gex_snapshots "
                "(ticker, data_date, payload) "
                "VALUES (%s, %s, %s) RETURNING id",
                (ticker.upper(), data_date, Jsonb(payload)),
            )
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])
    # ---- Gold (Phase A1) — macro series ----
