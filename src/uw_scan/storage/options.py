"""Option-chain and run-keyed options persistence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from decimal import Decimal
from typing import Any

import psycopg

from .. import models


def _iv_term_params(
    run_id: int, rows: Iterable[models.TermStructureRow]
) -> list[tuple[Any, ...]]:
    return [
        (
            run_id,
            r.ticker,
            r.date,
            r.expiry,
            r.dte,
            r.volatility,
            r.implied_move,
            r.implied_move_perc,
        )
        for r in rows
    ]


def _greek_exposure_params(
    run_id: int, ticker: str, rows: Iterable[models.GreekExposureRow]
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


def _greeks_params(
    run_id: int, ticker: str, rows: Iterable[models.GreeksRow]
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


def _option_contract_params(
    run_id: int, ticker: str, rows: Iterable[models.OptionContractRow]
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


def _interpolated_iv_params(
    run_id: int, ticker: str, rows: Iterable[models.InterpolatedIvRow]
) -> list[tuple[Any, ...]]:
    return [
        (
            run_id,
            ticker,
            r.date,
            r.days,
            r.percentile,
            r.volatility,
            r.implied_move_perc,
        )
        for r in rows
    ]


def _oi_per_strike_params(
    ticker: str, rows: Iterable[models.OiPerStrikeRow]
) -> list[tuple[Any, ...]]:
    return [(ticker, r.date, r.strike, r.call_oi, r.put_oi) for r in rows]


def _options_volume_daily_params(
    ticker: str, rows: Iterable[models.OptionsDailyRow]
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


def _option_chain_per_strike_params(
    ticker: str,
    snapshot_date: _date,
    rows: Iterable[models.OptionChainPerStrikeRow],
) -> list[tuple[Any, ...]]:
    return [
        (
            ticker,
            snapshot_date,
            r.expiry,
            r.strike,
            r.call_volume,
            r.put_volume,
            r.call_oi,
            r.put_oi,
        )
        for r in rows
    ]


def _oi_change_params(
    run_id: int, rows: Iterable[models.OiChangeRow]
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


def _max_pain_params(
    run_id: int,
    ticker: str,
    market_date: Any,
    rows: Iterable[models.MaxPainRow],
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


def _dark_pool_params(
    run_id: int, rows: Iterable[models.DarkPoolPrint]
) -> list[tuple[Any, ...]]:
    return [
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
        )
        for r in rows
    ]


class _OptionsMixin:
    _conn: psycopg.Connection
    _schema: str

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
        params = _iv_term_params(run_id, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _interpolated_iv_params(run_id, ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _greek_exposure_params(run_id, ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _greeks_params(run_id, ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_exposures_summary(
        self,
        run_id: int,
        ticker: str,
        market_date: _date,
        rows: Iterable[models.ExposuresSummaryRow],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.exposures_summary "
            "(run_id, ticker, expiry, market_date, dte, spot, "
            " net_vanna, top_vanna_strike, top_vanna_value, delta_shock_1pt_iv, "
            " vanna_regime, vanna_flip, vanna_headline, vanna_subtitle, "
            " net_charm, charm_pin_strike, charm_above_sum, charm_below_sum, "
            " charm_imbalance_pct, charm_signal_quality, charm_flip, "
            " charm_headline, charm_subtitle) "
            "VALUES (%s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, "
            "        %s, %s, %s, %s, "
            "        %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry) DO UPDATE SET "
            " market_date=EXCLUDED.market_date, dte=EXCLUDED.dte, spot=EXCLUDED.spot, "
            " net_vanna=EXCLUDED.net_vanna, top_vanna_strike=EXCLUDED.top_vanna_strike, "
            " top_vanna_value=EXCLUDED.top_vanna_value, "
            " delta_shock_1pt_iv=EXCLUDED.delta_shock_1pt_iv, "
            " vanna_regime=EXCLUDED.vanna_regime, vanna_flip=EXCLUDED.vanna_flip, "
            " vanna_headline=EXCLUDED.vanna_headline, vanna_subtitle=EXCLUDED.vanna_subtitle, "
            " net_charm=EXCLUDED.net_charm, charm_pin_strike=EXCLUDED.charm_pin_strike, "
            " charm_above_sum=EXCLUDED.charm_above_sum, charm_below_sum=EXCLUDED.charm_below_sum, "
            " charm_imbalance_pct=EXCLUDED.charm_imbalance_pct, "
            " charm_signal_quality=EXCLUDED.charm_signal_quality, "
            " charm_flip=EXCLUDED.charm_flip, "
            " charm_headline=EXCLUDED.charm_headline, charm_subtitle=EXCLUDED.charm_subtitle, "
            " computed_at=now()"
        )
        params = [
            (
                run_id,
                ticker,
                r.expiry,
                market_date,
                r.dte,
                r.spot,
                r.net_vanna,
                r.top_vanna_strike,
                r.top_vanna_value,
                r.delta_shock_1pt_iv,
                r.vanna_regime,
                r.vanna_flip,
                r.vanna_headline,
                r.vanna_subtitle,
                r.net_charm,
                r.charm_pin_strike,
                r.charm_above_sum,
                r.charm_below_sum,
                r.charm_imbalance_pct,
                r.charm_signal_quality,
                r.charm_flip,
                r.charm_headline,
                r.charm_subtitle,
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _oi_per_strike_params(ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _options_volume_daily_params(ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _option_chain_per_strike_params(ticker, snapshot_date, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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

    # ------------------------------------------------------------------
    # Cockpit matrix state source reads
    # ------------------------------------------------------------------

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
        params = _oi_change_params(run_id, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def replace_oi_change_rows_for_date(
        self, run_id: int, rows: Iterable[models.OiChangeRow]
    ) -> int:
        """Replace target historical OI-change ticker/date slices.

        Normal scan ingestion can store duplicate ticker/date/contract rows
        across scan runs for audit history. Historical backfill instead wants a
        resumable final-state slice, so it deletes only the incoming ticker/date
        keys before inserting the new run's rows.
        """

        rows = list(rows)
        if not rows:
            return 0
        keys = sorted(
            {
                (r.underlying_symbol.upper(), r.curr_date)
                for r in rows
                if r.curr_date is not None
            }
        )
        if not keys:
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
        params = _oi_change_params(run_id, rows)
        with self._conn.cursor() as cur:
            cur.executemany(
                f"DELETE FROM {self._schema}.oi_change_events "
                "WHERE underlying_symbol = %s AND curr_date = %s",
                keys,
            )
            cur.executemany(sql, params)
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
        params = _max_pain_params(run_id, ticker, market_date, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _option_contract_params(run_id, ticker, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
        params = _dark_pool_params(run_id, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
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
    # SELECT helpers — used by reports/single_stock.py
    # ------------------------------------------------------------------

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
