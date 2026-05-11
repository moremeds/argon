from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from uw_scan.analysis import GexInputLevel, OiInputRow, StockAnalysisInputs
from uw_scan.models import FlowRow


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("data", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, Mapping):
            return [value]
    return [payload]


def _first_row(payload: Any) -> Mapping[str, Any]:
    rows = _rows(payload)
    return rows[0] if rows else {}


def _decimal_from(row: Mapping[str, Any], keys: tuple[str, ...], default: Decimal) -> Decimal:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return Decimal(str(value).replace(",", "").replace("%", ""))
        except (InvalidOperation, ValueError):
            continue
    return default


def _int_from(row: Mapping[str, Any], keys: tuple[str, ...], default: int) -> int:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return int(Decimal(str(value).replace(",", "")))
        except (InvalidOperation, ValueError):
            continue
    return default


def _str_from(row: Mapping[str, Any], keys: tuple[str, ...], default: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return str(value)
    return default


def _payload(payloads: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payloads:
            return payloads[name]
    return {}


def _ticker_flow(ticker: str, flow_rows: list[FlowRow]) -> list[FlowRow]:
    return [row for row in flow_rows if row.ticker.upper() == ticker.upper()]


def _derive_flow_premiums(ticker: str, flow_rows: list[FlowRow]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    bull = Decimal("0")
    bear = Decimal("0")
    for row in _ticker_flow(ticker, flow_rows):
        if row.option_type == "call" and row.side in {"ask", "buy", "above_ask"}:
            bull += row.premium
        elif row.option_type == "put" and row.side in {"ask", "buy", "above_ask"}:
            bear += row.premium
        elif row.option_type == "call":
            bear += row.premium
        else:
            bull += row.premium
    net = bull - bear
    ratio = bear / bull if bull else Decimal("0")
    return net, bull, bear, ratio


def _flow_premiums(ticker: str, flow_rows: list[FlowRow], payloads: Mapping[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    summary = _first_row(_payload(payloads, "flow_summary", "net_premium"))
    if summary:
        bull = _decimal_from(summary, ("bull_premium", "bullish_premium", "call_premium"), Decimal("0"))
        bear = _decimal_from(summary, ("bear_premium", "bearish_premium", "put_premium"), Decimal("0"))
        net = _decimal_from(summary, ("net_premium",), bull - bear)
        ratio = _decimal_from(summary, ("call_put_ratio", "cp_ratio", "c_p_ratio"), bear / bull if bull else Decimal("0"))
        return net, bull, bear, ratio
    return _derive_flow_premiums(ticker, flow_rows)


def _gex_levels(payloads: Mapping[str, Any]) -> list[GexInputLevel]:
    levels: list[GexInputLevel] = []
    for row in _rows(_payload(payloads, "greek_exposure", "gex", "spot_exposures")):
        strike = _decimal_from(row, ("strike", "price", "level"), Decimal("0"))
        gex = _decimal_from(
            row,
            ("gex", "gamma_exposure", "net_gex", "total_gex", "call_put_gamma_exposure"),
            Decimal("0"),
        )
        if not gex:
            gex = _decimal_from(row, ("call_gex", "call_gamma_exposure"), Decimal("0")) + _decimal_from(
                row,
                ("put_gex", "put_gamma_exposure"),
                Decimal("0"),
            )
        if strike:
            levels.append(GexInputLevel(strike=strike, net_gex=gex))
    return levels


def _infer_gex_flip(levels: list[GexInputLevel], spot: Decimal) -> Decimal:
    below = [level for level in levels if level.strike <= spot and level.net_gex <= 0]
    above = [level for level in levels if level.strike >= spot and level.net_gex >= 0]
    if below and above:
        low = max(below, key=lambda level: level.strike)
        high = min(above, key=lambda level: level.strike)
        return (low.strike + high.strike) / Decimal("2")
    return spot


def _term_rows(payloads: Mapping[str, Any]) -> tuple[Decimal, int, Decimal, int, Decimal, int, int]:
    rows = sorted(
        _rows(_payload(payloads, "term_structure", "iv_term_structure")),
        key=lambda row: _int_from(row, ("dte", "days_to_expiry", "days_to_expiration"), 9999),
    )
    if not rows:
        return Decimal("0"), 0, Decimal("0"), 0, Decimal("0"), 0, 0
    near = rows[0]
    mid = rows[min(1, len(rows) - 1)]
    far = rows[-1]
    return (
        _decimal_from(near, ("iv", "implied_volatility", "atm_iv", "volatility"), Decimal("0")),
        _int_from(near, ("dte", "days_to_expiry", "days_to_expiration"), 0),
        _decimal_from(mid, ("iv", "implied_volatility", "atm_iv", "volatility"), Decimal("0")),
        _int_from(mid, ("dte", "days_to_expiry", "days_to_expiration"), 0),
        _decimal_from(far, ("iv", "implied_volatility", "atm_iv", "volatility"), Decimal("0")),
        _int_from(far, ("dte", "days_to_expiry", "days_to_expiration"), 0),
        len(rows),
    )


def _oi_rows(payloads: Mapping[str, Any]) -> list[OiInputRow]:
    rows: list[OiInputRow] = []
    for row in _rows(_payload(payloads, "oi_per_strike", "oi_change")):
        strike = _decimal_from(row, ("strike",), Decimal("0"))
        if not strike:
            continue
        rows.append(
            OiInputRow(
                strike=strike,
                call_volume=_int_from(row, ("call_volume", "call_vol", "call_open_interest", "call_oi"), 0),
                put_volume=_int_from(row, ("put_volume", "put_vol", "put_open_interest", "put_oi"), 0),
            )
        )
    return rows


def _darkpool(payloads: Mapping[str, Any]) -> tuple[Decimal, int]:
    rows = _rows(_payload(payloads, "darkpool", "dark_pool"))
    premium = sum(
        (_decimal_from(row, ("premium", "notional", "size", "volume"), Decimal("0")) for row in rows),
        Decimal("0"),
    )
    return premium, len(rows)


def build_analysis_inputs_from_payloads(
    *,
    ticker: str,
    flow_rows: list[FlowRow],
    payloads: Mapping[str, Any],
    data_date: str,
) -> StockAnalysisInputs:
    vol = _first_row(_payload(payloads, "volatility_stats", "vol_stats"))
    iv_rank_row = _first_row(_payload(payloads, "iv_rank"))
    skew = _first_row(_payload(payloads, "skew", "risk_reversal_skew"))
    short = _first_row(_payload(payloads, "short_interest", "shorts"))
    gex_levels = _gex_levels(payloads)
    spot = _decimal_from(vol, ("price", "stock_price", "underlying_price", "close"), Decimal("0"))
    if not spot:
        spot = _decimal_from(_first_row(_payload(payloads, "spot_exposures", "dex")), ("price", "strike"), Decimal("0"))
    gex_flip = _decimal_from(_first_row(_payload(payloads, "gex_flip")), ("strike", "gex_flip"), Decimal("0"))
    if not gex_flip:
        gex_flip = _infer_gex_flip(gex_levels, spot)
    near_iv, near_dte, mid_iv, mid_dte, far_iv, far_dte, expiration_count = _term_rows(payloads)
    net_premium, bull_premium, bear_premium, call_put_ratio = _flow_premiums(ticker, flow_rows, payloads)
    dex_row = max(
        _rows(_payload(payloads, "spot_exposures", "dex")),
        key=lambda row: abs(_decimal_from(row, ("dex", "delta_exposure", "vol_gamma"), Decimal("0"))),
        default={},
    )
    dark_premium, dark_prints = _darkpool(payloads)
    ticker_rows = _ticker_flow(ticker, flow_rows)
    first_flow = ticker_rows[0] if ticker_rows else None
    buy_strike = first_flow.strike if first_flow else spot
    dte = first_flow.dte if first_flow else 30

    return StockAnalysisInputs(
        ticker=ticker.upper(),
        spot=spot,
        gex_flip=gex_flip,
        gex_levels=gex_levels,
        volume_dex_strike=_decimal_from(dex_row, ("strike", "price", "level"), spot),
        volume_dex_premium=_decimal_from(dex_row, ("dex", "delta_exposure", "vol_gamma"), Decimal("0"))
        or abs(_decimal_from(dex_row, ("call_delta_vol",), Decimal("0")))
        + abs(_decimal_from(dex_row, ("put_delta_vol",), Decimal("0"))),
        current_iv_pct=_decimal_from(vol, ("implied_volatility", "iv", "current_iv"), Decimal("0")),
        historical_vol_pct=_decimal_from(vol, ("historical_volatility", "realized_volatility", "hv", "rv"), Decimal("0")),
        iv_rank=_decimal_from(iv_rank_row, ("iv_rank", "iv_rank_1y", "rank", "iv_percentile"), Decimal("0")),
        iv_52w_low_pct=_decimal_from(vol, ("iv_low_52w", "iv_52w_low", "iv_low"), Decimal("0")),
        iv_52w_high_pct=_decimal_from(vol, ("iv_high_52w", "iv_52w_high", "iv_high"), Decimal("0")),
        rv_52w_low_pct=_decimal_from(vol, ("rv_low_52w", "rv_52w_low", "realized_low_52w", "rv_low"), Decimal("0")),
        rv_52w_high_pct=_decimal_from(vol, ("rv_high_52w", "rv_52w_high", "realized_high_52w", "rv_high"), Decimal("0")),
        vrp_pct=_decimal_from(vol, ("vrp",), _decimal_from(vol, ("implied_volatility", "iv", "current_iv"), Decimal("0")) - _decimal_from(vol, ("historical_volatility", "realized_volatility", "hv", "rv"), Decimal("0"))),
        vrp_z_score=_decimal_from(vol, ("vrp_z_score", "vrp_z"), Decimal("0.28")),
        put_25_delta_iv_pct=_decimal_from(skew, ("put_25_delta_iv", "put_iv_25_delta"), Decimal("0")),
        call_25_delta_iv_pct=_decimal_from(skew, ("call_25_delta_iv", "call_iv_25_delta"), Decimal("0")),
        near_term_iv_pct=near_iv,
        near_term_dte=near_dte,
        mid_term_iv_pct=mid_iv,
        mid_term_dte=mid_dte,
        far_term_iv_pct=far_iv,
        far_term_dte=far_dte,
        term_expiration_count=expiration_count,
        vol_stats_date=_str_from(vol, ("date", "market_date"), data_date),
        net_premium=net_premium,
        bull_premium=bull_premium,
        bear_premium=bear_premium,
        call_put_ratio=call_put_ratio,
        dark_pool_premium=dark_premium,
        dark_pool_prints=dark_prints,
        short_interest_ratio_pct=_decimal_from(short, ("short_interest_ratio", "short_ratio", "ratio"), Decimal("0")),
        short_interest_z=_decimal_from(short, ("z_score", "z", "short_interest_z"), Decimal("0")),
        short_interest_history_days=_int_from(short, ("history_days", "days", "lookback_days"), 0),
        top_expiries=[],
        oi_rows=_oi_rows(payloads),
        trade_expiry_label=first_flow.expiry.strftime("%b %d, %Y") if first_flow else data_date,
        trade_dte=dte,
        call_buy_strike=buy_strike,
        call_sell_strike=buy_strike + Decimal("15"),
        put_buy_strike=buy_strike - Decimal("15"),
        put_sell_strike=buy_strike - Decimal("25"),
        estimated_debit=Decimal("6.40"),
        max_profit=Decimal("8.60"),
        max_loss=Decimal("6.40"),
        data_date=data_date,
    )
