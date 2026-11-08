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

    def earliest_daily_ohlc_date(self, ticker: str) -> _date | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT min(date) FROM {self._schema}.daily_ohlc WHERE ticker=%s",
                (ticker,),
            )
            return cur.fetchone()[0]

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

    def get_intraday_quotes(self, tickers: list[str]) -> list[IntradayQuoteRow]:
        """Batch read of the latest WS quote per ticker (regime live compute)."""
        if not tickers:
            return []
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, price, quoted_at, fetched_at, source
                FROM {self._schema}.intraday_quote WHERE ticker = ANY(%s)
                """,
                (tickers,),
            )
            return [IntradayQuoteRow(*row) for row in cur.fetchall()]

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

    def repair_pcr_history_oi(
        self, *, before: _date, max_lag_days: int = 4, apply: bool = False
    ) -> dict[str, int]:
        """Recompute ``pcr_history.pcr_oi`` as put OI / call OI for rows dated
        before ``before``.

        Until 2026-11-08 the scan stored UW's screener ``put_call_ratio`` there,
        which UW defines as put VOLUME / call volume, so every older row holds a
        copy of ``pcr_vol``. The OI comes from ``options_volume_daily``: the
        latest session at or before ``snapshot_date`` within ``max_lag_days``.
        ``snapshot_date`` is the worker's UTC date: it equals the ET session
        for every scheduled scan (04:00-16:30 ET), while an ad hoc rescan
        after ~20:00 ET or on a weekend lands on a non-session date. A row with
        no such session is set NULL, never left holding the volume ratio.
        Idempotent; ``apply=False`` rolls the transaction back.
        """
        if max_lag_days < 0:
            raise ValueError(f"max_lag_days must be >= 0, got {max_lag_days}")
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH src AS (
                  SELECT p.ticker, p.snapshot_date,
                         (SELECT CASE WHEN o.call_open_interest > 0
                                           AND o.put_open_interest IS NOT NULL
                                      THEN round(o.put_open_interest::numeric
                                                 / o.call_open_interest, 4)
                                 END
                          FROM {self._schema}.options_volume_daily o
                          WHERE o.ticker = p.ticker
                            AND o.trade_date <= p.snapshot_date
                            AND o.trade_date >= p.snapshot_date - %(lag)s::int
                          ORDER BY o.trade_date DESC
                          LIMIT 1) AS new_oi
                  FROM {self._schema}.pcr_history p
                  WHERE p.snapshot_date < %(before)s
                ), upd AS (
                  UPDATE {self._schema}.pcr_history p
                  SET pcr_oi = src.new_oi
                  FROM src
                  WHERE p.ticker = src.ticker
                    AND p.snapshot_date = src.snapshot_date
                    AND p.pcr_oi IS DISTINCT FROM src.new_oi
                  RETURNING p.pcr_oi
                )
                SELECT (SELECT count(*) FROM src),
                       (SELECT count(*) FROM src WHERE new_oi IS NOT NULL),
                       (SELECT count(*) FROM upd),
                       (SELECT count(*) FROM upd WHERE pcr_oi IS NULL)
                """,
                {"before": before, "lag": max_lag_days},
            )
            row = cur.fetchone()
        assert row is not None
        if apply:
            self._conn.commit()
        else:
            self._conn.rollback()
        return {
            "rows_in_scope": row[0],
            "rows_with_oi_source": row[1],
            "rows_changed": row[2],
            "rows_set_null": row[3],
        }

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
