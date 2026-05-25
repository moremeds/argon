"""Persistence for CBOE vol-complex and SPX daily OHLC sourced from the lake.

New domain — kept in its own file rather than extending the 5,000-line
repository.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from psycopg import Connection


class VolIndexRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_rows(self, rows: Iterable[dict]) -> int:
        """Insert or update vol_index_daily rows. Returns count."""
        rows = list(rows)
        if not rows:
            return 0
        sql = """
            INSERT INTO vol_index_daily
                (symbol, trade_date, open, high, low, close, adj_close, volume)
            VALUES
                (%(symbol)s, %(trade_date)s, %(open)s, %(high)s, %(low)s,
                 %(close)s, %(adj_close)s, %(volume)s)
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                open      = EXCLUDED.open,
                high      = EXCLUDED.high,
                low       = EXCLUDED.low,
                close     = EXCLUDED.close,
                adj_close = EXCLUDED.adj_close,
                volume    = EXCLUDED.volume
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
        self._conn.commit()
        return len(rows)

    def fetch_history(self, symbol: str, days: int) -> list[dict]:
        """Return up to `days` most-recent rows for symbol, ascending."""
        sql = """
            SELECT symbol, trade_date,
                   open::float8, high::float8, low::float8,
                   close::float8, adj_close::float8, volume
              FROM vol_index_daily
             WHERE symbol = %s
             ORDER BY trade_date DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (symbol, days))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows

    def latest_date_for(self, symbol: str) -> date | None:
        """Return latest trade_date stored, or None."""
        sql = "SELECT MAX(trade_date) FROM vol_index_daily WHERE symbol = %s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def fetch_dates_for(self, symbol: str) -> set[date]:
        """Return the full set of trade_dates stored for `symbol`.

        Used by the gap-aware lake-sync logic to compute `missing = R2 - DB`.
        Single-column index scan; cheap even for VIX (~9k rows → <100 ms).
        """
        sql = "SELECT trade_date FROM vol_index_daily WHERE symbol = %s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            return {r[0] for r in cur.fetchall()}

    def fetch_multi_history(
        self, symbols: Sequence[str], days: int
    ) -> dict[str, list[dict]]:
        """Bulk variant — returns symbol → rows."""
        if not symbols:
            return {}
        sql = """
            SELECT symbol, trade_date, close::float8
              FROM vol_index_daily
             WHERE symbol = ANY(%s)
               AND trade_date >= (CURRENT_DATE - %s::int)
             ORDER BY symbol, trade_date
        """
        out: dict[str, list[dict]] = {s: [] for s in symbols}
        with self._conn.cursor() as cur:
            cur.execute(sql, (list(symbols), days))
            for sym, td, close in cur.fetchall():
                out[sym].append({"trade_date": td, "close": close})
        return out
