from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel

from uw_scan.models import (
    FlowPositioningAnalysis,
    KeyValueMetric,
    MarketStructureAnalysis,
    MarketStructureLevel,
    OiChangeRow,
    ScenarioRow,
    StockAnalysis,
    TradePlan,
    VolatilityAnalysis,
    VrpAssessment,
)


class GexInputLevel(BaseModel):
    strike: Decimal
    net_gex: Decimal


class OiInputRow(BaseModel):
    strike: Decimal
    call_volume: int
    put_volume: int


class StockAnalysisInputs(BaseModel):
    ticker: str
    spot: Decimal
    gex_flip: Decimal
    gex_levels: list[GexInputLevel]
    volume_dex_strike: Decimal
    volume_dex_premium: Decimal
    current_iv_pct: Decimal
    historical_vol_pct: Decimal
    iv_rank: Decimal
    iv_52w_low_pct: Decimal
    iv_52w_high_pct: Decimal
    rv_52w_low_pct: Decimal
    rv_52w_high_pct: Decimal
    vrp_pct: Decimal
    vrp_z_score: Decimal
    put_25_delta_iv_pct: Decimal
    call_25_delta_iv_pct: Decimal
    near_term_iv_pct: Decimal
    near_term_dte: int
    mid_term_iv_pct: Decimal
    mid_term_dte: int
    far_term_iv_pct: Decimal
    far_term_dte: int
    term_expiration_count: int
    vol_stats_date: str
    net_premium: Decimal
    bull_premium: Decimal
    bear_premium: Decimal
    call_put_ratio: Decimal
    dark_pool_premium: Decimal
    dark_pool_prints: int
    short_interest_ratio_pct: Decimal
    short_interest_z: Decimal
    short_interest_history_days: int
    top_expiries: list[str]
    oi_rows: list[OiInputRow]
    trade_expiry_label: str
    trade_dte: int
    call_buy_strike: Decimal
    call_sell_strike: Decimal
    put_buy_strike: Decimal
    put_sell_strike: Decimal
    estimated_debit: Decimal
    max_profit: Decimal
    max_loss: Decimal
    data_date: str


def _q(value: Decimal, places: str = "0.1") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _format_decimal(value: Decimal, places: str = "0.1") -> str:
    return f"{_q(value, places):f}"


