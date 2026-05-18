"""Cockpit matrix-state persistence and source-freshness reads."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql as psql

from .. import models


def _vrp_sign_flip_status_for_db(value: bool | str | None) -> str | None:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return value


def _vrp_sign_flip_status_from_db(value: Any) -> bool | str:
    if value == "true":
        return True
    if value == "false":
        return False
    return value or "insufficient_history"


# _RECORD_HEALTH_* constants moved to health.py with _HealthMixin


class _MatrixStateMixin:
    _conn: psycopg.Connection
    _schema: str

    def fetch_matrix_greeks_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT expiry, strike, call_vanna, put_vanna, call_charm, put_charm, "
            "call_option_symbol, put_option_symbol "
            f"FROM {self._schema}.greeks_by_expiry_strike "
            "WHERE ticker = %s AND market_date = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.greeks_by_expiry_strike "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_straddle_mid_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT g.expiry, g.strike, "
            "(c.nbbo_bid + c.nbbo_ask) / 2 AS call_mid, "
            "(p.nbbo_bid + p.nbbo_ask) / 2 AS put_mid "
            f"FROM {self._schema}.greeks_by_expiry_strike g "
            f"LEFT JOIN {self._schema}.option_contract_snapshots c "
            "  ON c.run_id = g.run_id AND c.option_symbol = g.call_option_symbol "
            f"LEFT JOIN {self._schema}.option_contract_snapshots p "
            "  ON p.run_id = g.run_id AND p.option_symbol = g.put_option_symbol "
            "WHERE g.ticker = %s AND g.market_date = %s "
            "  AND g.run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.greeks_by_expiry_strike "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY g.expiry ASC, g.strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_exposure_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT expiry, strike, dte, call_gex, put_gex, "
            "call_vanna, put_vanna, call_charm, put_charm "
            f"FROM {self._schema}.exposures_by_expiry_strike "
            "WHERE ticker = %s AND market_date = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.exposures_by_expiry_strike "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_option_chain_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT snapshot_date, expiry, strike, call_volume, put_volume, call_oi, put_oi "
            f"FROM {self._schema}.option_chain_per_strike "
            "WHERE ticker = %s AND snapshot_date = ("
            f"  SELECT max(snapshot_date) FROM {self._schema}.option_chain_per_strike "
            "  WHERE ticker = %s AND snapshot_date <= %s"
            ") "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_skew_history(
        self, *, ticker: str, market_date: _date, days: int = 260
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT DISTINCT ON (market_date) market_date, delta, expiry, risk_reversal "
            f"FROM {self._schema}.risk_reversal_skew_history "
            "WHERE ticker = %s AND delta = 25 "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC, expiry ASC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_skew_expiry_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT market_date, delta, expiry, risk_reversal "
            f"FROM {self._schema}.risk_reversal_skew_history "
            "WHERE ticker = %s AND delta = 25 AND market_date = %s "
            "ORDER BY expiry ASC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_term_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, dte, volatility, implied_move, implied_move_perc "
            f"FROM {self._schema}.iv_term_snapshots "
            "WHERE ticker = %s AND market_date = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.iv_term_snapshots "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY dte ASC NULLS LAST, expiry ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_interpolated_iv_history(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT DISTINCT ON (market_date) "
            "market_date, days, percentile, volatility, implied_move_perc "
            f"FROM {self._schema}.interpolated_iv_snapshots "
            "WHERE ticker = %s "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC, ABS(days - 30) ASC, run_id DESC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_realized_vol_history(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def persist_vrp_30d_settlements(self, *, ticker: str, market_date: _date) -> None:
        iv_sql = (
            "SELECT volatility "
            f"FROM {self._schema}.interpolated_iv_snapshots "
            "WHERE ticker = %s AND market_date = %s "
            "ORDER BY ABS(days - 30) ASC, run_id DESC LIMIT 1"
        )
        rv_sql = (
            "SELECT market_date, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s AND market_date >= (%s::date + INTERVAL '30 days') "
            "  AND realized_volatility IS NOT NULL "
            "ORDER BY market_date ASC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(iv_sql, (ticker.upper(), market_date))
            iv_row = cur.fetchone()
            if iv_row is None or iv_row[0] is None:
                return
            iv_30d = iv_row[0]
            cur.execute(rv_sql, (ticker.upper(), market_date))
            rv_row = cur.fetchone()
            settlement_date = rv_row[0] if rv_row else None
            rv_subsequent = rv_row[1] if rv_row else None
            vrp_strict = iv_30d - rv_subsequent if rv_subsequent is not None else None
            cur.execute(
                f"INSERT INTO {self._schema}.vrp_30d_settlements ("
                "ticker, market_date, iv_30d, settlement_date, rv_subsequent, "
                "vrp_strict, generated_at"
                ") VALUES (%s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (ticker, market_date) DO UPDATE SET "
                "iv_30d=EXCLUDED.iv_30d, "
                "settlement_date=EXCLUDED.settlement_date, "
                "rv_subsequent=EXCLUDED.rv_subsequent, "
                "vrp_strict=EXCLUDED.vrp_strict, "
                "generated_at=now(), inserted_at=now()",
                (
                    ticker.upper(),
                    market_date,
                    iv_30d,
                    settlement_date,
                    rv_subsequent,
                    vrp_strict,
                ),
            )

    def fetch_vrp_30d_settlement(
        self, *, ticker: str, market_date: _date
    ) -> dict[str, Any] | None:
        sql = (
            "SELECT ticker, market_date, iv_30d, settlement_date, rv_subsequent, "
            "vrp_strict, generated_at, inserted_at "
            f"FROM {self._schema}.vrp_30d_settlements "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_matrix_oi_change_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT option_symbol, oi_diff_plain, oi_change, volume, trades "
            f"FROM {self._schema}.oi_change_events "
            "WHERE underlying_symbol = %s AND curr_date = %s "
            "ORDER BY ABS(COALESCE(oi_diff_plain, 0)) DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_matrix_state_snapshot(self, state: models.MatrixState) -> None:
        sql = (
            f"INSERT INTO {self._schema}.matrix_state_snapshots ("
            "ticker, market_date, threshold_version, vanna_state, charm_state, skew_state, "
            "term_state, im_state, flow_state, vrp_state, consistency_tier, "
            "cluster_coverage_ok, term_classification, skew_25d_zscore_180d, "
            "iv_atm_30d, rv_30d, vrp, vrp_zscore_60d, implied_move_pct, "
            "front_iv, back_iv, front_back_spread, pin_distance_sigma, vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days, vanna_conditional_reading, "
            "directional_imbalance_3d, vanna_oi_change_bias, charm_regime, "
            "charm_stress_override, skew_25d_5d_change, skew_regime, "
            "skew_term_structure, single_point_bump_pct, full_curve_slope_pct, "
            "term_johnson_slope_pc1, atm_straddle_mid, implied_move_expected_abs, "
            "implied_move_event_percentile, vrp_zscore_252d, generated_at"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, now()"
            ") ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "threshold_version=EXCLUDED.threshold_version, "
            "vanna_state=EXCLUDED.vanna_state, "
            "charm_state=EXCLUDED.charm_state, "
            "skew_state=EXCLUDED.skew_state, "
            "term_state=EXCLUDED.term_state, "
            "im_state=EXCLUDED.im_state, "
            "flow_state=EXCLUDED.flow_state, "
            "vrp_state=EXCLUDED.vrp_state, "
            "consistency_tier=EXCLUDED.consistency_tier, "
            "cluster_coverage_ok=EXCLUDED.cluster_coverage_ok, "
            "term_classification=EXCLUDED.term_classification, "
            "skew_25d_zscore_180d=EXCLUDED.skew_25d_zscore_180d, "
            "iv_atm_30d=EXCLUDED.iv_atm_30d, "
            "rv_30d=EXCLUDED.rv_30d, "
            "vrp=EXCLUDED.vrp, "
            "vrp_zscore_60d=EXCLUDED.vrp_zscore_60d, "
            "implied_move_pct=EXCLUDED.implied_move_pct, "
            "front_iv=EXCLUDED.front_iv, "
            "back_iv=EXCLUDED.back_iv, "
            "front_back_spread=EXCLUDED.front_back_spread, "
            "pin_distance_sigma=EXCLUDED.pin_distance_sigma, "
            "vrp_sign_flip_status=EXCLUDED.vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days=EXCLUDED.vrp_sign_flip_aligned_days, "
            "vanna_conditional_reading=EXCLUDED.vanna_conditional_reading, "
            "directional_imbalance_3d=EXCLUDED.directional_imbalance_3d, "
            "vanna_oi_change_bias=EXCLUDED.vanna_oi_change_bias, "
            "charm_regime=EXCLUDED.charm_regime, "
            "charm_stress_override=EXCLUDED.charm_stress_override, "
            "skew_25d_5d_change=EXCLUDED.skew_25d_5d_change, "
            "skew_regime=EXCLUDED.skew_regime, "
            "skew_term_structure=EXCLUDED.skew_term_structure, "
            "single_point_bump_pct=EXCLUDED.single_point_bump_pct, "
            "full_curve_slope_pct=EXCLUDED.full_curve_slope_pct, "
            "term_johnson_slope_pc1=EXCLUDED.term_johnson_slope_pc1, "
            "atm_straddle_mid=EXCLUDED.atm_straddle_mid, "
            "implied_move_expected_abs=EXCLUDED.implied_move_expected_abs, "
            "implied_move_event_percentile=EXCLUDED.implied_move_event_percentile, "
            "vrp_zscore_252d=EXCLUDED.vrp_zscore_252d, "
            "generated_at=now(), inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    state.ticker,
                    state.market_date,
                    state.threshold_version,
                    state.vanna_state,
                    state.charm_state,
                    state.skew_state,
                    state.term_state,
                    state.im_state,
                    state.flow_state,
                    state.vrp_state,
                    state.consistency_tier,
                    state.cluster_coverage_ok,
                    state.term_classification,
                    state.skew_25d_zscore_180d,
                    state.iv_atm_30d,
                    state.rv_30d,
                    state.vrp,
                    state.vrp_zscore_60d,
                    state.implied_move_pct,
                    state.front_iv,
                    state.back_iv,
                    state.front_back_spread,
                    state.pin_distance_sigma,
                    _vrp_sign_flip_status_for_db(state.vrp_sign_flip_status),
                    state.vrp_sign_flip_aligned_days,
                    state.vanna_conditional_reading,
                    state.directional_imbalance_3d,
                    state.vanna_oi_change_bias,
                    state.charm_regime,
                    state.charm_stress_override,
                    state.skew_25d_5d_change,
                    state.skew_regime,
                    state.skew_term_structure,
                    state.single_point_bump_pct,
                    state.full_curve_slope_pct,
                    state.term_johnson_slope_pc1,
                    state.atm_straddle_mid,
                    state.implied_move_expected_abs,
                    state.implied_move_event_percentile,
                    state.vrp_zscore_252d,
                ),
            )

    def fetch_matrix_state_snapshot(
        self, *, ticker: str, market_date: _date
    ) -> models.MatrixState | None:
        sql = (
            "SELECT ticker, market_date, threshold_version, vanna_state, charm_state, skew_state, "
            "term_state, im_state, flow_state, vrp_state, consistency_tier, "
            "cluster_coverage_ok, term_classification, skew_25d_zscore_180d, "
            "iv_atm_30d, rv_30d, vrp, vrp_zscore_60d, implied_move_pct, "
            "front_iv, back_iv, front_back_spread, pin_distance_sigma, vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days, vanna_conditional_reading, "
            "directional_imbalance_3d, vanna_oi_change_bias, charm_regime, "
            "charm_stress_override, skew_25d_5d_change, skew_regime, "
            "skew_term_structure, single_point_bump_pct, full_curve_slope_pct, "
            "term_johnson_slope_pc1, atm_straddle_mid, implied_move_expected_abs, "
            "implied_move_event_percentile, vrp_zscore_252d "
            f"FROM {self._schema}.matrix_state_snapshots "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            data = dict(zip(cols, row, strict=False))
            data["vrp_sign_flip_status"] = _vrp_sign_flip_status_from_db(
                data.get("vrp_sign_flip_status")
            )
            data["vrp_sign_flip_aligned_days"] = (
                data.get("vrp_sign_flip_aligned_days") or 0
            )
            return models.MatrixState(**data)

    def fetch_latest_matrix_state_snapshot(
        self, *, ticker: str
    ) -> models.MatrixState | None:
        sql = (
            "SELECT ticker, market_date, threshold_version, vanna_state, charm_state, skew_state, "
            "term_state, im_state, flow_state, vrp_state, consistency_tier, "
            "cluster_coverage_ok, term_classification, skew_25d_zscore_180d, "
            "iv_atm_30d, rv_30d, vrp, vrp_zscore_60d, implied_move_pct, "
            "front_iv, back_iv, front_back_spread, pin_distance_sigma, vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days, vanna_conditional_reading, "
            "directional_imbalance_3d, vanna_oi_change_bias, charm_regime, "
            "charm_stress_override, skew_25d_5d_change, skew_regime, "
            "skew_term_structure, single_point_bump_pct, full_curve_slope_pct, "
            "term_johnson_slope_pc1, atm_straddle_mid, implied_move_expected_abs, "
            "implied_move_event_percentile, vrp_zscore_252d "
            f"FROM {self._schema}.matrix_state_snapshots "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            data = dict(zip(cols, row, strict=False))
            data["vrp_sign_flip_status"] = _vrp_sign_flip_status_from_db(
                data.get("vrp_sign_flip_status")
            )
            data["vrp_sign_flip_aligned_days"] = (
                data.get("vrp_sign_flip_aligned_days") or 0
            )
            return models.MatrixState(**data)

    def fetch_matrix_source_freshness(
        self, *, ticker: str, market_date: _date
    ) -> models.MatrixSourceFreshness:
        return models.MatrixSourceFreshness(
            vanna_charm=self._latest_inserted_at(
                "greeks_by_expiry_strike",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            skew=self._latest_inserted_at(
                "risk_reversal_skew_history",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            term=self._latest_inserted_at(
                "iv_term_snapshots",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            im_vrp=self._latest_inserted_at(
                "interpolated_iv_snapshots",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            vrp_rv=self._latest_inserted_at(
                "realized_volatility_history",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            oi=self._latest_inserted_at(
                "option_chain_per_strike",
                ticker=ticker,
                date_column="snapshot_date",
                market_date=market_date,
                timestamp_column="fetched_at",
                comparison="<=",
            ),
        )

    def fetch_latest_cockpit_source_market_date(self, *, ticker: str) -> _date | None:
        sql = (
            "SELECT max(market_date) FROM ("
            f"  SELECT market_date FROM {self._schema}.greeks_by_expiry_strike "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.exposures_by_expiry_strike "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.risk_reversal_skew_history "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.iv_term_snapshots "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.interpolated_iv_snapshots "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.realized_volatility_history "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.vanna_signals "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.charm_signals "
            "  WHERE ticker = %s"
            ") source_dates"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (ticker, ticker, ticker, ticker, ticker, ticker, ticker, ticker),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def _latest_inserted_at(
        self,
        table: str,
        *,
        ticker: str,
        date_column: str,
        market_date: _date,
        timestamp_column: str = "inserted_at",
        comparison: str = "=",
    ) -> datetime | None:
        allowed = {
            "greeks_by_expiry_strike",
            "risk_reversal_skew_history",
            "iv_term_snapshots",
            "interpolated_iv_snapshots",
            "realized_volatility_history",
            "option_chain_per_strike",
        }
        if (
            table not in allowed
            or comparison not in {"=", "<="}
            or date_column not in {"market_date", "snapshot_date"}
            or timestamp_column not in {"inserted_at", "fetched_at"}
        ):
            raise ValueError(f"unsupported matrix freshness source: {table}")
        with self._conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT max({}) FROM {} WHERE ticker = %s AND {} "
                    + comparison
                    + " %s"
                ).format(
                    psql.Identifier(timestamp_column),
                    psql.Identifier(self._schema, table),
                    psql.Identifier(date_column),
                ),
                (ticker, market_date),
            )
            row = cur.fetchone()
            return row[0] if row else None
