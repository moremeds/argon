"""Persistence layer: thin wrapper around psycopg cursors.

One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .. import models


@dataclass(frozen=True)
class WatchlistRow:
    ticker: str
    sector: str
    notes: str | None
    pinned: bool
    sort_rank: int
    added_at: datetime
    removed_at: datetime | None


@dataclass(frozen=True)
class DailyOhlcRow:
    ticker: str
    date: _date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class IntradayQuoteRow:
    ticker: str
    price: Decimal
    quoted_at: datetime
    fetched_at: datetime


@dataclass(frozen=True)
class PcrHistoryRow:
    ticker: str
    snapshot_date: _date
    pcr_oi: Decimal | None
    pcr_vol: Decimal | None


@dataclass(frozen=True)
class JobRow:
    id: Any
    ticker: str
    status: str
    run_id: int | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WatchlistCardRow:
    """Variable-shaped: 25+ fields, many nullable. Wraps a dict for forward-compat
    when the card schema grows. Use .from_db(row, cursor.description) to construct."""

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str):
        try:
            data = object.__getattribute__(self, "_data")
        except AttributeError as e:
            raise AttributeError(name) from e
        if name in data:
            return data[name]
        raise AttributeError(name)

    @classmethod
    def from_db(cls, row: tuple, description) -> "WatchlistCardRow":
        return cls({col.name: val for col, val in zip(description, row, strict=False)})

    def to_dict(self) -> dict:
        return dict(self._data)


logger = logging.getLogger(__name__)


def _d(value: Decimal | None) -> Any:
    """psycopg handles Decimal natively; keep this for symmetry with other casters."""
    return value


class Repository:
    """Repository wraps a psycopg connection and exposes typed CRUD."""

    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    @property
    def conn(self) -> psycopg.Connection:
        return self._conn

    # ------------------------------------------------------------------
    # scan_runs
    # ------------------------------------------------------------------
    def latest_run_id(self, ticker: str) -> int:
        """Return the highest full-scan run_id for `ticker`, or 0 if none.

        Excludes runs created by ``flow_data_refresh`` — that job populates
        ticker-keyed tables only (options_volume_daily, option_chain_per_strike)
        and its scan_runs row would otherwise shadow the actual full-scan run
        the report assembler needs for flow_alerts / oi_change_top / GEX /
        volatility data, which are all keyed by run_id.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT run_id FROM {self._schema}.scan_runs "
                "WHERE ticker = %s "
                "  AND (notes IS DISTINCT FROM 'flow_data_refresh') "
                "ORDER BY run_id DESC LIMIT 1",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def insert_scan_run(self, ticker: str, notes: str = "") -> int:
        sql = (
            f"INSERT INTO {self._schema}.scan_runs (ticker, notes) "
            "VALUES (%s, %s) RETURNING run_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), notes))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def finish_scan_run(self, run_id: int, status: str = "ok") -> None:
        sql = (
            f"UPDATE {self._schema}.scan_runs "
            "SET finished_at = now(), status = %s WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (status, run_id))

    # ------------------------------------------------------------------
    # advisory locks (single-flight worker jobs)
    # ------------------------------------------------------------------
    def try_advisory_lock(self, key: int) -> bool:
        """Session-scoped ``pg_try_advisory_lock``; returns True if acquired.

        Mirror the precedent in ``api/routers/volatility.py``. Always pair with
        :meth:`release_advisory_lock` in a ``finally`` block.
        """

        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = cur.fetchone()
            return bool(row and row[0])

    def release_advisory_lock(self, key: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))

    # ------------------------------------------------------------------
    # api_request_audit + raw_payloads
    # ------------------------------------------------------------------
    def insert_audit_row(
        self,
        run_id: int,
        endpoint_slug: str,
        endpoint_path: str,
        params: dict[str, Any],
        status_code: int,
        started_at: datetime,
        finished_at: datetime,
        daily_req_count: int | None,
        minute_req_remaining: int | None,
        minute_req_reset: str | None,
        error_message: str | None = None,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.api_request_audit ("
            "run_id, endpoint_slug, endpoint_path, params_json, status_code, "
            "request_started_at, request_finished_at, daily_req_count, "
            "minute_req_remaining, minute_req_reset, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING audit_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    endpoint_slug,
                    endpoint_path,
                    Jsonb(params),
                    status_code,
                    started_at,
                    finished_at,
                    daily_req_count,
                    minute_req_remaining,
                    minute_req_reset,
                    error_message,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def insert_raw_payload(self, audit_id: int, payload: dict | list) -> int:
        sql = (
            f"INSERT INTO {self._schema}.raw_payloads (audit_id, payload_jsonb) "
            "VALUES (%s, %s) RETURNING payload_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (audit_id, Jsonb(payload)))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    # ------------------------------------------------------------------
    # flow_events
    # ------------------------------------------------------------------
    def insert_flow_events(
        self, run_id: int, ticker: str, alerts: Iterable[models.FlowAlert]
    ) -> int:
        rows = list(alerts)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.flow_events ("
            "run_id, alert_id, ticker, option_chain, expiry, strike, option_type, "
            "price, underlying_price, total_size, total_premium, "
            "total_ask_side_prem, total_bid_side_prem, volume, open_interest, "
            "volume_oi_ratio, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, iv_start, iv_end, alert_rule, rule_id, sector, "
            "issue_type, next_earnings_date, created_at) VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, alert_id) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.id,
                        r.ticker,
                        r.option_chain,
                        r.expiry,
                        r.strike,
                        r.type,
                        r.price,
                        r.underlying_price,
                        r.total_size,
                        r.total_premium,
                        r.total_ask_side_prem,
                        r.total_bid_side_prem,
                        r.volume,
                        r.open_interest,
                        r.volume_oi_ratio,
                        r.has_sweep,
                        r.has_floor,
                        r.has_multileg,
                        r.all_opening_trades,
                        r.iv_start,
                        r.iv_end,
                        r.alert_rule,
                        r.rule_id,
                        r.sector,
                        r.issue_type,
                        r.next_earnings_date,
                        r.created_at,
                    ),
                )
        return len(rows)

    # ------------------------------------------------------------------
    # Time-series history (UPSERT by (ticker, market_date))
    # ------------------------------------------------------------------
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
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (ticker, r.date, r.close, r.volatility, r.iv_rank_1y, r.updated_at),
                )
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
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
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
                    ),
                )
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
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker,
                        r.date,
                        r.price,
                        r.implied_volatility,
                        r.realized_volatility,
                        r.unshifted_rv_date,
                    ),
                )
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
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (ticker, r.date, r.delta, r.expiry, r.risk_reversal),
                )
        return len(rows)

    # ------------------------------------------------------------------
    # Run-keyed inserts
    # ------------------------------------------------------------------
    def insert_iv_term_rows(
        self, run_id: int, rows: Iterable[models.TermStructureRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.iv_term_snapshots "
            "(run_id, ticker, market_date, expiry, dte, volatility, "
            "implied_move, implied_move_perc) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.ticker,
                        r.date,
                        r.expiry,
                        r.dte,
                        r.volatility,
                        r.implied_move,
                        r.implied_move_perc,
                    ),
                )
        return len(rows)

    def insert_interpolated_iv_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.InterpolatedIvRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.interpolated_iv_snapshots "
            "(run_id, ticker, market_date, days, percentile, volatility, implied_move_perc) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, days) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.date,
                        r.days,
                        r.percentile,
                        r.volatility,
                        r.implied_move_perc,
                    ),
                )
        return len(rows)

    def insert_greek_exposure_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.GreekExposureRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.exposures_by_expiry_strike "
            "(run_id, ticker, market_date, expiry, strike, dte, "
            "call_delta, put_delta, call_gex, put_gex, call_vanna, put_vanna, "
            "call_charm, put_charm) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry, strike) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.date,
                        r.expiry,
                        r.strike,
                        r.dte,
                        r.call_delta,
                        r.put_delta,
                        r.call_gex,
                        r.put_gex,
                        r.call_vanna,
                        r.put_vanna,
                        r.call_charm,
                        r.put_charm,
                    ),
                )
        return len(rows)

    def insert_greeks_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.GreeksRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.greeks_by_expiry_strike "
            "(run_id, ticker, market_date, expiry, strike, "
            "call_delta, put_delta, call_gamma, put_gamma, call_vega, put_vega, "
            "call_theta, put_theta, call_rho, put_rho, "
            "call_vanna, put_vanna, call_charm, put_charm, "
            "call_volatility, put_volatility, "
            "call_option_symbol, put_option_symbol) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry, strike) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.date,
                        r.expiry,
                        r.strike,
                        r.call_delta,
                        r.put_delta,
                        r.call_gamma,
                        r.put_gamma,
                        r.call_vega,
                        r.put_vega,
                        r.call_theta,
                        r.put_theta,
                        r.call_rho,
                        r.put_rho,
                        r.call_vanna,
                        r.put_vanna,
                        r.call_charm,
                        r.put_charm,
                        r.call_volatility,
                        r.put_volatility,
                        r.call_option_symbol,
                        r.put_option_symbol,
                    ),
                )
        return len(rows)

    def upsert_oi_per_strike_rows(
        self, ticker: str, rows: Iterable[models.OiPerStrikeRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.oi_by_strike "
            "(ticker, market_date, strike, call_oi, put_oi) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, strike) DO UPDATE SET "
            "call_oi=EXCLUDED.call_oi, put_oi=EXCLUDED.put_oi"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (ticker, r.date, r.strike, r.call_oi, r.put_oi),
                )
        return len(rows)

    def upsert_options_volume_daily(
        self, ticker: str, rows: Iterable[models.OptionsDailyRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.options_volume_daily "
            "(ticker, trade_date, call_volume, put_volume, "
            " call_volume_ask_side, call_volume_bid_side, "
            " put_volume_ask_side, put_volume_bid_side, "
            " call_premium, put_premium, net_call_premium, net_put_premium, "
            " bullish_premium, bearish_premium, "
            " call_open_interest, put_open_interest, "
            " avg_3_day_call_volume, avg_3_day_put_volume, "
            " avg_7_day_call_volume, avg_7_day_put_volume, "
            " avg_30_day_call_volume, avg_30_day_put_volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, trade_date) DO UPDATE SET "
            "call_volume=EXCLUDED.call_volume, put_volume=EXCLUDED.put_volume, "
            "call_volume_ask_side=EXCLUDED.call_volume_ask_side, "
            "call_volume_bid_side=EXCLUDED.call_volume_bid_side, "
            "put_volume_ask_side=EXCLUDED.put_volume_ask_side, "
            "put_volume_bid_side=EXCLUDED.put_volume_bid_side, "
            "call_premium=EXCLUDED.call_premium, put_premium=EXCLUDED.put_premium, "
            "net_call_premium=EXCLUDED.net_call_premium, "
            "net_put_premium=EXCLUDED.net_put_premium, "
            "bullish_premium=EXCLUDED.bullish_premium, "
            "bearish_premium=EXCLUDED.bearish_premium, "
            "call_open_interest=EXCLUDED.call_open_interest, "
            "put_open_interest=EXCLUDED.put_open_interest, "
            "avg_3_day_call_volume=EXCLUDED.avg_3_day_call_volume, "
            "avg_3_day_put_volume=EXCLUDED.avg_3_day_put_volume, "
            "avg_7_day_call_volume=EXCLUDED.avg_7_day_call_volume, "
            "avg_7_day_put_volume=EXCLUDED.avg_7_day_put_volume, "
            "avg_30_day_call_volume=EXCLUDED.avg_30_day_call_volume, "
            "avg_30_day_put_volume=EXCLUDED.avg_30_day_put_volume"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker,
                        r.date,
                        r.call_volume,
                        r.put_volume,
                        r.call_volume_ask_side,
                        r.call_volume_bid_side,
                        r.put_volume_ask_side,
                        r.put_volume_bid_side,
                        r.call_premium,
                        r.put_premium,
                        r.net_call_premium,
                        r.net_put_premium,
                        r.bullish_premium,
                        r.bearish_premium,
                        r.call_open_interest,
                        r.put_open_interest,
                        r.avg_3_day_call_volume,
                        r.avg_3_day_put_volume,
                        r.avg_7_day_call_volume,
                        r.avg_7_day_put_volume,
                        r.avg_30_day_call_volume,
                        r.avg_30_day_put_volume,
                    ),
                )
        return len(rows)

    def upsert_option_chain_per_strike(
        self,
        ticker: str,
        snapshot_date: _date,
        rows: Iterable[models.OptionChainPerStrikeRow],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.option_chain_per_strike "
            "(ticker, snapshot_date, expiry, strike, "
            " call_volume, put_volume, call_oi, put_oi) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, snapshot_date, expiry, strike) DO UPDATE SET "
            "call_volume=EXCLUDED.call_volume, put_volume=EXCLUDED.put_volume, "
            "call_oi=EXCLUDED.call_oi, put_oi=EXCLUDED.put_oi"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker,
                        snapshot_date,
                        r.expiry,
                        r.strike,
                        r.call_volume,
                        r.put_volume,
                        r.call_oi,
                        r.put_oi,
                    ),
                )
        return len(rows)

    def delete_option_chain_per_strike(self, ticker: str, snapshot_date: _date) -> int:
        """Delete same-day rows before re-upserting a refreshed snapshot.

        Without this, a shrinking chain (fewer active strikes than last run)
        would leave stale rows in place since UPSERT only touches the keys
        present in the new batch.
        """

        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.option_chain_per_strike "
                f"WHERE ticker = %s AND snapshot_date = %s",
                (ticker, snapshot_date),
            )
            return cur.rowcount or 0

    def get_options_timeline(
        self, ticker: str, lookback_days: int = 180
    ) -> list[models.OptionsDailyRow]:
        sql = (
            f"SELECT trade_date AS date, call_volume, put_volume, "
            f"call_volume_ask_side, call_volume_bid_side, "
            f"put_volume_ask_side, put_volume_bid_side, "
            f"call_premium, put_premium, net_call_premium, net_put_premium, "
            f"bullish_premium, bearish_premium, "
            f"call_open_interest, put_open_interest, "
            f"avg_3_day_call_volume, avg_3_day_put_volume, "
            f"avg_7_day_call_volume, avg_7_day_put_volume, "
            f"avg_30_day_call_volume, avg_30_day_put_volume "
            f"FROM {self._schema}.options_volume_daily "
            f"WHERE ticker = %s AND trade_date >= (CURRENT_DATE - %s::int) "
            f"ORDER BY trade_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, lookback_days))
            cols = [c.name for c in cur.description]
            return [
                models.OptionsDailyRow(**dict(zip(cols, row, strict=True)))
                for row in cur.fetchall()
            ]

    def get_option_chain_per_strike(
        self, ticker: str
    ) -> list[models.OptionChainPerStrikeRow]:
        sql = (
            f"SELECT expiry, strike, call_volume, put_volume, call_oi, put_oi "
            f"FROM {self._schema}.option_chain_per_strike "
            f"WHERE ticker = %s AND snapshot_date = ("
            f"  SELECT MAX(snapshot_date) FROM {self._schema}.option_chain_per_strike "
            f"  WHERE ticker = %s) "
            f"ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            cols = [c.name for c in cur.description]
            return [
                models.OptionChainPerStrikeRow(**dict(zip(cols, row, strict=True)))
                for row in cur.fetchall()
            ]

    def insert_oi_change_rows(
        self, run_id: int, rows: Iterable[models.OiChangeRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.oi_change_events "
            "(run_id, underlying_symbol, option_symbol, curr_date, last_date, "
            " curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            " avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            " percentage_of_total, rnk, "
            " prev_ask_volume, prev_bid_volume, prev_mid_volume, prev_neutral_volume, "
            " prev_multi_leg_volume, prev_stock_multi_leg_volume, "
            " prev_total_premium, last_ask, last_bid) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, option_symbol) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.underlying_symbol,
                        r.option_symbol,
                        r.curr_date,
                        r.last_date,
                        r.curr_oi,
                        r.last_oi,
                        r.oi_diff_plain,
                        r.oi_change,
                        r.volume,
                        r.trades,
                        r.avg_price,
                        r.last_fill,
                        r.days_of_oi_increases,
                        r.days_of_vol_greater_than_oi,
                        r.percentage_of_total,
                        r.rnk,
                        r.prev_ask_volume,
                        r.prev_bid_volume,
                        r.prev_mid_volume,
                        r.prev_neutral_volume,
                        r.prev_multi_leg_volume,
                        r.prev_stock_multi_leg_volume,
                        r.prev_total_premium,
                        r.last_ask,
                        r.last_bid,
                    ),
                )
        return len(rows)

    def insert_max_pain_rows(
        self,
        run_id: int,
        ticker: str,
        market_date: Any,
        rows: Iterable[models.MaxPainRow],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.max_pain_by_expiry "
            "(run_id, ticker, market_date, expiry, max_pain, close, open, "
            "next_upper_strike, next_lower_strike) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        market_date,
                        r.expiry,
                        r.max_pain,
                        r.close,
                        r.open,
                        r.next_upper_strike,
                        r.next_lower_strike,
                    ),
                )
        return len(rows)

    def insert_option_contract_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.OptionContractRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.option_contract_snapshots "
            "(run_id, ticker, option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, prev_oi, volume, ask_volume, "
            "bid_volume, mid_volume, multi_leg_volume, stock_multi_leg_volume, "
            "floor_volume, sweep_volume, no_side_volume, "
            "avg_price, high_price, low_price, total_premium) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, option_symbol) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.option_symbol,
                        r.last_price,
                        r.nbbo_bid,
                        r.nbbo_ask,
                        r.implied_volatility,
                        r.open_interest,
                        r.prev_oi,
                        r.volume,
                        r.ask_volume,
                        r.bid_volume,
                        r.mid_volume,
                        r.multi_leg_volume,
                        r.stock_multi_leg_volume,
                        r.floor_volume,
                        r.sweep_volume,
                        r.no_side_volume,
                        r.avg_price,
                        r.high_price,
                        r.low_price,
                        r.total_premium,
                    ),
                )
        return len(rows)

    def insert_dark_pool_rows(
        self, run_id: int, rows: Iterable[models.DarkPoolPrint]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.dark_pool_events "
            "(run_id, ticker, tracking_id, executed_at, trf_executed_at, "
            "price, size, premium, nbbo_bid, nbbo_ask, "
            "nbbo_bid_quantity, nbbo_ask_quantity, market_center, "
            "sale_cond_codes, ext_hour_sold_codes, trade_code, trade_settlement, "
            "canceled) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, tracking_id) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.ticker,
                        r.tracking_id,
                        r.executed_at,
                        r.trf_executed_at,
                        r.price,
                        r.size,
                        r.premium,
                        r.nbbo_bid,
                        r.nbbo_ask,
                        r.nbbo_bid_quantity,
                        r.nbbo_ask_quantity,
                        r.market_center,
                        r.sale_cond_codes,
                        r.ext_hour_sold_codes,
                        r.trade_code,
                        r.trade_settlement,
                        r.canceled,
                    ),
                )
        return len(rows)

    def insert_short_interest_snapshot(
        self, run_id: int, row: models.ShortDataRow
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.short_interest_snapshots "
            "(run_id, ticker, name, snapshot_at, short_shares_available, "
            "fee_rate, rebate_rate) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "snapshot_at=EXCLUDED.snapshot_at, "
            "short_shares_available=EXCLUDED.short_shares_available, "
            "fee_rate=EXCLUDED.fee_rate, rebate_rate=EXCLUDED.rebate_rate"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    row.symbol,
                    row.name,
                    row.timestamp,
                    row.short_shares_available,
                    row.fee_rate,
                    row.rebate_rate,
                ),
            )
        return 1

    # ------------------------------------------------------------------
    # opportunity_scores + structure_ideas
    # ------------------------------------------------------------------
    def insert_opportunity_score(
        self,
        run_id: int,
        ticker: str,
        score: Decimal,
        setup_types: list[str],
        direction: str | None,
        confirmations: list[str],
        warnings: list[str],
        notes: str,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.opportunity_scores "
            "(run_id, ticker, score, setup_types, direction, confirmations, "
            "warnings, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING score_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker,
                    score,
                    setup_types,
                    direction,
                    confirmations,
                    warnings,
                    notes,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def insert_structure_idea(
        self,
        run_id: int,
        ticker: str,
        structure: str,
        legs: list[dict[str, Any]],
        rationale: str,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.structure_ideas "
            "(run_id, ticker, structure, legs_json, rationale) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING idea_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (run_id, ticker, structure, Jsonb(legs), rationale),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    # ------------------------------------------------------------------
    # SELECT helpers — used by reports/single_stock.py
    # ------------------------------------------------------------------
    def fetch_flow_alerts_for_ticker(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT alert_id, ticker, option_chain, expiry, strike, option_type, "
            "price, underlying_price, total_size, total_premium, "
            "total_ask_side_prem, total_bid_side_prem, volume, open_interest, "
            "volume_oi_ratio, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, iv_start, iv_end, alert_rule, rule_id, sector, "
            "issue_type, next_earnings_date, created_at "
            f"FROM {self._schema}.flow_events "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper()))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_iv_rank_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, close, volatility, iv_rank_1y, updated_at_src "
            f"FROM {self._schema}.iv_rank_history "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_volatility_stats_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, iv, iv_low, iv_high, iv_rank, rv, rv_low, rv_high "
            f"FROM {self._schema}.volatility_stats_history "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_realized_vol_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_iv_term_rows(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, dte, volatility, implied_move, implied_move_perc "
            f"FROM {self._schema}.iv_term_snapshots "
            "WHERE run_id = %s AND ticker = %s ORDER BY expiry"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_interpolated_iv_30d(
        self, run_id: int, ticker: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT days, percentile, volatility, implied_move_perc "
            f"FROM {self._schema}.interpolated_iv_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY ABS(days - 30) ASC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_skew_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, delta, expiry, risk_reversal "
            f"FROM {self._schema}.risk_reversal_skew_history "
            "WHERE ticker = %s AND delta = 25 "
            "ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_exposures_summary(
        self, run_id: int, ticker: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT "
            "SUM(call_gex) AS total_call_gex, "
            "SUM(put_gex) AS total_put_gex, "
            "SUM(call_delta) AS total_call_dex, "
            "SUM(put_delta) AS total_put_dex "
            f"FROM {self._schema}.exposures_by_expiry_strike "
            "WHERE run_id = %s AND ticker = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_top_oi_strikes(
        self, ticker: str, limit: int = 5
    ) -> tuple[list[Decimal], list[Decimal]]:
        sql = (
            f"SELECT strike, call_oi, put_oi FROM {self._schema}.oi_by_strike "
            "WHERE ticker = %s AND market_date = "
            f"(SELECT MAX(market_date) FROM {self._schema}.oi_by_strike WHERE ticker = %s)"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            rows = cur.fetchall()
        calls = sorted(
            [r for r in rows if r[1] is not None],
            key=lambda r: r[1],
            reverse=True,
        )[:limit]
        puts = sorted(
            [r for r in rows if r[2] is not None],
            key=lambda r: r[2],
            reverse=True,
        )[:limit]
        return [Decimal(str(r[0])) for r in calls], [Decimal(str(r[0])) for r in puts]

    def fetch_oi_change_top(self, run_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Return a candidate set wider than the UI's top-N so the frontend
        can re-sort by notional (volume * avg_price * 100) without losing
        high-notional rows that sit outside the rank-ordered first 10."""

        sql = (
            f"SELECT underlying_symbol, option_symbol, curr_date, last_date, "
            "curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            "avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            "percentage_of_total, rnk, "
            "prev_ask_volume, prev_bid_volume, prev_mid_volume, prev_neutral_volume, "
            "prev_multi_leg_volume, prev_stock_multi_leg_volume, "
            "prev_total_premium, last_ask, last_bid "
            f"FROM {self._schema}.oi_change_events "
            "WHERE run_id = %s "
            "ORDER BY (COALESCE(volume, 0) * COALESCE(avg_price, 0)) DESC NULLS LAST, rnk ASC "
            "LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_max_pain_rows(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, max_pain, close, open, next_upper_strike, next_lower_strike "
            f"FROM {self._schema}.max_pain_by_expiry "
            "WHERE run_id = %s AND ticker = %s ORDER BY expiry"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_option_contracts(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, volume, total_premium "
            f"FROM {self._schema}.option_contract_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_dark_pool_summary(self, run_id: int) -> tuple[int, Decimal]:
        sql = (
            f"SELECT COUNT(*), COALESCE(SUM(premium), 0) "
            f"FROM {self._schema}.dark_pool_events WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
        assert row is not None
        return int(row[0]), Decimal(str(row[1] or 0))

    def fetch_short_interest_snapshot(self, run_id: int) -> dict[str, Any] | None:
        sql = (
            f"SELECT ticker, name, snapshot_at, short_shares_available, "
            "fee_rate, rebate_rate "
            f"FROM {self._schema}.short_interest_snapshots WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    # ------------------------------------------------------------------
    # Row-count helpers (used by integration test)
    # ------------------------------------------------------------------
    def count_rows(self, table: str) -> int:
        sql = f"SELECT COUNT(*) FROM {self._schema}.{table}"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def apply_migration(self, sql_text: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql_text)

    # ------------------------------------------------------------------
    # S2: scan_universe + scan_results
    # ------------------------------------------------------------------
    def insert_scan_universe(
        self,
        run_id: int,
        tickers: Iterable[str],
        source: str = "hardcoded_s2",
    ) -> int:
        rows = [t.upper() for t in tickers]
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.scan_universe (run_id, ticker, source) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (run_id, ticker) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for t in rows:
                cur.execute(sql, (run_id, t, source))
        return len(rows)

    def insert_scan_results(
        self,
        run_id: int,
        results: Iterable[models.ScanTickerResult],
    ) -> int:
        rows = list(results)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.scan_results ("
            "run_id, ticker, market_date, setup_type, direction, score, "
            "net_call_premium, net_put_premium, net_premium, "
            "bullish_premium, bearish_premium, call_premium, put_premium, "
            "put_call_ratio, iv_rank, volatility, iv30d, "
            "implied_move, implied_move_perc, "
            "gex_net_change, gex_ratio, variance_risk_premium, "
            "total_open_interest, relative_volume, next_earnings_date, "
            "sector, marketcap, "
            "signals_present, confirmations, warnings, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker) DO UPDATE SET "
            "setup_type=EXCLUDED.setup_type, direction=EXCLUDED.direction, "
            "score=EXCLUDED.score, signals_present=EXCLUDED.signals_present, "
            "confirmations=EXCLUDED.confirmations, warnings=EXCLUDED.warnings, "
            "notes=EXCLUDED.notes"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                sr = r.screener_row
                market_date = sr.date if sr is not None else None
                volatility = sr.volatility if sr is not None else None
                iv30d = sr.iv30d if sr is not None else None
                implied_move = sr.implied_move if sr is not None else None
                implied_move_perc = sr.implied_move_perc if sr is not None else None
                gex_ratio = sr.gex_ratio if sr is not None else None
                bullish_premium = sr.bullish_premium if sr is not None else None
                bearish_premium = sr.bearish_premium if sr is not None else None
                call_premium = sr.call_premium if sr is not None else None
                put_premium = sr.put_premium if sr is not None else None
                put_call_ratio = sr.put_call_ratio if sr is not None else None
                marketcap = sr.marketcap if sr is not None else None
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.ticker,
                        market_date,
                        r.setup_type,
                        r.direction,
                        r.score,
                        r.net_call_premium,
                        r.net_put_premium,
                        r.net_premium,
                        bullish_premium,
                        bearish_premium,
                        call_premium,
                        put_premium,
                        put_call_ratio,
                        r.iv_rank,
                        volatility,
                        iv30d,
                        implied_move,
                        implied_move_perc,
                        r.gex_net_change,
                        gex_ratio,
                        r.variance_risk_premium,
                        r.total_open_interest,
                        r.relative_volume,
                        r.next_earnings_date,
                        r.sector,
                        marketcap,
                        list(r.signals_present),
                        list(r.confirmations),
                        list(r.warnings),
                        r.notes,
                    ),
                )
        return len(rows)

    def fetch_scan_universe(self, run_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT ticker, source FROM {self._schema}.scan_universe "
            "WHERE run_id = %s ORDER BY ticker"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_scan_results(self, run_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT run_id, ticker, market_date, setup_type, direction, score, "
            "net_call_premium, net_put_premium, net_premium, "
            "bullish_premium, bearish_premium, call_premium, put_premium, "
            "put_call_ratio, iv_rank, volatility, iv30d, "
            "implied_move, implied_move_perc, "
            "gex_net_change, gex_ratio, variance_risk_premium, "
            "total_open_interest, relative_volume, next_earnings_date, "
            "sector, marketcap, "
            "signals_present, confirmations, warnings, notes "
            f"FROM {self._schema}.scan_results "
            "WHERE run_id = %s "
            "ORDER BY score DESC, ticker ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def get_last_full_scan_finished_at(self) -> datetime | None:
        """Latest scan_runs.finished_at where status='ok'. Used by /api/health."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(finished_at) FROM {self._schema}.scan_runs
                WHERE status='ok' AND finished_at IS NOT NULL
                """
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def list_runs_for_ticker(
        self, ticker: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent scan_runs rows for a ticker, newest first."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT run_id, started_at, finished_at, status
                FROM {self._schema}.scan_runs
                WHERE ticker = %s
                ORDER BY run_id DESC
                LIMIT %s
                """,
                (ticker.upper(), limit),
            )
            return [
                {
                    "run_id": int(row[0]),
                    "scanned_at": row[1],
                    "finished_at": row[2],
                    "status": row[3],
                }
                for row in cur.fetchall()
            ]

    def latest_scan_run_id(self) -> int:
        """Return the highest run_id that has scan_results rows, or 0 if none."""
        sql = (
            f"SELECT run_id FROM {self._schema}.scan_results "
            "ORDER BY run_id DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # S3+: watchlist CRUD
    # ------------------------------------------------------------------
    def list_active_watchlist(self) -> list[WatchlistRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, sector, notes, pinned, sort_rank, added_at, removed_at
                FROM {self._schema}.watchlist
                WHERE removed_at IS NULL
                ORDER BY sort_rank, ticker
                """
            )
            return [WatchlistRow(*row) for row in cur.fetchall()]

    def add_watchlist_ticker(
        self,
        *,
        ticker: str,
        sector: str,
        notes: str | None = None,
        sort_rank: int = 0,
        pinned: bool = False,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist
                  (ticker, sector, notes, sort_rank, pinned)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET sector=EXCLUDED.sector, notes=EXCLUDED.notes,
                      sort_rank=EXCLUDED.sort_rank, pinned=EXCLUDED.pinned,
                      removed_at=NULL
                """,
                (ticker, sector, notes, sort_rank, pinned),
            )
        self._conn.commit()

    def soft_delete_watchlist_ticker(self, ticker: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.watchlist SET removed_at=NOW() WHERE ticker=%s",
                (ticker,),
            )
        self._conn.commit()

    def patch_watchlist_ticker(
        self,
        ticker: str,
        *,
        sector: str | None = None,
        notes: str | None = None,
        pinned: bool | None = None,
        sort_rank: int | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        for col, val in (
            ("sector", sector),
            ("notes", notes),
            ("pinned", pinned),
            ("sort_rank", sort_rank),
        ):
            if val is not None:
                sets.append(f"{col}=%s")
                vals.append(val)
        if not sets:
            return
        vals.append(ticker)
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.watchlist SET {', '.join(sets)} WHERE ticker=%s",
                vals,
            )
        self._conn.commit()

    # ---- watchlist_card ----
    def upsert_watchlist_card(
        self,
        *,
        ticker: str,
        run_id: int,
        scanned_at: datetime,
        spot: Decimal | None = None,
        **fields: Any,
    ) -> None:
        """Insert or replace the per-ticker card row.

        `updated_at` is DB-owned (default NOW() on insert; refreshed by the
        conflict branch). It is NOT part of the column list, so INSERT cols
        and VALUES placeholders have matching arity.
        """
        cols = ["ticker", "run_id", "scanned_at", "spot", *fields.keys()]
        vals = [ticker, run_id, scanned_at, spot, *fields.values()]
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "ticker")
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist_card ({", ".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (ticker) DO UPDATE SET {updates}, updated_at=NOW()
                """,
                vals,
            )
        self._conn.commit()

    def get_watchlist_card(self, ticker: str) -> WatchlistCardRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self._schema}.watchlist_card WHERE ticker=%s",
                (ticker,),
            )
            row = cur.fetchone()
            return WatchlistCardRow.from_db(row, cur.description) if row else None

    def list_watchlist_cards(self) -> list[WatchlistCardRow]:
        """Return one row per active watchlist ticker.

        LEFT JOIN from watchlist → watchlist_card so tickers that haven't been
        scanned yet still appear (with scan-derived fields = None). The page
        renders them as 'no data' placeholders, which is preferable to making
        them invisible while a full_scan is still chewing through the queue.
        Also LEFT JOINs intraday_quotes so a 15-min-delayed spot price shows
        up even before the first full scan for that ticker.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  w.ticker, w.sector, w.pinned, w.sort_rank,
                  c.run_id, c.scanned_at,
                  COALESCE(c.spot, q.price)                                AS spot,
                  COALESCE(c.spot_quoted_at, q.quoted_at)                  AS spot_quoted_at,
                  COALESCE(c.spot_source, CASE WHEN q.price IS NOT NULL THEN 'massive.com_intraday' END) AS spot_source,
                  c.iv_atm, c.iv_rank,
                  c.setup_type, c.setup_direction, c.setup_score,
                  c.aggression_pct,
                  c.ret_1d, c.ret_1w, c.ret_30d,
                  c.gex_flip_distance, c.gex_flip_price, c.gex_per_1pct_move,
                  c.max_gex_strike, c.gex_expiring_pct, c.gex_expiring_date,
                  c.skew_25d_30dte,
                  c.call_oi_total, c.put_oi_total, c.pcr_oi, c.pcr_vol,
                  c.pcr_delta_30d
                FROM {self._schema}.watchlist w
                LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
                LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
                WHERE w.removed_at IS NULL
                ORDER BY w.pinned DESC, w.sort_rank, w.ticker
                """
            )
            return [
                WatchlistCardRow.from_db(row, cur.description) for row in cur.fetchall()
            ]

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
        self, ticker: str, price: Decimal, quoted_at: datetime
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.intraday_quote (ticker, price, quoted_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price, quoted_at=EXCLUDED.quoted_at, fetched_at=NOW()
                """,
                (ticker, price, quoted_at),
            )
        self._conn.commit()

    def get_intraday_quote(self, ticker: str) -> IntradayQuoteRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, price, quoted_at, fetched_at
                FROM {self._schema}.intraday_quote WHERE ticker=%s
                """,
                (ticker,),
            )
            row = cur.fetchone()
            return IntradayQuoteRow(*row) if row else None

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

    # ---- jobs ----
    def enqueue_rescan_job(self, ticker: str) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.jobs (ticker, status)
                VALUES (%s, 'queued') RETURNING id
                """,
                (ticker,),
            )
            row = cur.fetchone()
            assert row is not None
            job_id = row[0]
        self._conn.commit()
        return str(job_id)

    def claim_next_queued_job(self) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='running', started_at=NOW()
                WHERE id = (
                  SELECT id FROM {self._schema}.jobs
                  WHERE status='queued'
                  ORDER BY requested_at
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING id, ticker, status, run_id, error, requested_at, started_at, finished_at
                """
            )
            row = cur.fetchone()
        self._conn.commit()
        return JobRow(*row) if row else None

    def mark_job_done(self, job_id: str, run_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='done', run_id=%s, finished_at=NOW() WHERE id=%s
                """,
                (run_id, job_id),
            )
        self._conn.commit()

    def mark_job_failed(self, job_id: str, error: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='failed', error=%s, finished_at=NOW() WHERE id=%s
                """,
                (error[:2000], job_id),
            )
        self._conn.commit()

    # ---- aggregates (JSONB on scan_runs) ----
    def set_aggregates(self, run_id: int, agg: "models.MarketAggregates") -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.scan_runs SET aggregates=%s WHERE run_id=%s",
                (Jsonb(agg.model_dump(mode="json")), run_id),
            )
        self._conn.commit()

    def get_aggregates(self, run_id: int) -> "models.MarketAggregates | None":
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT aggregates FROM {self._schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        return models.MarketAggregates.model_validate(row[0])

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

    # ---- stock history rollup (for Market Structure history table) ----
    def fetch_stock_history_rollup(self, ticker: str, limit: int = 30) -> list[dict]:
        """One row per trading day, latest successful scan_run on that date.

        Joins to daily_ohlc for end-of-day spot. Returns dicts shaped for
        api.routers.stock to wrap in StockHistoryRow models.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH daily_runs AS (
                    SELECT DISTINCT ON (started_at::date)
                        started_at::date AS market_date,
                        strike_gex_curve,
                        aggregates
                    FROM {self._schema}.scan_runs
                    WHERE ticker = %s
                      AND status = 'ok'
                      AND strike_gex_curve IS NOT NULL
                    ORDER BY started_at::date DESC, started_at DESC
                )
                SELECT
                    r.market_date,
                    d.close AS spot,
                    r.aggregates->>'iv30d' AS iv30d,
                    r.aggregates->>'pcr_vol' AS pcr_vol,
                    r.strike_gex_curve
                FROM daily_runs r
                LEFT JOIN {self._schema}.daily_ohlc d
                  ON d.ticker = %s AND d.date = r.market_date
                ORDER BY r.market_date DESC
                LIMIT %s
                """,
                (ticker, ticker, limit),
            )
            return [
                {
                    "market_date": row[0],
                    "spot": row[1],
                    "iv30d": row[2],
                    "pcr_vol": row[3],
                    "strike_gex_curve": row[4],
                }
                for row in cur.fetchall()
            ]

    # ---- watchlist count (for HealthPanel) ----
    def count_active_watchlist(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {self._schema}.watchlist WHERE removed_at IS NULL"
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    # ---- worker_heartbeat ----
    def upsert_heartbeat(self, job_name: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.worker_heartbeat (job_name, last_beat_at)
                VALUES (%s, now())
                ON CONFLICT (job_name) DO UPDATE SET last_beat_at = now()
                """,
                (job_name,),
            )
        self._conn.commit()

    def get_heartbeat(self, job_name: str) -> datetime | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT last_beat_at FROM {self._schema}.worker_heartbeat WHERE job_name=%s",
                (job_name,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    # ---- strike_gex_curve (JSONB on scan_runs) ----
    def set_strike_gex_curve(self, run_id: int, curve: list[dict]) -> None:
        """Persist the per-strike, per-expiry GEX curve as JSONB on the run row."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.scan_runs SET strike_gex_curve=%s WHERE run_id=%s",
                (Jsonb(curve), run_id),
            )
        self._conn.commit()

    def get_strike_gex_curve(self, run_id: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT strike_gex_curve FROM {self._schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else []

    def get_job(self, job_id: str) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, status, run_id, error, requested_at, started_at, finished_at
                FROM {self._schema}.jobs WHERE id=%s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return JobRow(*row) if row else None

    # ---- Volatility Tab v2 helpers (spec 2026-05-13) ----

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


# Re-export for convenience
__all__ = [
    "Repository",
    "WatchlistRow",
    "WatchlistCardRow",
    "DailyOhlcRow",
    "IntradayQuoteRow",
    "PcrHistoryRow",
    "JobRow",
]
