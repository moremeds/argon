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

        Thin shim over ``fetch_metrics_history`` — kept for the (still-shipped)
        callers that only need the flip strike. New call sites should reach
        for ``fetch_metrics_history`` to get flip + iv30d + vol_pc + bias in
        a single query.
        """
        metrics = self.fetch_metrics_history(ticker=ticker, limit=limit)
        return {d: m["flip"] for d, m in metrics.items() if m.get("flip") is not None}

    def fetch_metrics_history(
        self, *, ticker: str, limit: int = 90
    ) -> dict[object, dict]:
        """Return ``{trade_date: {flip, iv_30d, vol_pc, bias}}`` for the most
        recent N days.

        Multiple snapshots per day may exist; the latest scan wins (max
        ``scanned_at`` per ``data_date``). Days where the column is NULL come
        through as ``None`` so the GEX history table can render ``"---"``
        per cell instead of dropping the whole row.

        ``bias`` is read from ``payload->'bias'->>'direction'`` rather than
        a dedicated column because the snapshot schema kept the bias
        derivation inside the JSON payload (see ``scanners/gex.py``
        ``compute_directional_bias``).
        """
        sql = f"""
            SELECT DISTINCT ON (data_date)
                   data_date,
                   level_gex_flip_strike::float8 AS flip,
                   iv_30d::float8                AS iv_30d,
                   vol_pc::float8                AS vol_pc,
                   payload->'bias'->>'direction' AS bias
              FROM {self._schema}.gex_snapshots
             WHERE ticker = %s
               AND data_date IS NOT NULL
             ORDER BY data_date DESC, scanned_at DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), limit))
            return {
                row[0]: {
                    "flip": row[1],
                    "iv_30d": row[2],
                    "vol_pc": row[3],
                    "bias": row[4],
                }
                for row in cur.fetchall()
            }

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
