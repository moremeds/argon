"""Persistence for UW /greek-exposure daily history. New domain — own file."""

from __future__ import annotations

from collections.abc import Iterable

from psycopg import Connection
from psycopg.types.json import Jsonb


class GreekExposureDailyRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_rows(self, ticker: str, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        params = [
            {
                "ticker": ticker,
                "trade_date": r["trade_date"],
                "call_gex": r.get("call_gex"),
                "put_gex": r.get("put_gex"),
                "call_delta": r.get("call_delta"),
                "put_delta": r.get("put_delta"),
                "payload": Jsonb(r.get("payload") or {}),
            }
            for r in rows
        ]
        sql = """
            INSERT INTO greek_exposure_daily
                (ticker, trade_date, call_gex, put_gex,
                 call_delta, put_delta, payload)
            VALUES
                (%(ticker)s, %(trade_date)s, %(call_gex)s, %(put_gex)s,
                 %(call_delta)s, %(put_delta)s, %(payload)s)
            ON CONFLICT (ticker, trade_date) DO UPDATE SET
                call_gex   = EXCLUDED.call_gex,
                put_gex    = EXCLUDED.put_gex,
                call_delta = EXCLUDED.call_delta,
                put_delta  = EXCLUDED.put_delta,
                payload    = EXCLUDED.payload
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def fetch_history(self, ticker: str, days: int) -> list[dict]:
        """Return up to `days` most-recent rows, ascending by trade_date."""
        sql = """
            SELECT ticker, trade_date,
                   call_gex::float8,   put_gex::float8,
                   call_delta::float8, put_delta::float8,
                   net_gex::float8,    net_dex::float8
              FROM greek_exposure_daily
             WHERE ticker = %s
             ORDER BY trade_date DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows
