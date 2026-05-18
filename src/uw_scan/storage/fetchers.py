"""Read-only ticker report fetchers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg



class _FetchersMixin:
    _conn: psycopg.Connection
    _schema: str

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

    def fetch_flow_alerts_daily_baseline(
        self, run_id: int, ticker: str, lookback_days: int = 30
    ) -> dict[str, Any] | None:
        sql = (
            "WITH current_rollup AS ("
            f"SELECT ticker, trade_date, alert_count, alert_count_is_limited, "
            "top_alert_rule "
            f"FROM {self._schema}.flow_alerts_daily_rollup "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY trade_date DESC LIMIT 1"
            "), history AS ("
            f"SELECT h.alert_count "
            f"FROM {self._schema}.flow_alerts_daily_rollup h "
            "JOIN current_rollup c ON c.ticker = h.ticker "
            "WHERE h.trade_date < c.trade_date "
            "AND h.trade_date >= c.trade_date - (%s::int * INTERVAL '1 day')"
            ") "
            "SELECT c.alert_count, c.alert_count_is_limited, c.top_alert_rule, "
            "AVG(h.alert_count)::numeric AS avg_30d_alert_count, "
            "CASE WHEN AVG(h.alert_count) > 0 "
            "THEN ROUND(c.alert_count::numeric / AVG(h.alert_count)::numeric, 16) "
            "ELSE NULL END AS flow_count_vs_30d_avg, "
            "COUNT(h.alert_count)::int AS baseline_days "
            "FROM current_rollup c "
            "LEFT JOIN history h ON true "
            "GROUP BY c.alert_count, c.alert_count_is_limited, c.top_alert_rule"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper(), lookback_days))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

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

        # LEFT JOIN option_contract_snapshots to surface today's ask/bid/mid
        # breakdown — /oi-change never returns prev_* side volumes (all NULL),
        # so per-contract aggressor classification has to come from
        # /option-contracts via this join.
        sql = (
            f"SELECT e.underlying_symbol, e.option_symbol, e.curr_date, e.last_date, "
            "e.curr_oi, e.last_oi, e.oi_diff_plain, e.oi_change, e.volume, e.trades, "
            "e.avg_price, e.last_fill, e.days_of_oi_increases, e.days_of_vol_greater_than_oi, "
            "e.percentage_of_total, e.rnk, "
            "e.prev_ask_volume, e.prev_bid_volume, e.prev_mid_volume, e.prev_neutral_volume, "
            "e.prev_multi_leg_volume, e.prev_stock_multi_leg_volume, "
            "e.prev_total_premium, e.last_ask, e.last_bid, "
            "s.ask_volume, s.bid_volume, s.mid_volume, s.no_side_volume "
            f"FROM {self._schema}.oi_change_events e "
            f"LEFT JOIN {self._schema}.option_contract_snapshots s "
            "  ON s.run_id = e.run_id AND s.option_symbol = e.option_symbol "
            "WHERE e.run_id = %s "
            "ORDER BY (COALESCE(e.volume, 0) * COALESCE(e.avg_price, 0)) DESC NULLS LAST, e.rnk ASC "
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

    def fetch_option_contracts_rich(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, prev_oi, volume, ask_volume, "
            "bid_volume, mid_volume, multi_leg_volume, stock_multi_leg_volume, "
            "floor_volume, sweep_volume, no_side_volume, avg_price, high_price, "
            "low_price, total_premium "
            f"FROM {self._schema}.option_contract_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
