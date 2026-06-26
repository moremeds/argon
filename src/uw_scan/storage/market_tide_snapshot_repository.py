"""Persistence for market-wide options tide snapshots.

New domain — own file, never extending repository.py. One row per
(session date, 5-min bar). Premium/volume are upserted from UW (idempotent —
re-fetching the same day overwrites the same bars); `spot` is set separately
from the live WS feed and is preserved across UW re-upserts.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from psycopg import Connection


class MarketTideSnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_bars(self, bars: list[dict]) -> int:
        """Upsert premium/volume for each bar. Leaves `spot` untouched on
        conflict so a previously-captured live spot is never clobbered by a
        later full-day re-fetch."""
        if not bars:
            return 0
        sql = """
            INSERT INTO market_tide_snapshots
                (data_date, ts, net_call_premium, net_put_premium, net_volume)
            VALUES (%(data_date)s, %(ts)s, %(net_call_premium)s,
                    %(net_put_premium)s, %(net_volume)s)
            ON CONFLICT (data_date, ts) DO UPDATE
               SET net_call_premium = EXCLUDED.net_call_premium,
                   net_put_premium  = EXCLUDED.net_put_premium,
                   net_volume       = EXCLUDED.net_volume
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, bars)
        self._conn.commit()
        return len(bars)

    def set_spot(
        self,
        *,
        data_date: date,
        ts: datetime,
        spot: Decimal | float,
        spot_ticker: str,
        spot_quoted_at: datetime | None = None,
    ) -> bool:
        """Attach a live spot reading to one already-inserted bar. Returns
        True when a row matched (the bar must already exist)."""
        sql = """
            UPDATE market_tide_snapshots
               SET spot = %s, spot_ticker = %s, spot_quoted_at = %s
             WHERE data_date = %s AND ts = %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (spot, spot_ticker, spot_quoted_at, data_date, ts))
            matched = cur.rowcount
        self._conn.commit()
        return matched > 0

    def fetch_sessions(self, *, sessions: int = 5) -> list[dict]:
        """Last N session-dates of bars, grouped into sessions ASC by date,
        points ASC by ts. Empty list when no rows exist."""
        sql = """
            WITH recent AS (
                SELECT DISTINCT data_date
                  FROM market_tide_snapshots
                 ORDER BY data_date DESC
                 LIMIT %s
            )
            SELECT m.data_date,
                   m.ts,
                   m.net_call_premium::float8 AS net_call_premium,
                   m.net_put_premium::float8  AS net_put_premium,
                   m.net_volume,
                   m.spot::float8             AS spot,
                   m.spot_ticker
              FROM market_tide_snapshots m
              JOIN recent r ON m.data_date = r.data_date
             ORDER BY m.ts ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (sessions,))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        out: dict[date, list[dict]] = {}
        spot_ticker: str | None = None
        for r in rows:
            d = r.pop("data_date")
            spot_ticker = r.get("spot_ticker") or spot_ticker
            out.setdefault(d, []).append(r)
        return [{"date": d, "points": pts} for d, pts in sorted(out.items())]
