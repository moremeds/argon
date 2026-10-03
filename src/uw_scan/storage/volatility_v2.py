"""Volatility Tab v2 persistence helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Any

import psycopg


class _VolatilityV2Mixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_index_ohlc_rows(self, bars: Iterable[Any]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.index_ohlc_daily "
            "(ticker, market_date, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, "
            "volume = EXCLUDED.volume, inserted_at = now()"
        )
        rows = [
            (b.ticker, b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def fetch_index_ohlc_series(
        self,
        ticker: str,
        *,
        start: _date | None = None,
        end: _date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
        if start is not None:
            clauses.append("market_date >= %s")
            params.append(start)
        if end is not None:
            clauses.append("market_date <= %s")
            params.append(end)
        sql = (
            f"SELECT market_date, open, high, low, close, volume "
            f"FROM {self._schema}.index_ohlc_daily "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_iv_smile_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.iv_smile_snapshots "
            "(ticker, market_date, expiry, strike, iv) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, expiry, strike) DO UPDATE SET "
            "iv = EXCLUDED.iv, inserted_at = now()"
        )
        params = [
            (r["ticker"], r["market_date"], r["expiry"], r["strike"], r.get("iv"))
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_iv_smile_latest(self, ticker: str) -> list[dict[str, Any]]:
        """All (expiry, strike, iv) for the latest market_date with smile data."""
        sql = (
            f"WITH latest AS ("
            f"  SELECT max(market_date) AS market_date "
            f"  FROM {self._schema}.iv_smile_snapshots WHERE ticker = %s) "
            f"SELECT s.expiry, s.strike, s.iv, s.market_date "
            f"FROM {self._schema}.iv_smile_snapshots s "
            f"JOIN latest l USING (market_date) "
            f"WHERE s.ticker = %s "
            f"ORDER BY s.expiry ASC, s.strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_vrp_daily_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.vrp_daily "
            "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "iv = EXCLUDED.iv, rv = EXCLUDED.rv, "
            "vrp = EXCLUDED.vrp, vrp_z_20 = EXCLUDED.vrp_z_20, "
            "inserted_at = now()"
        )
        params = [
            (
                r["ticker"],
                r["market_date"],
                r.get("iv"),
                r.get("rv"),
                r.get("vrp"),
                r.get("vrp_z_20"),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_vrp_daily_series(
        self,
        ticker: str,
        *,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, iv, rv, vrp, vrp_z_20 "
            f"FROM {self._schema}.vrp_daily "
            f"WHERE ticker = %s "
            f"ORDER BY market_date DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_stock_analytics_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.stock_analytics_daily "
            "(ticker, market_date, rvol_21, rvol_pctile, "
            "spy_corr_21, iv_of_iv_20) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "rvol_21 = EXCLUDED.rvol_21, rvol_pctile = EXCLUDED.rvol_pctile, "
            "spy_corr_21 = EXCLUDED.spy_corr_21, "
            "iv_of_iv_20 = EXCLUDED.iv_of_iv_20, inserted_at = now()"
        )
        params = [
            (
                r["ticker"],
                r["market_date"],
                r.get("rvol_21"),
                r.get("rvol_pctile"),
                r.get("spy_corr_21"),
                r.get("iv_of_iv_20"),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_stock_analytics_series(
        self,
        ticker: str,
        *,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, rvol_21, rvol_pctile, spy_corr_21, iv_of_iv_20 "
            f"FROM {self._schema}.stock_analytics_daily "
            f"WHERE ticker = %s ORDER BY market_date DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_greeks_rows_for_smile(
        self,
        *,
        ticker: str,
        market_date: _date,
        expiry: _date,
    ) -> list[dict[str, Any]]:
        """Cache-first source for the smile chart from greeks_by_expiry_strike."""
        sql = (
            f"SELECT expiry, strike, call_volatility, put_volatility "
            f"FROM {self._schema}.greeks_by_expiry_strike "
            "WHERE ticker = %s AND market_date = %s AND expiry = %s "
            "ORDER BY strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, expiry))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def count_realized_vol_history(
        self,
        ticker: str,
        *,
        days: int = 365,
    ) -> int:
        sql = (
            f"SELECT count(*) FROM {self._schema}.realized_volatility_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval)"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            return int(cur.fetchone()[0])

    def fetch_realized_vol_history(
        self,
        ticker: str,
        *,
        days: int = 365,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            f"ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_volatility_stats_history(
        self,
        ticker: str,
        *,
        days: int = 365,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, iv, iv_low, iv_high, iv_rank, "
            f"rv, rv_low, rv_high "
            f"FROM {self._schema}.volatility_stats_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            f"ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    # ---- Backfill state machine ----

    def get_volatility_backfill_status(
        self,
        ticker: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT ticker, status, started_at, finished_at, error_message "
            f"FROM {self._schema}.volatility_backfill_status WHERE ticker = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def upsert_volatility_backfill_status(
        self,
        *,
        ticker: str,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.volatility_backfill_status "
            "(ticker, status, started_at, finished_at, error_message) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker) DO UPDATE SET "
            "status = EXCLUDED.status, "
            "started_at = COALESCE(EXCLUDED.started_at, "
            f"  {self._schema}.volatility_backfill_status.started_at), "
            "finished_at = EXCLUDED.finished_at, "
            "error_message = EXCLUDED.error_message"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (ticker, status, started_at, finished_at, error_message),
            )

    # Durable backfill queue (migration 157). The GET enqueues, the uw-0
    # worker's volatility_backfill_tick claims. The ticker PK is the dedup key.

    def enqueue_volatility_backfill(self, ticker: str) -> None:
        """Queue a backfill unless one is already queued or running."""
        sql = (
            f"INSERT INTO {self._schema}.volatility_backfill_status (ticker, status) "
            "VALUES (%s, 'queued') "
            "ON CONFLICT (ticker) DO UPDATE SET status = 'queued', "
            "started_at = NULL, finished_at = NULL, error_message = NULL "
            f"WHERE {self._schema}.volatility_backfill_status.status "
            "NOT IN ('queued', 'running')"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
        self._conn.commit()

    # A claimable row is 'queued', or 'running' with a started_at older than
    # ``stale_after`` (its worker died mid-run). The worker never writes
    # 'queued' -- only the API GET does, and the API self-migrates before it
    # serves -- so a worker on new code is safe against a pre-157 CHECK.
    _CLAIMABLE = (
        "status = 'queued' OR (status = 'running' AND "
        "(started_at IS NULL OR started_at < NOW() - %s))"
    )

    def has_claimable_volatility_backfill(self, stale_after: timedelta) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT EXISTS (SELECT 1 FROM {self._schema}.volatility_backfill_status "
                f"WHERE {self._CLAIMABLE})",
                (stale_after,),
            )
            row = cur.fetchone()
        self._conn.commit()
        return bool(row and row[0])

    def claim_volatility_backfill(self, stale_after: timedelta) -> str | None:
        """Claim one claimable row in a single UPDATE: status stays/becomes
        'running' and started_at is bumped. Stale reclaims go first. SKIP
        LOCKED so concurrent claimers never take the same row."""
        # ponytail: then ordered by ticker, not FIFO -- no requested_at column,
        # and the queue only holds the handful of tickers opened on the page.
        sql = (
            f"UPDATE {self._schema}.volatility_backfill_status "
            "SET status = 'running', started_at = NOW(), finished_at = NULL, "
            "error_message = NULL "
            "WHERE ticker = ("
            f"  SELECT ticker FROM {self._schema}.volatility_backfill_status "
            f"  WHERE {self._CLAIMABLE} "
            "  ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, ticker "
            "  FOR UPDATE SKIP LOCKED LIMIT 1"
            ") RETURNING ticker"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (stale_after,))
            row = cur.fetchone()
        self._conn.commit()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Regime / GEX (ported from xenon 2026-05-16)
    # ------------------------------------------------------------------
