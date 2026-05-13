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