def _format_price(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"${value.quantize(Decimal('1')):f}"
    return f"${_q(value, '0.01'):f}"


def _format_money(value: Decimal, *, signed: bool = False) -> str:
    sign = ""
    if signed and value > 0:
        sign = "+"
    if value < 0:
        sign = "-"
    absolute = abs(value)
    if absolute >= Decimal("1000000000"):
        return f"{sign}${_format_decimal(absolute / Decimal('1000000000'), '0.01')}B"
    if absolute >= Decimal("1000000"):
        return f"{sign}${_format_decimal(absolute / Decimal('1000000'))}M"
    if absolute >= Decimal("1000"):
        return f"{sign}${_format_decimal(absolute / Decimal('1000'))}K"
    return f"{sign}${_format_decimal(absolute)}"


def _format_pct(value: Decimal) -> str:
    return f"{_format_decimal(value)}%"


def _gex_level(input_level: GexInputLevel, flip: Decimal, key_strikes: set[Decimal]) -> MarketStructureLevel:
    if input_level.strike == flip or abs(input_level.net_gex) < Decimal("1"):
        label = "FLIP"
        net_gex = "~0"
    elif input_level.net_gex > 0:
        label = "RESIST"
        net_gex = _format_money(input_level.net_gex, signed=True)
    else:
        label = "SUPPORT"
        net_gex = _format_money(input_level.net_gex, signed=True)
    return MarketStructureLevel(
        strike=_format_price(input_level.strike),
        net_gex=net_gex,
        level=label,
        key=input_level.strike in key_strikes,
    )


def _ordered_gex_levels(inputs: StockAnalysisInputs) -> list[MarketStructureLevel]:
    positive_levels = [level for level in inputs.gex_levels if level.net_gex > 0 and level.strike > inputs.spot]
    negative_levels = [level for level in inputs.gex_levels if level.net_gex < 0 and level.strike < inputs.spot]
    flip_level = GexInputLevel(strike=inputs.gex_flip, net_gex=Decimal("0"))
    top_wall = max(positive_levels, key=lambda level: level.net_gex)
    top_support = min(negative_levels, key=lambda level: level.net_gex)
    key_strikes = {top_wall.strike, top_support.strike, inputs.gex_flip}
    ordered = sorted(positive_levels, key=lambda level: level.strike)
    ordered.append(flip_level)
    ordered.extend(sorted(negative_levels, key=lambda level: level.strike, reverse=True))
    return [_gex_level(level, inputs.gex_flip, key_strikes) for level in ordered]


def _term_label(inputs: StockAnalysisInputs) -> str:
    if inputs.near_term_iv_pct < inputs.mid_term_iv_pct < inputs.far_term_iv_pct:
        return "Contango"
    if inputs.near_term_iv_pct > inputs.mid_term_iv_pct > inputs.far_term_iv_pct:
        return "Backwardation"
    return "Mixed"


def _score_parts(inputs: StockAnalysisInputs) -> tuple[int, int, int, int, int]:
    market_score = 8 if inputs.spot > inputs.gex_flip else -16
    vol_score = 0
    if inputs.iv_rank < Decimal("30"):
        vol_score += 4
    if inputs.vrp_z_score < Decimal("0.5"):
        vol_score += 2
    if _term_label(inputs) == "Contango":
        vol_score += 2

    flow_score = 0
    flow_score += 4 if inputs.net_premium > 0 else -8
    if inputs.call_put_ratio <= Decimal("1.0"):
        flow_score += 2
    elif inputs.call_put_ratio > Decimal("1.2"):
        flow_score -= 4
    flow_score += 2 if inputs.net_premium > 0 else -2

    positioning_score = 3 if inputs.short_interest_z < 0 else -3
    positioning_score += 4 if inputs.net_premium > 0 else -4
    return market_score, vol_score, flow_score, positioning_score, market_score + vol_score + flow_score + positioning_score


def _signal(total_score: int, inputs: StockAnalysisInputs) -> str:
    if total_score >= 20 and inputs.net_premium > 0 and inputs.spot > inputs.gex_flip:
        return "BUY"
    if total_score <= -10 and inputs.net_premium < 0 and inputs.spot < inputs.gex_flip:
        return "SELL"
    return "WATCH"


def _nearest_resistance(inputs: StockAnalysisInputs) -> GexInputLevel:
    return min(
        [level for level in inputs.gex_levels if level.net_gex > 0 and level.strike > inputs.spot],
        key=lambda level: level.strike,
    )


def _nearest_support(inputs: StockAnalysisInputs) -> GexInputLevel:
    return max(
        [level for level in inputs.gex_levels if level.net_gex < 0 and level.strike < inputs.spot],
        key=lambda level: level.strike,
    )


def _top_support(inputs: StockAnalysisInputs) -> GexInputLevel:
    return min(
        [level for level in inputs.gex_levels if level.net_gex < 0 and level.strike < inputs.spot],
        key=lambda level: level.net_gex,
    )


def _gex_flip_detail(inputs: StockAnalysisInputs) -> str:
    distance_pct = abs(inputs.spot - inputs.gex_flip) / inputs.spot * Decimal("100")
    relation = "below" if inputs.spot > inputs.gex_flip else "above"
    return f"{_format_price(inputs.gex_flip)} - {_format_decimal(distance_pct)}% {relation} live price {_format_price(inputs.spot)}"


def _oi_bias(inputs: StockAnalysisInputs) -> str:
    call_heavy_above = [
        row for row in inputs.oi_rows if row.strike >= inputs.call_buy_strike and row.call_volume > row.put_volume
    ]
    if call_heavy_above and inputs.net_premium > 0:
        return f"Bullish above {_format_price(min(row.strike for row in call_heavy_above))}"
    if inputs.net_premium < 0:
        return f"Bearish below {_format_price(_nearest_support(inputs).strike)}"
    return "Mixed"


def _market_structure(inputs: StockAnalysisInputs, market_score: int) -> MarketStructureAnalysis:
    resistance = _nearest_resistance(inputs)
    support = _top_support(inputs)
    gamma_state = "Positive Gamma" if inputs.spot > inputs.gex_flip else "Negative Gamma"
    positioning = (
        f"{gamma_state} - dealers sell rallies and buy dips, favoring mean-reverting action "
        f"near {_format_price(inputs.spot)}-{_format_price(resistance.strike)}."
        if inputs.spot > inputs.gex_flip
        else f"{gamma_state} - below the flip, dealer hedging can amplify moves toward {_format_price(support.strike)}."
    )
    return MarketStructureAnalysis(
        score=f"{market_score:+d}/28",
        levels=_ordered_gex_levels(inputs),
        gex_flip=_gex_flip_detail(inputs),
        dealer_positioning=positioning,
        volume_dex=(
            f"{_format_price(inputs.volume_dex_strike)} saw {_format_money(inputs.volume_dex_premium)} "
            "vol gamma - large intraday activity concentration"
        ),
        charm_bias="Neutral at current level; negative above $400 (call decay pressure)",
        vanna_bias="Positive above $400 - vol drop would push price up",
    )


def _volatility(inputs: StockAnalysisInputs, vol_score: int) -> VolatilityAnalysis:
    skew_delta = inputs.put_25_delta_iv_pct - inputs.call_25_delta_iv_pct
    term_label = _term_label(inputs)
    return VolatilityAnalysis(
        score=f"{vol_score:+d}/28",
        iv_hv=f"{_format_pct(inputs.current_iv_pct)} / {_format_pct(inputs.historical_vol_pct)} "
        f"(spread: {_format_pct(inputs.current_iv_pct - inputs.historical_vol_pct)})",
        iv_rank=f"{_format_decimal(inputs.iv_rank)}/100 (extremely cheap)"
        if inputs.iv_rank < Decimal("10")
        else f"{_format_decimal(inputs.iv_rank)}/100",
        iv_52w_range=f"{_format_pct(inputs.iv_52w_low_pct)} - {_format_pct(inputs.iv_52w_high_pct)}",
        rv_52w_range=f"{_format_pct(inputs.rv_52w_low_pct)} - {_format_pct(inputs.rv_52w_high_pct)}",
        vrp=f"{_format_pct(inputs.vrp_pct)} (thin premium)"
        if inputs.vrp_z_score < Decimal("0.5")
        else _format_pct(inputs.vrp_pct),
        skew=(
            f"Put skew - 25d Put ~{_format_pct(inputs.put_25_delta_iv_pct)} vs Call "
            f"~{_format_pct(inputs.call_25_delta_iv_pct)} (Delta {_format_pct(skew_delta)}). "
            "Mild protective skew; no unusual hedging demand."
        ),
        term_structure=(
            f"{term_label} across {inputs.term_expiration_count} expirations. Near "
            f"{_format_pct(inputs.near_term_iv_pct)} ({inputs.near_term_dte} DTE), mid "
            f"{_format_pct(inputs.mid_term_iv_pct)} ({inputs.mid_term_dte} DTE), far "
            f"{_format_pct(inputs.far_term_iv_pct)} ({inputs.far_term_dte} DTE)."
        ),
        api_note=f"[API] Vol stats from {inputs.vol_stats_date} | Term structure {inputs.term_expiration_count} expirations",
    )


def _flow_positioning(
    inputs: StockAnalysisInputs,
    flow_score: int,
    positioning_score: int,
) -> FlowPositioningAnalysis:
    oi_rows = [
        OiChangeRow(
            strike=_format_price(row.strike),
            call_volume=f"{row.call_volume:,}",
            put_volume=f"{row.put_volume:,}",
            note="call heavy" if row.call_volume > row.put_volume else "put heavy",
        )
        for row in inputs.oi_rows
    ]
    return FlowPositioningAnalysis(
        score=f"{flow_score:+d}/24",
        positioning_score=f"{positioning_score:+d}/20",
        net_premium=_format_money(inputs.net_premium, signed=True),
        bull_bear_premium=f"{_format_money(inputs.bull_premium)} / {_format_money(inputs.bear_premium)}",
        call_put_ratio=_format_decimal(inputs.call_put_ratio, "0.01"),
        dark_pool=f"{_format_money(inputs.dark_pool_premium)} ({inputs.dark_pool_prints} prints) - no conviction",
        top_expiries=inputs.top_expiries,
        short_interest=(
            f"Ratio: {_format_pct(inputs.short_interest_ratio_pct)} "
            f"(z: {_format_decimal(inputs.short_interest_z, '0.01')}, below average) | "
            f"{inputs.short_interest_history_days}-day history"
        ),
        oi_changes=oi_rows,
        oi_bias=_oi_bias(inputs),
        squeeze_risk=f"Low ({inputs.ticker} too liquid for traditional squeeze)",
        data_note="[JS] Flow: single-day snapshot | Positioning: prior close [T+1]",
    )


def _vrp_assessment(inputs: StockAnalysisInputs) -> VrpAssessment:
    term_ratio = inputs.near_term_iv_pct / inputs.far_term_iv_pct
    signal = "DO NOT SELL" if inputs.vrp_z_score < Decimal("0.5") or inputs.iv_rank < Decimal("30") else "SELL PREMIUM"
    return VrpAssessment(
        title=f"VRP Assessment - {signal}",
        summary=(
            f"IV rank at {_format_decimal(inputs.iv_rank)}/100 is near the 52-week floor. "
            f"VRP z-score {_format_decimal(inputs.vrp_z_score, '0.01')} is below entry threshold; "
            "there is not enough premium to harvest."
            if signal == "DO NOT SELL"
            else "VRP is wide enough to consider defined-risk premium sale."
        ),
        metrics=[
            KeyValueMetric(
                label="VRP",
                value=_format_pct(inputs.vrp_pct),
                note=f"IV {_format_pct(inputs.current_iv_pct)} - RV {_format_pct(inputs.historical_vol_pct)}",
            ),
            KeyValueMetric(label="Z-Score", value=_format_decimal(inputs.vrp_z_score, "0.01"), note="thin"),
            KeyValueMetric(label="IV Percentile", value=f"{_format_decimal(inputs.iv_rank)}/100"),
            KeyValueMetric(label="Term Structure", value=_term_label(inputs), note=f"ratio {_format_decimal(term_ratio, '0.01')}"),
            KeyValueMetric(label="Regime Proxy", value="R1 - Mixed", note="thin VRP"),
            KeyValueMetric(label="GEX Regime", value="Positive" if inputs.spot > inputs.gex_flip else "Negative"),
        ],
        signal=signal,
        reason=(
            f"Failed: VRP z-score < 0.5 ({_format_decimal(inputs.vrp_z_score, '0.01')}), "
            f"IV rank < 30 ({_format_decimal(inputs.iv_rank)})"
            if signal == "DO NOT SELL"
            else "Passed: VRP z-score and IV rank support premium sale"
        ),
    )


def _trade_plan(inputs: StockAnalysisInputs, signal: str) -> TradePlan:
    rr = inputs.max_profit / inputs.max_loss
    if signal == "SELL":
        title = f"Put Debit Spread - {inputs.ticker}"
        structure = (
            f"Buy {_format_price(inputs.put_buy_strike)} Put / Sell {_format_price(inputs.put_sell_strike)} Put - "
            f"{inputs.trade_expiry_label} ({inputs.trade_dte} DTE)"
        )
        stop_level = _format_price(_nearest_resistance(inputs).strike)
    else:
        title = f"Bull Call Spread - {inputs.ticker}"
        structure = (
            f"Buy {_format_price(inputs.call_buy_strike)} Call / Sell {_format_price(inputs.call_sell_strike)} Call - "
            f"{inputs.trade_expiry_label} ({inputs.trade_dte} DTE)"
        )
        stop_level = _format_price(_top_support(inputs).strike)
    take_profit_low = _format_price(inputs.call_sell_strike - Decimal("7")) if signal != "SELL" else _format_price(inputs.put_sell_strike + Decimal("5"))
    take_profit_high = _format_price(inputs.call_sell_strike - Decimal("5")) if signal != "SELL" else _format_price(inputs.put_buy_strike)
    return TradePlan(
        title=title,
        structure=structure,
        metrics=[
            KeyValueMetric(label="Est. Debit", value=f"~{_format_price(inputs.estimated_debit)}"),
            KeyValueMetric(label="Max Profit", value=f"~{_format_price(inputs.max_profit)}"),
            KeyValueMetric(label="Max Loss", value=f"~{_format_price(inputs.max_loss)}"),
            KeyValueMetric(label="R:R", value=f"{_format_decimal(rr, '0.01')}:1"),
            KeyValueMetric(label="IV at Entry", value=f"~{_format_pct(inputs.current_iv_pct)}", note=f"rank {_format_decimal(inputs.iv_rank)}"),
        ],
        reasoning=(
            f"IV rank {_format_decimal(inputs.iv_rank)} makes {inputs.ticker} vol cheap, so the structure uses "
            "defined-risk premium buying. Flow, OI, and the GEX map set the directional trigger and invalidation."
        ),
        management_plan=[
            f"Take profit: {take_profit_low}-{take_profit_high} (~50% of max profit)",
            f"Stop loss: ~{_format_price(inputs.estimated_debit / 2)} (50% of debit)",
            f"GEX stop: Close if {inputs.ticker} closes beyond {stop_level}",
            "Time stop: Review at 14 DTE; close by 7 DTE",
        ],
    )


def build_stock_analysis(inputs: StockAnalysisInputs) -> StockAnalysis:
    market_score, vol_score, flow_score, positioning_score, total_score = _score_parts(inputs)
    signal = _signal(total_score, inputs)
    relation = "above" if inputs.spot > inputs.gex_flip else "below"
    resistance = _nearest_resistance(inputs)
    support = _top_support(inputs)
    wall_phrase = (
        f"a {_format_money(resistance.net_gex)} gamma wall at {_format_price(resistance.strike)} caps immediate upside"
        if signal != "SELL"
        else f"support at {_format_price(support.strike)} is the downside magnet"
    )
    return StockAnalysis(
        ticker=inputs.ticker,
        live_price=_format_price(inputs.spot),
        signal=signal,
        thesis=(
            f"{inputs.ticker} sits just {relation} the GEX flip at {_format_price(inputs.gex_flip)}. "
            f"{wall_phrase}. Flow is {_format_money(inputs.net_premium, signed=True)} net premium, "
            f"IV rank is {_format_decimal(inputs.iv_rank)}, and the setup favors "
            f"{'buying calls for a breakout' if signal == 'BUY' else 'downside protection or put spreads' if signal == 'SELL' else 'waiting for confirmation'}."
        ),
        score=f"{total_score:+d}/100",
        iv_rank=f"{_format_decimal(inputs.iv_rank)}/100",
        iv_hv=f"{_format_pct(inputs.current_iv_pct)} / {_format_pct(inputs.historical_vol_pct)}",
        skew=f"Put skew ({_format_pct(inputs.put_25_delta_iv_pct - inputs.call_25_delta_iv_pct)})",
        term_structure=f"{_term_label(inputs)} (normal)" if _term_label(inputs) == "Contango" else _term_label(inputs),
        vol_regime=f"Low (rank {_format_decimal(inputs.iv_rank)})" if inputs.iv_rank < Decimal("30") else "Elevated",
        net_premium_1d=_format_money(inputs.net_premium, signed=True),
        call_put_ratio=_format_decimal(inputs.call_put_ratio, "0.01"),
        gex_flip=f"{_format_price(inputs.gex_flip)} ({relation})",
        short_interest=f"{_format_pct(inputs.short_interest_ratio_pct)} [T+1]",
        oi_signal=f"{'Bullish' if inputs.net_premium > 0 else 'Bearish'} [T+1]",
        data_date=inputs.data_date,
        scenarios=[
            ScenarioRow(
                tone="bull",
                text=f"Break {_format_price(resistance.strike)} wall -> {_format_price(inputs.call_sell_strike - Decimal('7'))}-{_format_price(inputs.call_sell_strike)} target",
            ),
            ScenarioRow(tone="base", text=f"{_format_price(inputs.gex_flip - Decimal('1.25'))}-{_format_price(resistance.strike + Decimal('2.5'))} range-bound (GEX pinning)"),
            ScenarioRow(tone="bear", text=f"Lose {_format_price(support.strike)} support -> {_format_price(support.strike - Decimal('10'))} gap fill"),
        ],
        conviction=f"{'B - Moderate' if abs(total_score) < 40 else 'A - High'} | Top: Cheap IV + directional flow",
        risk=f"{_format_price(resistance.strike)} GEX wall may cap upside" if signal != "SELL" else f"Reclaim {_format_price(resistance.strike)} invalidates downside",
        watch=f"Break above {_format_price(resistance.strike)} with volume" if signal != "SELL" else f"Break below {_format_price(support.strike)} with volume",
        market_structure=_market_structure(inputs, market_score),
        volatility=_volatility(inputs, vol_score),
        flow_positioning=_flow_positioning(inputs, flow_score, positioning_score),
        vrp_assessment=_vrp_assessment(inputs),
        trade_plan=_trade_plan(inputs, signal),
    )


def sample_tsla_analysis_inputs() -> StockAnalysisInputs:
    return StockAnalysisInputs(
        ticker="TSLA",
        spot=Decimal("380.88"),
        gex_flip=Decimal("376.25"),
        gex_levels=[
            GexInputLevel(strike=Decimal("382.50"), net_gex=Decimal("100400000")),
            GexInputLevel(strike=Decimal("392.50"), net_gex=Decimal("28200000")),
            GexInputLevel(strike=Decimal("400"), net_gex=Decimal("20700000")),
            GexInputLevel(strike=Decimal("375"), net_gex=Decimal("-17900000")),
            GexInputLevel(strike=Decimal("370"), net_gex=Decimal("-44200000")),
            GexInputLevel(strike=Decimal("350"), net_gex=Decimal("-42800000")),
        ],
        volume_dex_strike=Decimal("380"),
        volume_dex_premium=Decimal("152500000"),
        current_iv_pct=Decimal("42.0"),
        historical_vol_pct=Decimal("31.1"),
        iv_rank=Decimal("3.37"),
        iv_52w_low_pct=Decimal("39.3"),
        iv_52w_high_pct=Decimal("107.2"),
        rv_52w_low_pct=Decimal("28.5"),
        rv_52w_high_pct=Decimal("112.9"),
        vrp_pct=Decimal("7.6"),
        vrp_z_score=Decimal("0.28"),
        put_25_delta_iv_pct=Decimal("41.6"),
        call_25_delta_iv_pct=Decimal("40.2"),
        near_term_iv_pct=Decimal("38.6"),
        near_term_dte=11,
        mid_term_iv_pct=Decimal("41.5"),
        mid_term_dte=29,
        far_term_iv_pct=Decimal("45.0"),
        far_term_dte=91,
        term_expiration_count=20,
        vol_stats_date="2026-03-19",
        net_premium=Decimal("524300000"),
        bull_premium=Decimal("2290000000"),
        bear_premium=Decimal("1770000000"),
        call_put_ratio=Decimal("0.94"),
        dark_pool_premium=Decimal("2300000"),
        dark_pool_prints=8,
        short_interest_ratio_pct=Decimal("43.7"),
        short_interest_z=Decimal("-0.78"),
        short_interest_history_days=122,
        top_expiries=[
            "Mar 20: +$463M (0DTE opex) | Apr 17: +$94M (29 DTE)",
            "May 15: -$11M | Dec 2028: -$17M (LEAPS)",
        ],
        oi_rows=[
            OiInputRow(strike=Decimal("385"), call_volume=136564, put_volume=56586),
            OiInputRow(strike=Decimal("390"), call_volume=114894, put_volume=52794),
            OiInputRow(strike=Decimal("380"), call_volume=106881, put_volume=167016),
        ],
        trade_expiry_label="Apr 17, 2026",
        trade_dte=24,
        call_buy_strike=Decimal("385"),
        call_sell_strike=Decimal("400"),
        put_buy_strike=Decimal("370"),
        put_sell_strike=Decimal("360"),
        estimated_debit=Decimal("6.40"),
        max_profit=Decimal("8.60"),
        max_loss=Decimal("6.40"),
        data_date="3/24/2026",
    )
