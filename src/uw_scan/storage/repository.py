"""Persistence layer: thin wrapper around psycopg cursors.

One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .. import models

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
        """Return the highest run_id for `ticker`, or 0 if none."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT run_id FROM {self._schema}.scan_runs "
                "WHERE ticker = %s ORDER BY run_id DESC LIMIT 1",
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

    def insert_oi_change_rows(
        self, run_id: int, rows: Iterable[models.OiChangeRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.oi_change_events "
            "(run_id, underlying_symbol, option_symbol, curr_date, last_date, "
            "curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            "avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            "percentage_of_total, rnk) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
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

    def fetch_oi_change_top(self, run_id: int, limit: int = 10) -> list[dict[str, Any]]:
        sql = (
            f"SELECT underlying_symbol, option_symbol, curr_date, last_date, "
            "curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            "avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            "percentage_of_total, rnk "
            f"FROM {self._schema}.oi_change_events "
            "WHERE run_id = %s ORDER BY rnk ASC NULLS LAST LIMIT %s"
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


# Re-export for convenience
__all__ = ["Repository"]
