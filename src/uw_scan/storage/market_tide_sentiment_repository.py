"""Persistence for EOD market-tide sentiment (one row per session).

New domain — own file, never extending repository.py. Upsert is idempotent so
the nightly job / backfill can re-run safely.
"""

from __future__ import annotations

from datetime import date

from psycopg import Connection

from ..reports.market_tide_sentiment import TideSentiment


class MarketTideSentimentRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert(self, data_date: date, s: TideSentiment) -> None:
        sql = """
            INSERT INTO market_tide_sentiment_daily
                (data_date, state, magnitude, driver, momentum, spread,
                 session_slope, recent_slope, trend_strength, volume_confirms,
                 bars, computed_at)
            VALUES (%(data_date)s, %(state)s, %(magnitude)s, %(driver)s,
                    %(momentum)s, %(spread)s, %(session_slope)s,
                    %(recent_slope)s, %(trend_strength)s, %(volume_confirms)s,
                    %(bars)s, now())
            ON CONFLICT (data_date) DO UPDATE
               SET state = EXCLUDED.state,
                   magnitude = EXCLUDED.magnitude,
                   driver = EXCLUDED.driver,
                   momentum = EXCLUDED.momentum,
                   spread = EXCLUDED.spread,
                   session_slope = EXCLUDED.session_slope,
                   recent_slope = EXCLUDED.recent_slope,
                   trend_strength = EXCLUDED.trend_strength,
                   volume_confirms = EXCLUDED.volume_confirms,
                   bars = EXCLUDED.bars,
                   computed_at = now()
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, {"data_date": data_date, **s.to_dict()})
        self._conn.commit()

    def fetch_history(self, *, days: int = 90) -> list[dict]:
        """Most-recent N sessions ASC by date — for backtest joins."""
        sql = """
            SELECT data_date, state, magnitude, driver, momentum,
                   spread::float8        AS spread,
                   session_slope::float8 AS session_slope,
                   recent_slope::float8  AS recent_slope,
                   trend_strength::float8 AS trend_strength,
                   volume_confirms, bars
              FROM (
                  SELECT * FROM market_tide_sentiment_daily
                   ORDER BY data_date DESC LIMIT %s
              ) t
             ORDER BY data_date ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (days,))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
