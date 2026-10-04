"""Index dealer cockpit derived dealer and surface reads."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from .. import models
from ..cards.cockpit_dealer import compute_cockpit_dealer_metrics, flow_color_summary


class _CockpitMixin:
    _conn: psycopg.Connection
    _schema: str

    def fetch_cockpit_dealer_points(
        self, *, ticker: str, market_date: _date
    ) -> list[models.CockpitDealerPoint]:
        greeks = self.fetch_matrix_greeks_rows(ticker=ticker, market_date=market_date)
        exposures = self.fetch_matrix_exposure_rows(
            ticker=ticker, market_date=market_date
        )
        exposure_by_key = {
            (row["expiry"], row["strike"]): row
            for row in exposures
            if row.get("expiry") is not None and row.get("strike") is not None
        }
        points: list[models.CockpitDealerPoint] = []
        for row in greeks:
            key = (row["expiry"], row["strike"])
            exposure = exposure_by_key.get(key, {})
            points.append(
                models.CockpitDealerPoint(
                    expiry=row["expiry"],
                    strike=row["strike"],
                    call_vanna=row.get("call_vanna"),
                    put_vanna=row.get("put_vanna"),
                    call_charm=row.get("call_charm"),
                    put_charm=row.get("put_charm"),
                    exposure_call_vanna=exposure.get("call_vanna"),
                    exposure_put_vanna=exposure.get("put_vanna"),
                    exposure_call_charm=exposure.get("call_charm"),
                    exposure_put_charm=exposure.get("put_charm"),
                )
            )
        return points

    def upsert_vanna_signal(self, signal: models.VannaSignal) -> None:
        sql = (
            f"INSERT INTO {self._schema}.vanna_signals ("
            "ticker, market_date, dealer_net_vanna_proxy, flow_color_lookback_3d, "
            "flow_put_premium_3d, flow_call_premium_3d, iv_30d_delta_5d, "
            "vanna_conditional_reading, directional_imbalance_3d, "
            "vanna_oi_change_bias, generated_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "dealer_net_vanna_proxy=EXCLUDED.dealer_net_vanna_proxy, "
            "flow_color_lookback_3d=EXCLUDED.flow_color_lookback_3d, "
            "flow_put_premium_3d=EXCLUDED.flow_put_premium_3d, "
            "flow_call_premium_3d=EXCLUDED.flow_call_premium_3d, "
            "iv_30d_delta_5d=EXCLUDED.iv_30d_delta_5d, "
            "vanna_conditional_reading=EXCLUDED.vanna_conditional_reading, "
            "directional_imbalance_3d=EXCLUDED.directional_imbalance_3d, "
            "vanna_oi_change_bias=EXCLUDED.vanna_oi_change_bias, "
            "generated_at=EXCLUDED.generated_at, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    signal.ticker.upper(),
                    signal.market_date,
                    signal.dealer_net_vanna_proxy,
                    signal.flow_color_lookback_3d,
                    signal.flow_put_premium_3d,
                    signal.flow_call_premium_3d,
                    signal.iv_30d_delta_5d,
                    signal.vanna_conditional_reading,
                    signal.directional_imbalance_3d,
                    signal.vanna_oi_change_bias,
                    signal.generated_at,
                ),
            )

    def fetch_vanna_signal(
        self, *, ticker: str, market_date: _date
    ) -> models.VannaSignal | None:
        sql = (
            "SELECT ticker, market_date, dealer_net_vanna_proxy, "
            "flow_color_lookback_3d, flow_put_premium_3d, flow_call_premium_3d, "
            "iv_30d_delta_5d, vanna_conditional_reading, directional_imbalance_3d, "
            "vanna_oi_change_bias, generated_at, inserted_at "
            f"FROM {self._schema}.vanna_signals "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return models.VannaSignal(**dict(zip(cols, row, strict=False)))

    def upsert_charm_signal(self, signal: models.CharmSignal) -> None:
        sql = (
            f"INSERT INTO {self._schema}.charm_signals ("
            "ticker, market_date, pin_candidate_strike, pin_candidate_expiry, pin_source_date, "
            "pin_distance_sigma, pin_regime_flag, dealer_net_charm_proxy, "
            "net_gamma, net_gamma_sign, gamma_regime, charm_regime, "
            "charm_stress_override, generated_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "pin_candidate_strike=EXCLUDED.pin_candidate_strike, "
            "pin_candidate_expiry=EXCLUDED.pin_candidate_expiry, "
            "pin_source_date=EXCLUDED.pin_source_date, "
            "pin_distance_sigma=EXCLUDED.pin_distance_sigma, "
            "pin_regime_flag=EXCLUDED.pin_regime_flag, "
            "dealer_net_charm_proxy=EXCLUDED.dealer_net_charm_proxy, "
            "net_gamma=EXCLUDED.net_gamma, "
            "net_gamma_sign=EXCLUDED.net_gamma_sign, "
            "gamma_regime=EXCLUDED.gamma_regime, "
            "charm_regime=EXCLUDED.charm_regime, "
            "charm_stress_override=EXCLUDED.charm_stress_override, "
            "generated_at=EXCLUDED.generated_at, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    signal.ticker.upper(),
                    signal.market_date,
                    signal.pin_candidate_strike,
                    signal.pin_candidate_expiry,
                    signal.pin_source_date,
                    signal.pin_distance_sigma,
                    signal.pin_regime_flag,
                    signal.dealer_net_charm_proxy,
                    signal.net_gamma,
                    signal.net_gamma_sign,
                    signal.gamma_regime,
                    signal.charm_regime,
                    signal.charm_stress_override,
                    signal.generated_at,
                ),
            )

    def fetch_charm_signal(
        self, *, ticker: str, market_date: _date
    ) -> models.CharmSignal | None:
        sql = (
            "SELECT ticker, market_date, pin_candidate_strike, pin_candidate_expiry, "
            "pin_source_date, pin_distance_sigma, pin_regime_flag, dealer_net_charm_proxy, "
            "net_gamma, net_gamma_sign, gamma_regime, charm_regime, "
            "charm_stress_override, generated_at, inserted_at "
            f"FROM {self._schema}.charm_signals "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return models.CharmSignal(**dict(zip(cols, row, strict=False)))

    def persist_cockpit_dealer_signals(
        self, *, ticker: str, market_date: _date, generated_at: datetime | None = None
    ) -> models.CockpitDealerMetrics:
        metrics = self._compute_cockpit_dealer_metrics(
            ticker=ticker, market_date=market_date
        )
        self.upsert_vanna_signal(
            models.VannaSignal(
                ticker=ticker,
                market_date=market_date,
                dealer_net_vanna_proxy=metrics.dealer_net_vanna_proxy,
                flow_color_lookback_3d=metrics.flow_color_lookback_3d,
                flow_put_premium_3d=metrics.flow_put_premium_3d,
                flow_call_premium_3d=metrics.flow_call_premium_3d,
                iv_30d_delta_5d=metrics.iv_30d_delta_5d,
                vanna_conditional_reading=metrics.vanna_conditional_reading,
                directional_imbalance_3d=metrics.directional_imbalance_3d,
                vanna_oi_change_bias=metrics.vanna_oi_change_bias,
                generated_at=generated_at,
            )
        )
        self.upsert_charm_signal(
            models.CharmSignal(
                ticker=ticker,
                market_date=market_date,
                pin_candidate_strike=metrics.pin_candidate_strike,
                pin_candidate_expiry=metrics.pin_candidate_expiry,
                pin_source_date=metrics.pin_source_date,
                pin_distance_sigma=metrics.pin_distance_sigma,
                pin_regime_flag=metrics.pin_regime_flag,
                dealer_net_charm_proxy=metrics.dealer_net_charm_proxy,
                net_gamma=metrics.net_gamma,
                net_gamma_sign=metrics.net_gamma_sign,
                gamma_regime=metrics.gamma_regime,
                charm_regime=metrics.charm_regime,
                charm_stress_override=metrics.charm_stress_override,
                generated_at=generated_at,
            )
        )
        return metrics

    def fetch_cockpit_dealer_metrics(
        self, *, ticker: str, market_date: _date
    ) -> models.CockpitDealerMetrics:
        vanna = self.fetch_vanna_signal(ticker=ticker, market_date=market_date)
        charm = self.fetch_charm_signal(ticker=ticker, market_date=market_date)
        computed = self._compute_cockpit_dealer_metrics(
            ticker=ticker, market_date=market_date
        )
        return models.CockpitDealerMetrics(
            pin_candidate_strike=(
                charm.pin_candidate_strike
                if charm is not None and charm.pin_candidate_strike is not None
                else computed.pin_candidate_strike
            ),
            pin_candidate_expiry=(
                charm.pin_candidate_expiry
                if charm is not None and charm.pin_candidate_expiry is not None
                else computed.pin_candidate_expiry
            ),
            pin_source_date=(
                charm.pin_source_date
                if charm is not None and charm.pin_source_date is not None
                else computed.pin_source_date
            ),
            pin_distance_sigma=(
                charm.pin_distance_sigma
                if charm is not None and charm.pin_distance_sigma is not None
                else computed.pin_distance_sigma
            ),
            pin_regime_flag=(
                charm.pin_regime_flag
                if charm is not None and charm.pin_regime_flag is not None
                else computed.pin_regime_flag
            ),
            dealer_net_vanna_proxy=(
                vanna.dealer_net_vanna_proxy
                if vanna is not None and vanna.dealer_net_vanna_proxy is not None
                else computed.dealer_net_vanna_proxy
            ),
            dealer_net_charm_proxy=(
                charm.dealer_net_charm_proxy
                if charm is not None and charm.dealer_net_charm_proxy is not None
                else computed.dealer_net_charm_proxy
            ),
            flow_color_lookback_3d=(
                vanna.flow_color_lookback_3d
                if vanna is not None and vanna.flow_color_lookback_3d is not None
                else computed.flow_color_lookback_3d
            ),
            flow_put_premium_3d=(
                vanna.flow_put_premium_3d
                if vanna is not None and vanna.flow_put_premium_3d is not None
                else computed.flow_put_premium_3d
            ),
            flow_call_premium_3d=(
                vanna.flow_call_premium_3d
                if vanna is not None and vanna.flow_call_premium_3d is not None
                else computed.flow_call_premium_3d
            ),
            iv_30d_delta_5d=(
                vanna.iv_30d_delta_5d
                if vanna is not None and vanna.iv_30d_delta_5d is not None
                else computed.iv_30d_delta_5d
            ),
            net_gamma=(
                charm.net_gamma
                if charm is not None and charm.net_gamma is not None
                else computed.net_gamma
            ),
            net_gamma_sign=(
                charm.net_gamma_sign
                if charm is not None and charm.net_gamma_sign is not None
                else computed.net_gamma_sign
            ),
            gamma_regime=(
                charm.gamma_regime
                if charm is not None and charm.gamma_regime is not None
                else computed.gamma_regime
            ),
            vanna_conditional_reading=(
                vanna.vanna_conditional_reading
                if vanna is not None and vanna.vanna_conditional_reading is not None
                else computed.vanna_conditional_reading
            ),
            directional_imbalance_3d=(
                vanna.directional_imbalance_3d
                if vanna is not None and vanna.directional_imbalance_3d is not None
                else computed.directional_imbalance_3d
            ),
            vanna_oi_change_bias=(
                vanna.vanna_oi_change_bias
                if vanna is not None and vanna.vanna_oi_change_bias is not None
                else computed.vanna_oi_change_bias
            ),
            charm_regime=(
                charm.charm_regime
                if charm is not None and charm.charm_regime is not None
                else computed.charm_regime
            ),
            charm_stress_override=(
                charm.charm_stress_override
                if charm is not None and charm.charm_stress_override is not None
                else computed.charm_stress_override
            ),
        )

    def _compute_cockpit_dealer_metrics(
        self, *, ticker: str, market_date: _date
    ) -> models.CockpitDealerMetrics:
        greeks = self.fetch_matrix_greeks_rows(ticker=ticker, market_date=market_date)
        exposures = self.fetch_matrix_exposure_rows(
            ticker=ticker, market_date=market_date
        )
        chain_rows = self.fetch_matrix_option_chain_rows(
            ticker=ticker, market_date=market_date
        )
        iv_rows = self.fetch_matrix_interpolated_iv_history(
            ticker=ticker, market_date=market_date, days=10
        )
        rv_rows = self.fetch_matrix_realized_vol_history(
            ticker=ticker, market_date=market_date, days=10
        )
        flow = self._flow_color_lookback(ticker=ticker, market_date=market_date)
        iv_rows_90d = self.fetch_matrix_interpolated_iv_history(
            ticker=ticker, market_date=market_date, days=90
        )
        oi_change_rows = self.fetch_matrix_oi_change_rows(
            ticker=ticker, market_date=market_date
        )
        return compute_cockpit_dealer_metrics(
            market_date=market_date,
            greeks_rows=greeks,
            exposure_rows=exposures,
            chain_rows=chain_rows,
            iv_rows=iv_rows,
            rv_rows=rv_rows,
            flow=flow,
            iv_rows_90d=iv_rows_90d,
            oi_change_rows=oi_change_rows,
        )

    def _flow_color_lookback(
        self, *, ticker: str, market_date: _date, days: int = 3
    ) -> dict[str, Any]:
        if days < 0:
            raise ValueError(f"days must be >= 0, got {days}")
        # Loose index scan on (ticker, created_at) (migration 155): each step of
        # the recursion is one backward probe for the latest event before the
        # previous day, so it touches about `days` days of index entries instead
        # of every flow event of the ticker (21 s on prod).
        # Day membership is always decided by ``created_at::date`` (session
        # TimeZone), exactly as before. The timestamptz bounds only narrow the
        # index range and are padded by a full day, because ``date::timestamptz``
        # can land an hour off the real start of a day where midnight repeats or
        # is skipped by a DST change.
        fe = f"{self._schema}.flow_events"
        sql = (
            "WITH RECURSIVE lookback_dates(event_date, n) AS ("
            f"  SELECT (SELECT max(created_at) FROM {fe} "
            "           WHERE ticker = %(t)s "
            "             AND created_at < (%(d)s::date + 2)::timestamptz "
            "             AND created_at::date <= %(d)s::date)::date, 1 "
            "  UNION ALL "
            f"  SELECT (SELECT max(created_at) FROM {fe} "
            "           WHERE ticker = %(t)s "
            "             AND created_at < (l.event_date + 1)::timestamptz "
            "             AND created_at::date < l.event_date)::date, l.n + 1 "
            "  FROM lookback_dates l "
            "  WHERE l.event_date IS NOT NULL AND l.n < %(days)s"
            "), days AS ("
            "  SELECT event_date FROM lookback_dates "
            "  WHERE event_date IS NOT NULL AND n <= %(days)s"
            ") "
            "SELECT option_type, "
            "COALESCE(sum(total_premium), 0), "
            "COALESCE(sum(total_ask_side_prem), 0), "
            "COALESCE(sum(total_bid_side_prem), 0) "
            f"FROM {fe} "
            "WHERE ticker = %(t)s "
            "  AND created_at >= ((SELECT min(event_date) FROM days) - 1)::timestamptz "
            "  AND created_at < (%(d)s::date + 2)::timestamptz "
            "  AND created_at::date IN (SELECT event_date FROM days) "
            "GROUP BY option_type"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, {"t": ticker.upper(), "d": market_date, "days": days})
            rows = cur.fetchall()
        return flow_color_summary(rows)

    def fetch_cockpit_surface(
        self, *, ticker: str, market_date: _date
    ) -> tuple[list[models.CockpitSkewPoint], list[models.CockpitTermPoint]]:
        skew_rows = self.fetch_matrix_skew_history(
            ticker=ticker, market_date=market_date
        )
        term_rows = self.fetch_matrix_term_rows(ticker=ticker, market_date=market_date)
        skew = [
            models.CockpitSkewPoint(
                market_date=row["market_date"],
                expiry=row.get("expiry"),
                risk_reversal=row.get("risk_reversal"),
            )
            for row in skew_rows
        ]
        term = [
            models.CockpitTermPoint(
                expiry=row["expiry"],
                dte=row.get("dte"),
                volatility=row.get("volatility"),
                implied_move_perc=row.get("implied_move_perc"),
                implied_move_expected_abs=(
                    Decimal(str(row["implied_move_perc"])) * Decimal("0.7979")
                    if row.get("implied_move_perc") is not None
                    else None
                ),
            )
            for row in term_rows
        ]
        return skew, term

    def fetch_cockpit_flow_alerts(
        self, *, ticker: str, limit: int = 25
    ) -> list[models.CockpitFlowAlert]:
        sql = (
            f"SELECT alert_id, ticker, option_chain, expiry, strike, option_type, "
            "total_premium, total_ask_side_prem, total_bid_side_prem, "
            "volume, open_interest, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, alert_rule, flow_footprint_label, "
            "aggressor_label_confidence, created_at "
            f"FROM {self._schema}.flow_events "
            "WHERE ticker = %s "
            "ORDER BY created_at DESC NULLS LAST, total_premium DESC NULLS LAST "
            "LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), limit))
            cols = [d.name for d in cur.description or []]
            rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
        return [
            models.CockpitFlowAlert(
                alert_id=str(row["alert_id"]),
                option_chain=row.get("option_chain"),
                expiry=row.get("expiry"),
                strike=row.get("strike"),
                option_type=row.get("option_type"),
                total_premium=row.get("total_premium"),
                volume=row.get("volume"),
                open_interest=row.get("open_interest"),
                total_ask_side_prem=row.get("total_ask_side_prem"),
                total_bid_side_prem=row.get("total_bid_side_prem"),
                has_sweep=row.get("has_sweep"),
                has_floor=row.get("has_floor"),
                has_multileg=row.get("has_multileg"),
                all_opening_trades=row.get("all_opening_trades"),
                alert_rule=row.get("alert_rule"),
                flow_footprint_label=row.get("flow_footprint_label"),
                aggressor_label_confidence=row.get("aggressor_label_confidence"),
                created_at=row.get("created_at"),
            )
            for row in rows
        ]

    def fetch_cockpit_implied_moves(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[models.CockpitImPoint]:
        rows = self.fetch_matrix_interpolated_iv_history(
            ticker=ticker, market_date=market_date, days=days
        )
        return [
            models.CockpitImPoint(
                market_date=row["market_date"],
                days=row["days"],
                volatility=row.get("volatility"),
                implied_move_perc=row.get("implied_move_perc"),
                implied_move_expected_abs=(
                    Decimal(str(row["implied_move_perc"])) * Decimal("0.7979")
                    if row.get("implied_move_perc") is not None
                    else None
                ),
                percentile=row.get("percentile"),
            )
            for row in rows
        ]

    def fetch_cockpit_vrp_points(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[models.CockpitVrpPoint]:
        rv_rows = self.fetch_matrix_realized_vol_history(
            ticker=ticker, market_date=market_date, days=days
        )
        iv_rank_rows = self.fetch_iv_rank_history(
            ticker=ticker, market_date=market_date, days=days
        )
        iv_rank_by_date = {
            row["market_date"]: row.get("iv_rank_1y") for row in iv_rank_rows
        }
        return [
            models.CockpitVrpPoint(
                market_date=row["market_date"],
                iv=row.get("implied_volatility"),
                rv=row.get("realized_volatility"),
                vrp=(
                    row.get("implied_volatility") - row.get("realized_volatility")
                    if row.get("implied_volatility") is not None
                    and row.get("realized_volatility") is not None
                    else None
                ),
                iv_rank_1y=iv_rank_by_date.get(row["market_date"]),
            )
            for row in rv_rows
        ]

    def fetch_iv_rank_history(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, close, volatility, iv_rank_1y, updated_at_src "
            f"FROM {self._schema}.iv_rank_history "
            "WHERE ticker = %s "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
