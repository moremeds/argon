"""Raw volatility history persistence."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import psycopg

from .. import models


def _iv_rank_params(
    ticker: str, rows: Iterable[models.IvRankRow]
) -> list[tuple[Any, ...]]:
    return [
        (ticker, r.date, r.close, r.volatility, r.iv_rank_1y, r.updated_at)
        for r in rows
    ]


def _volatility_stats_params(
    rows: Iterable[models.VolStatsRow],
) -> list[tuple[Any, ...]]:
    return [
        (
            r.ticker,
            r.date,
            r.iv,
            r.iv_low,
            r.iv_high,
            r.iv_rank,
            r.rv,
            r.rv_low,
            r.rv_high,
        )
        for r in rows
    ]


def _realized_vol_params(
    ticker: str, rows: Iterable[models.RealizedVolRow]
) -> list[tuple[Any, ...]]:
    return [
        (
            ticker,
            r.date,
            r.price,
            r.implied_volatility,
            r.realized_volatility,
            r.unshifted_rv_date,
        )
        for r in rows
    ]


def _skew_params(ticker: str, rows: Iterable[models.SkewRow]) -> list[tuple[Any, ...]]:
    return [
        (ticker, r.date, r.delta, r.expiry, r.risk_reversal)
        for r in rows
    ]


class _VolatilityRawMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_iv_rank_rows(self, ticker: str, rows: Iterable[models.IvRankRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.iv_rank_history "
            "(ticker, market_date, close, volatility, iv_rank_1y, updated_at_src) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "close=EXCLUDED.close, volatility=EXCLUDED.volatility, "
            "iv_rank_1y=EXCLUDED.iv_rank_1y, updated_at_src=EXCLUDED.updated_at_src"
        )
        params = _iv_rank_params(ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_volatility_stats_rows(self, rows: Iterable[models.VolStatsRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.volatility_stats_history "
            "(ticker, market_date, iv, iv_low, iv_high, iv_rank, rv, rv_low, rv_high) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "iv=EXCLUDED.iv, iv_low=EXCLUDED.iv_low, iv_high=EXCLUDED.iv_high, "
            "iv_rank=EXCLUDED.iv_rank, rv=EXCLUDED.rv, rv_low=EXCLUDED.rv_low, "
            "rv_high=EXCLUDED.rv_high"
        )
        params = _volatility_stats_params(rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_realized_vol_rows(
        self, ticker: str, rows: Iterable[models.RealizedVolRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.realized_volatility_history "
            "(ticker, market_date, price, implied_volatility, realized_volatility, "
            "unshifted_rv_date) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "price=EXCLUDED.price, implied_volatility=EXCLUDED.implied_volatility, "
            "realized_volatility=EXCLUDED.realized_volatility, "
            "unshifted_rv_date=EXCLUDED.unshifted_rv_date"
        )
        params = _realized_vol_params(ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_skew_rows(self, ticker: str, rows: Iterable[models.SkewRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.risk_reversal_skew_history "
            "(ticker, market_date, delta, expiry, risk_reversal) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, delta, expiry) DO UPDATE SET "
            "risk_reversal=EXCLUDED.risk_reversal"
        )
        params = _skew_params(ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    # ------------------------------------------------------------------
    # Run-keyed inserts
    # ------------------------------------------------------------------
