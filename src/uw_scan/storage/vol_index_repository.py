"""Persistence for CBOE vol-complex and SPX daily OHLC sourced from the lake.

New domain — kept in its own file rather than extending the 5,000-line
repository.py.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from datetime import date

from psycopg import Connection


def _ratio_zscore(ratios: list[float], window: int = 252) -> float | None:
    """Trailing-window z-score of the LATEST ratio vs the strictly-prior window.

    `ratios` is ascending by date. Mirrors the research trace's strictly-trailing
    convention (docs/research/2026-07-19-dispersion-signals-eval.md): today is
    excluded from the mean/std it is scored against. Needs ≥30 prior points.
    """
    if len(ratios) < 2:
        return None
    latest = ratios[-1]
    prior = ratios[-(window + 1) : -1]  # up to `window` points, excluding latest
    if len(prior) < 30:
        return None
    mean = statistics.fmean(prior)
    sd = statistics.pstdev(prior)
    return (latest - mean) / sd if sd > 0 else None


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

    def fetch_dispersion_context(self) -> dict:
        """Correlation/dispersion context scalars for the CRI view (descriptive).

        Returns COR1M's percentile within full 20yr history, the current
        VIX/COR1M ratio, and its trailing-252 z-score. All-None on an empty DB.
        Read-only. See docs/research/2026-07-19-dispersion-signals-eval.md.
        """
        empty = {
            "as_of": None,
            "cor1m": None,
            "cor1m_percentile": None,
            "vix": None,
            "vix_cor1m_ratio": None,
            "vix_cor1m_ratio_z": None,
            "history_start": None,
            "n_obs": 0,
        }
        with self._conn.cursor() as cur:
            # Aligned VIX+COR1M closes, most-recent 300 sessions (ratio-z window).
            cur.execute(
                """
                SELECT v.trade_date, v.close::float8, c.close::float8
                  FROM vol_index_daily v
                  JOIN vol_index_daily c
                    ON c.symbol = 'COR1M' AND c.trade_date = v.trade_date
                       AND c.close IS NOT NULL AND c.close > 0
                 WHERE v.symbol = 'VIX' AND v.close IS NOT NULL
                 ORDER BY v.trade_date DESC
                 LIMIT 300
                """
            )
            aligned = cur.fetchall()
            if not aligned:
                return empty
            aligned.reverse()  # ascending
            as_of, latest_vix, latest_cor = aligned[-1]
            ratios = [vix / cor for _, vix, cor in aligned]

            # COR1M percentile within FULL history + history span.
            cur.execute(
                """
                SELECT count(*)::int, min(trade_date),
                       avg((close <= %s)::int)::float8
                  FROM vol_index_daily
                 WHERE symbol = 'COR1M' AND close IS NOT NULL
                """,
                (latest_cor,),
            )
            n_obs, hist_start, pct = cur.fetchone()

        return {
            "as_of": as_of,
            "cor1m": latest_cor,
            "cor1m_percentile": pct,
            "vix": latest_vix,
            "vix_cor1m_ratio": latest_vix / latest_cor if latest_cor else None,
            "vix_cor1m_ratio_z": _ratio_zscore(ratios),
            "history_start": hist_start,
            "n_obs": n_obs,
        }

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
