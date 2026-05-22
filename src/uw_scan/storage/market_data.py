"""Market-data persistence: daily OHLC, intraday quote, PCR history, ETF AUM cache."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg

from .rows import DailyOhlcRow, IntradayQuoteRow, PcrHistoryRow


class _MarketDataMixin:
    _conn: psycopg.Connection
    _schema: str

    # ---- daily_ohlc ----
    def upsert_daily_ohlc(
        self,
        *,
        ticker: str,
        date: _date,
        open: Decimal | None,
        high: Decimal | None,
        low: Decimal | None,
        close: Decimal,
        volume: int | None,
        source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.daily_ohlc
                  (ticker, date, open, high, low, close, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, date) DO UPDATE
                  SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close, volume=EXCLUDED.volume,
                      source=EXCLUDED.source, fetched_at=NOW()
                """,
                (ticker, date, open, high, low, close, volume, source),
            )
        self._conn.commit()

    def list_daily_ohlc(self, ticker: str, *, limit: int = 30) -> list[DailyOhlcRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, date, open, high, low, close, volume, source, fetched_at
                FROM {self._schema}.daily_ohlc
                WHERE ticker=%s
                ORDER BY date DESC
                LIMIT %s
                """,
                (ticker, limit),
            )
            return [DailyOhlcRow(*row) for row in cur.fetchall()]

    # ---- intraday_quote ----
    def upsert_intraday_quote(
        self,
        ticker: str,
        price: Decimal,
        quoted_at: datetime,
        *,
        source: str = "massive.com_intraday",
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.intraday_quote (ticker, price, quoted_at, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price,
                      quoted_at=EXCLUDED.quoted_at,
                      source=EXCLUDED.source,
                      fetched_at=NOW()
                """,
                (ticker, price, quoted_at, source),
            )
        self._conn.commit()

    def bulk_upsert_intraday_quotes(
        self,
        rows: list[tuple[str, Decimal, datetime, str]],
    ) -> None:
        """Batch upsert of (ticker, price, quoted_at, source) rows.

        Does NOT commit — caller controls the transaction so this can be
        wrapped together with bulk_upsert_watchlist_card_spots + heartbeat
        in one atomic batch by the WS writer.
        """
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.intraday_quote (ticker, price, quoted_at, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price,
                      quoted_at=EXCLUDED.quoted_at,
                      source=EXCLUDED.source,
                      fetched_at=NOW()
                """,
                rows,
            )

    def get_intraday_quote(self, ticker: str) -> IntradayQuoteRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, price, quoted_at, fetched_at, source
                FROM {self._schema}.intraday_quote WHERE ticker=%s
                """,
                (ticker,),
            )
            row = cur.fetchone()
            return IntradayQuoteRow(*row) if row else None

    def get_latest_intraday_quote_times(self) -> tuple[datetime, datetime] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(quoted_at), MAX(fetched_at)
                FROM {self._schema}.intraday_quote
                """
            )
            row = cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (row[0], row[1])
        return None

    # ---- pcr_history ----
    def append_pcr_history(
        self,
        ticker: str,
        snapshot_date: _date,
        pcr_oi: Decimal | None,
        pcr_vol: Decimal | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.pcr_history (ticker, snapshot_date, pcr_oi, pcr_vol)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker, snapshot_date) DO UPDATE
                  SET pcr_oi=EXCLUDED.pcr_oi, pcr_vol=EXCLUDED.pcr_vol
                """,
                (ticker, snapshot_date, pcr_oi, pcr_vol),
            )
        self._conn.commit()

    def get_pcr_history_30d_ago(
        self, ticker: str, today: _date
    ) -> PcrHistoryRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, snapshot_date, pcr_oi, pcr_vol
                FROM {self._schema}.pcr_history
                WHERE ticker=%s AND snapshot_date <= %s - INTERVAL '30 days'
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (ticker, today),
            )
            row = cur.fetchone()
            return PcrHistoryRow(*row) if row else None

    def get_pcr_history_row(
        self, ticker: str, snapshot_date: _date
    ) -> PcrHistoryRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, snapshot_date, pcr_oi, pcr_vol
                FROM {self._schema}.pcr_history
                WHERE ticker=%s AND snapshot_date=%s
                """,
                (ticker, snapshot_date),
            )
            row = cur.fetchone()
        return PcrHistoryRow(*row) if row else None

    # ---- etf_aum_cache (A1 review fix: skip per-scan UW round trip) ----
    def get_recent_etf_aum(self, ticker: str, *, max_age: timedelta) -> Decimal | None:
        """Return cached AUM if fetched within max_age, else None.
        None means the caller should fetch fresh (cache miss or stale)."""
        ticker = ticker.upper()  # cache keys are canonical UPPER
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT aum FROM {self._schema}.etf_aum_cache
                WHERE ticker = %s AND fetched_at > NOW() - %s
                """,
                (ticker, max_age),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def upsert_etf_aum(self, ticker: str, aum: Decimal) -> None:
        ticker = ticker.upper()
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.etf_aum_cache (ticker, aum, fetched_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (ticker) DO UPDATE
                  SET aum = EXCLUDED.aum, fetched_at = EXCLUDED.fetched_at
                """,
                (ticker, aum),
            )
        self._conn.commit()
