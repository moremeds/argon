"""Index dealer cockpit dealer metrics: pure compute over fetched rows.

``storage/cockpit.py`` fetches the rows (matrix greeks/exposure/chain/IV/RV
history, the flow-events lookback, OI changes) and hands them here. Nothing in
this module touches the database. ``cards/matrix_state.py`` reuses
``vanna_conditional_reading`` and ``oi_change_bias`` from here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

from uw_scan.models import CockpitDealerMetrics


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


def vanna_conditional_reading(
    *,
    iv_30d_delta_5d: Decimal | None,
    directional_imbalance_3d: Decimal | None,
    flow_color: str | None,
    net_gamma_sign: str | None,
) -> Literal["grind_up", "reverse_selloff", "reflexive_sell_pressure", "weak_noise"]:
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


def oi_change_bias(
    rows: list[dict[str, Any]],
) -> Literal["call_oi_build", "put_oi_build", "mixed"] | None:
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


def flow_color_summary(rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """Fold the flow-lookback ``(option_type, premium, ask_premium, bid_premium)``
    rows into the color / premiums / directional-imbalance dict."""
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


def compute_cockpit_dealer_metrics(
    *,
    market_date: _date,
    greeks_rows: list[dict[str, Any]],
    exposure_rows: list[dict[str, Any]],
    chain_rows: list[dict[str, Any]],
    iv_rows: list[dict[str, Any]],
    rv_rows: list[dict[str, Any]],
    flow: dict[str, Any],
    iv_rows_90d: list[dict[str, Any]],
    oi_change_rows: list[dict[str, Any]],
) -> CockpitDealerMetrics:
    """Derive the dealer metrics from already-fetched rows.

    ``iv_rows``/``rv_rows`` are the 10-day interpolated-IV / realized-vol
    histories, ``iv_rows_90d`` the 90-day IV history, ``flow`` the
    ``flow_color_summary`` dict.
    """
    pin_source_date = max(
        (
            row["snapshot_date"]
            for row in chain_rows
            if row.get("snapshot_date") is not None
        ),
        default=None,
    )

    chain_by_key = {
        (row["expiry"], row["strike"]): row
        for row in chain_rows
        if row.get("expiry") is not None and row.get("strike") is not None
    }
    dealer_net_vanna = Decimal(0)
    dealer_net_charm = Decimal(0)
    vanna_seen = False
    charm_seen = False
    for row in greeks_rows:
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
            (row.get("call_vanna") or Decimal(0)) + (row.get("put_vanna") or Decimal(0))
            for row in exposure_rows
            if row.get("call_vanna") is not None or row.get("put_vanna") is not None
        )
        if exposure_vanna is not None:
            dealer_net_vanna = exposure_vanna
            vanna_seen = True

    if not charm_seen:
        exposure_charm = _sum_optional(
            (row.get("call_charm") or Decimal(0)) + (row.get("put_charm") or Decimal(0))
            for row in exposure_rows
            if row.get("expiry") is not None
            and 0 <= (row["expiry"] - market_date).days <= 5
            and (row.get("call_charm") is not None or row.get("put_charm") is not None)
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
            for row in iv_rows_90d
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
        for row in exposure_rows
        if row.get("call_gex") is not None or row.get("put_gex") is not None
    )
    gamma_sign = _sign_label(net_gamma)
    charm_regime = _charm_regime(
        pin_regime=pin_regime if pin is not None else None,
        stress_override=charm_stress_override,
        pin_distance_sigma=pin_distance_sigma,
        pin_dte=(pin[0] - market_date).days if pin is not None else None,
    )
    vanna_reading = vanna_conditional_reading(
        iv_30d_delta_5d=iv_30d_delta_5d,
        directional_imbalance_3d=flow["directional_imbalance"],
        flow_color=flow["color"],
        net_gamma_sign=gamma_sign,
    )

    return CockpitDealerMetrics(
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
        vanna_oi_change_bias=oi_change_bias(oi_change_rows),
        charm_regime=charm_regime,
        charm_stress_override=charm_stress_override,
    )
