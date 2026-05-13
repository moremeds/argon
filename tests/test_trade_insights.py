from datetime import date
from decimal import Decimal

from uw_scan.models import (
    CandidateStructure,
    InsightLeg,
    TradeInsightsHeader,
    TradeInsightsResponse,
)


def test_trade_insights_response_serializes_required_shape():
    response = TradeInsightsResponse(
        ticker="TSLA",
        header=TradeInsightsHeader(
            dominant_bias="NEUTRAL_SHORT_VOL",
            primary_setup="IV_RV_SPREAD_MEAN_REVERSION",
            confidence_label="MEDIUM",
            data_quality_label="MIXED",
            idea_count=1,
        ),
        candidate_structures=[
            CandidateStructure(
                idea_id="A",
                structure="call_credit_spread",
                thesis="Front premium is elevated.",
                expression_type="SHORT_VOL",
                rank=1,
                max_loss=Decimal("1.25"),
                legs=[
                    InsightLeg(
                        side="sell",
                        option_symbol="TSLA260515C00430000",
                        option_right="C",
                        expiry="2026-05-15",
                        strike=Decimal("430"),
                        mid=Decimal("9.50"),
                    )
                ],
            )
        ],
    )

    body = response.model_dump(mode="json")
    assert body["ticker"] == "TSLA"
    assert body["header"]["dominant_bias"] == "NEUTRAL_SHORT_VOL"
    assert body["candidate_structures"][0]["legs"][0]["strike"] == "430"
    assert body["source_reconciliation"]["status"] == "UNKNOWN"


from uw_scan.reports.trade_insights import (
    ParsedOptionSymbol,
    _credit_spread_math,
    _mid,
    parse_option_symbol,
)


def test_parse_option_symbol_occ_style():
    parsed = parse_option_symbol("TSLA260515C00430000")
    assert parsed == ParsedOptionSymbol(
        root="TSLA",
        expiry=date(2026, 5, 15),
        right="C",
        strike=Decimal("430"),
    )


def test_parse_option_symbol_rejects_bad_symbol():
    assert parse_option_symbol("bad") is None


def test_mid_uses_nbbo_when_present():
    assert _mid({"nbbo_bid": Decimal("1.00"), "nbbo_ask": Decimal("1.20")}) == Decimal(
        "1.10"
    )


def test_mid_falls_back_to_last_price():
    assert _mid({"last_price": Decimal("0.95")}) == Decimal("0.95")


def test_credit_spread_math_caps_loss_by_width_minus_credit():
    net_credit, max_loss, max_profit = _credit_spread_math(
        short_mid=Decimal("1.80"),
        long_mid=Decimal("0.55"),
        width=Decimal("5"),
    )
    assert net_credit == Decimal("1.25")
    assert max_loss == Decimal("3.75")
    assert max_profit == Decimal("1.25")
