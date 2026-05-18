"""Index dealer cockpit derived dealer and surface reads."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from .. import models


def _row_for_date(
    rows: list[dict[str, Any]], market_date: _date
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("market_date") == market_date:
            return row
    return None


def _iv_delta_5d(
    *, iv_rows: list[dict[str, Any]], market_date: _date
) -> Decimal | None:
    current = _row_for_date(iv_rows, market_date)
    if current is None or current.get("volatility") is None:
        return None
    cutoff = market_date - timedelta(days=5)
    prior_rows = [
        row
        for row in iv_rows
        if row.get("market_date") is not None
        and row["market_date"] <= cutoff
        and row.get("volatility") is not None
    ]
    if not prior_rows:
        return None
    prior = max(prior_rows, key=lambda row: row["market_date"])
    return current["volatility"] - prior["volatility"]


def _pin_candidate(
    *,
    chain_rows: list[dict[str, Any]],
    spot: Decimal | None,
    market_date: _date,
) -> tuple[_date, Decimal] | None:
    candidates: list[tuple[_date, Decimal, int]] = []
    for row in chain_rows:
        expiry = row.get("expiry")
        strike = row.get("strike")
        if expiry is None or strike is None:
            continue
        dte = (expiry - market_date).days
        if dte <= 0 or dte > 5:
            continue
        strike_dec = Decimal(str(strike))
        if (
            spot is not None
            and spot > 0
            and abs(strike_dec - spot) / spot > Decimal("0.02")
        ):
            continue
        oi = int(row.get("call_oi") or 0) + int(row.get("put_oi") or 0)
        candidates.append((expiry, strike_dec, oi))
    if not candidates:
        return None
    expiry, strike, _oi = max(
        candidates,
        key=lambda item: (
            item[2],
            -abs(item[1] - spot) if spot is not None else Decimal(0),
        ),
    )
    return expiry, strike


def _pin_distance_sigma(
    *,
    spot: Decimal | None,
    strike: Decimal | None,
    iv_30d: Decimal | None,
    dte_days: int | None,
) -> Decimal | None:
    if (
        spot is None
        or strike is None
        or iv_30d is None
        or dte_days is None
        or spot <= 0
        or iv_30d <= 0
        or dte_days <= 0
    ):
        return None
    sigma_to_expiry = spot * iv_30d * (Decimal(dte_days) / Decimal(365)).sqrt()
    if sigma_to_expiry <= 0:
        return None
    return (spot - strike) / sigma_to_expiry


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def _sum_optional(values: Iterable[Decimal]) -> Decimal | None:
    seen = False
    total = Decimal(0)
    for value in values:
        seen = True
        total += value
    return total if seen else None


def _sign_label(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _vanna_conditional_reading(
    *,
    iv_30d_delta_5d: Decimal | None,
    directional_imbalance_3d: Decimal | None,
    flow_color: str | None,
    net_gamma_sign: str | None,
) -> str:
    if iv_30d_delta_5d is None or net_gamma_sign is None:
        return "weak_noise"
    flow_is_put = flow_color == "put_heavy" or (
        directional_imbalance_3d is not None and directional_imbalance_3d < 0
    )
    flow_is_call = flow_color == "call_heavy" or (
        directional_imbalance_3d is not None and directional_imbalance_3d > 0
    )
    if iv_30d_delta_5d < 0 and flow_is_put and net_gamma_sign == "positive":
        return "grind_up"
    if iv_30d_delta_5d < 0 and flow_is_call and net_gamma_sign == "positive":
        return "reverse_selloff"
    if iv_30d_delta_5d > 0 and flow_is_put and net_gamma_sign == "negative":
        return "reflexive_sell_pressure"
    return "weak_noise"


def _charm_regime(
    *,
    pin_regime: bool | None,
    stress_override: bool,
    pin_distance_sigma: Decimal | None,
    pin_dte: int | None,
) -> str:
    if pin_regime:
        return (
            "opex_vortex"
            if pin_dte is not None
            and pin_dte <= 1
            and pin_distance_sigma is not None
            and abs(pin_distance_sigma) < Decimal("0.5")
            else "operative_magnet"
        )
    if stress_override:
        return (
            "opex_vortex" if pin_dte is not None and pin_dte <= 1 else "broken_magnet"
        )
    return "neutral"


def _oi_change_bias(rows: list[dict[str, Any]]) -> str | None:
    call_oi = Decimal(0)
    put_oi = Decimal(0)
    for row in rows:
        symbol = str(row.get("option_symbol") or "")
        diff = Decimal(row.get("oi_diff_plain") or 0)
        if "C" in symbol[-9:]:
            call_oi += diff
        elif "P" in symbol[-9:]:
            put_oi += diff
    if call_oi == 0 and put_oi == 0:
        return None
    if call_oi > put_oi:
        return "call_oi_build"
    if put_oi > call_oi:
        return "put_oi_build"
    return "mixed"




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
        pin_source_date = max(
            (
                row["snapshot_date"]
                for row in chain_rows
                if row.get("snapshot_date") is not None
            ),
            default=None,
        )
        iv_rows = self.fetch_matrix_interpolated_iv_history(
            ticker=ticker, market_date=market_date, days=10
        )
        rv_rows = self.fetch_matrix_realized_vol_history(
            ticker=ticker, market_date=market_date, days=10
        )
        flow = self._flow_color_lookback(ticker=ticker, market_date=market_date)

        chain_by_key = {
            (row["expiry"], row["strike"]): row
            for row in chain_rows
            if row.get("expiry") is not None and row.get("strike") is not None
        }
        dealer_net_vanna = Decimal(0)
        dealer_net_charm = Decimal(0)
        vanna_seen = False
        charm_seen = False
        for row in greeks:
            key = (row.get("expiry"), row.get("strike"))
            chain = chain_by_key.get(key)
            if chain is None:
                continue
            call_oi = Decimal(chain.get("call_oi") or 0)
            put_oi = Decimal(chain.get("put_oi") or 0)
            if row.get("call_vanna") is not None or row.get("put_vanna") is not None:
                dealer_net_vanna += (
                    (row.get("call_vanna") or Decimal(0)) * call_oi
                    - (row.get("put_vanna") or Decimal(0)) * put_oi
                ) * Decimal(100)
                vanna_seen = True
            expiry = row.get("expiry")
            near_expiry = expiry is not None and 0 <= (expiry - market_date).days <= 5
            if near_expiry and (
                row.get("call_charm") is not None or row.get("put_charm") is not None
            ):
                dealer_net_charm += (
                    (row.get("call_charm") or Decimal(0)) * call_oi
                    - (row.get("put_charm") or Decimal(0)) * put_oi
                ) * Decimal(100)
                charm_seen = True

        if not vanna_seen:
            exposure_vanna = _sum_optional(
                (row.get("call_vanna") or Decimal(0))
                + (row.get("put_vanna") or Decimal(0))
                for row in exposures
                if row.get("call_vanna") is not None or row.get("put_vanna") is not None
            )
            if exposure_vanna is not None:
                dealer_net_vanna = exposure_vanna
                vanna_seen = True

        if not charm_seen:
            exposure_charm = _sum_optional(
                (row.get("call_charm") or Decimal(0))
                + (row.get("put_charm") or Decimal(0))
                for row in exposures
                if row.get("expiry") is not None
                and 0 <= (row["expiry"] - market_date).days <= 5
                and (
                    row.get("call_charm") is not None
                    or row.get("put_charm") is not None
                )
            )
            if exposure_charm is not None:
                dealer_net_charm = exposure_charm
                charm_seen = True

        spot = _row_for_date(rv_rows, market_date)
        spot_price = None if spot is None else spot.get("price")
        current_iv = _row_for_date(iv_rows, market_date)
        iv_30d = None if current_iv is None else current_iv.get("volatility")
        iv_30d_delta_5d = _iv_delta_5d(iv_rows=iv_rows, market_date=market_date)
        pin = _pin_candidate(
            chain_rows=chain_rows, spot=spot_price, market_date=market_date
        )
        pin_distance_sigma = (
            _pin_distance_sigma(
                spot=spot_price,
                strike=pin[1] if pin is not None else None,
                iv_30d=iv_30d,
                dte_days=(pin[0] - market_date).days if pin is not None else None,
            )
            if pin is not None
            else None
        )
        iv_median_90d = _median(
            [
                row.get("volatility")
                for row in self.fetch_matrix_interpolated_iv_history(
                    ticker=ticker, market_date=market_date, days=90
                )
                if row.get("volatility") is not None
            ]
        )
        pin_regime = (
            iv_30d is not None
            and iv_median_90d is not None
            and pin_distance_sigma is not None
            and pin is not None
            and (pin[0] - market_date).days <= 5
            and abs(pin_distance_sigma) < Decimal("1.0")
            and iv_30d < iv_median_90d
        )
        charm_stress_override = bool(
            iv_30d is not None
            and iv_median_90d is not None
            and pin_distance_sigma is not None
            and iv_30d > iv_median_90d
            and abs(pin_distance_sigma) >= Decimal("1.0")
        )
        net_gamma = _sum_optional(
            (row.get("call_gex") or Decimal(0)) + (row.get("put_gex") or Decimal(0))
            for row in exposures
            if row.get("call_gex") is not None or row.get("put_gex") is not None
        )
        gamma_sign = _sign_label(net_gamma)
        charm_regime = _charm_regime(
            pin_regime=pin_regime if pin is not None else None,
            stress_override=charm_stress_override,
            pin_distance_sigma=pin_distance_sigma,
            pin_dte=(pin[0] - market_date).days if pin is not None else None,
        )
        vanna_reading = _vanna_conditional_reading(
            iv_30d_delta_5d=iv_30d_delta_5d,
            directional_imbalance_3d=flow["directional_imbalance"],
            flow_color=flow["color"],
            net_gamma_sign=gamma_sign,
        )

        return models.CockpitDealerMetrics(
            pin_candidate_strike=pin[1] if pin is not None else None,
            pin_candidate_expiry=pin[0] if pin is not None else None,
            pin_source_date=pin_source_date,
            pin_distance_sigma=pin_distance_sigma,
            pin_regime_flag=pin_regime if pin is not None else None,
            dealer_net_vanna_proxy=dealer_net_vanna if vanna_seen else None,
            dealer_net_charm_proxy=dealer_net_charm if charm_seen else None,
            flow_color_lookback_3d=flow["color"],
            flow_put_premium_3d=flow["put_premium"],
            flow_call_premium_3d=flow["call_premium"],
            iv_30d_delta_5d=iv_30d_delta_5d,
            net_gamma=net_gamma,
            net_gamma_sign=gamma_sign,
            gamma_regime=(
                "long_gamma"
                if gamma_sign == "positive"
                else "short_gamma"
                if gamma_sign == "negative"
                else "neutral"
                if gamma_sign == "neutral"
                else None
            ),
            vanna_conditional_reading=vanna_reading,
            directional_imbalance_3d=flow["directional_imbalance"],
            vanna_oi_change_bias=_oi_change_bias(
                self.fetch_matrix_oi_change_rows(ticker=ticker, market_date=market_date)
            ),
            charm_regime=charm_regime,
            charm_stress_override=charm_stress_override,
        )

    def _flow_color_lookback(
        self, *, ticker: str, market_date: _date, days: int = 3
    ) -> dict[str, Any]:
        sql = (
            "WITH lookback_dates AS ("
            "  SELECT DISTINCT created_at::date AS event_date "
            f"  FROM {self._schema}.flow_events "
            "  WHERE ticker = %s "
            "    AND created_at::date <= %s "
            "  ORDER BY event_date DESC "
            "  LIMIT %s"
            ") "
            "SELECT option_type, "
            "COALESCE(sum(total_premium), 0), "
            "COALESCE(sum(total_ask_side_prem), 0), "
            "COALESCE(sum(total_bid_side_prem), 0) "
            f"FROM {self._schema}.flow_events "
            "WHERE ticker = %s "
            "  AND created_at::date IN (SELECT event_date FROM lookback_dates) "
            "GROUP BY option_type"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date, days, ticker.upper()))
            rows = cur.fetchall()
        call_premium = Decimal(0)
        put_premium = Decimal(0)
        call_net = Decimal(0)
        put_net = Decimal(0)
        for option_type, premium, ask_premium, bid_premium in rows:
            premium = premium or Decimal(0)
            ask_premium = ask_premium or Decimal(0)
            bid_premium = bid_premium or Decimal(0)
            net_side = (
                ask_premium - bid_premium
                if ask_premium != 0 or bid_premium != 0
                else premium
            )
            if option_type == "call":
                call_premium += premium
                call_net += net_side
            elif option_type == "put":
                put_premium += premium
                put_net += net_side
        if not rows:
            color = None
        elif put_premium > call_premium:
            color = "put_heavy"
        elif call_premium > put_premium:
            color = "call_heavy"
        else:
            color = "neutral"
        return {
            "color": color,
            "put_premium": put_premium if rows else None,
            "call_premium": call_premium if rows else None,
            "directional_imbalance": call_net - put_net if rows else None,
        }

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
