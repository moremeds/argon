from decimal import Decimal

from uw_scan.analysis import build_stock_analysis, sample_tsla_analysis_inputs


def test_build_stock_analysis_computes_tsla_report_from_inputs():
    analysis = build_stock_analysis(sample_tsla_analysis_inputs())

    assert analysis.ticker == "TSLA"
    assert analysis.live_price == "$380.88"
    assert analysis.signal == "BUY"
    assert analysis.score == "+31/100"
    assert analysis.market_structure.score == "+8/28"
    assert analysis.market_structure.levels[0].strike == "$382.50"
    assert analysis.volatility.score == "+8/28"
    assert analysis.flow_positioning.net_premium == "+$524.3M"
    assert analysis.vrp_assessment.signal == "DO NOT SELL"
    assert "Buy $385 Call / Sell $400 Call" in analysis.trade_plan.structure


def test_build_stock_analysis_reacts_to_market_inputs():
    inputs = sample_tsla_analysis_inputs()
    bearish_inputs = inputs.model_copy(
        update={
            "spot": Decimal("365.00"),
            "net_premium": Decimal("-125000000"),
            "bull_premium": Decimal("900000000"),
            "bear_premium": Decimal("1025000000"),
            "call_put_ratio": Decimal("1.45"),
        }
    )

    analysis = build_stock_analysis(bearish_inputs)

    assert analysis.signal == "SELL"
    assert analysis.score.startswith("-")
    assert "below the GEX flip" in analysis.thesis
    assert analysis.flow_positioning.net_premium == "-$125.0M"
    assert analysis.trade_plan.title == "Put Debit Spread - TSLA"
