"""Pydantic round-trip for the GOLD COMPASS response models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.models import (
    GoldCorrelationBand,
    GoldCorrelationHistory,
    GoldCorrelationPoint,
    GoldCyclicalPostureModel,
    GoldDataFreshnessSource,
    GoldDecompositionRow,
    GoldGaugeState,
    GoldHistoryPoint,
    GoldInputProvenance,
    GoldSpotTile,
    GoldStateResponse,
    GoldStructuralPostureModel,
    GoldTwoForceText,
    GoldValuationPostureModel,
)


def test_gold_state_response_round_trips():
    resp = GoldStateResponse(
        obs_date=date(2026, 5, 16),
        computed_at=datetime(2026, 5, 17, tzinfo=UTC),
        gauge=GoldGaugeState(
            corr_60d=Decimal("-0.04"),
            corr_126d=Decimal("-0.05"),
            corr_252d=Decimal("-0.07"),
            corr_504d=Decimal("-0.31"),
            corr_252d_returns=Decimal("-0.06"),
            state="suspended",
        ),
        spot=GoldSpotTile(
            last=Decimal("4561.50"),
            delta_abs=Decimal("-157.20"),
            delta_pct=Decimal("-0.0332"),
            high=Decimal("4615.20"),
            low=Decimal("4524.30"),
            open=Decimal("4615.20"),
        ),
        structural=GoldStructuralPostureModel(
            state_label="structural-bid-intact",
            posture_chip="FAVORABLE",
            cb_strategic_12m_sum_t=Decimal("210"),
            cb_tactical_12m_sum_t=Decimal("12"),
            cb_diversifier_12m_sum_t=Decimal("34"),
            cb_52w_pct=Decimal("0.78"),
            gld_holdings_t=Decimal("872.5"),
            gld_30d_net_flow_t=Decimal("-12.4"),
            comex_registered_oz=Decimal("17500100"),
            comex_20d_roc_pct=Decimal("0.14"),
            lbma_30d_momentum_t=Decimal("-18"),
            cot_mm_net_pct=Decimal("0.72"),
            cot_mm_4w_change_sigma=Decimal("0.18"),
            uw_25d_skew_sigma=Decimal("1.2"),
            fx_basket_dxy_z=Decimal("0.6"),
            xau_cny_premium_pct=Decimal("0.004"),
            gld_history=[
                GoldHistoryPoint(obs_date=date(2024, 6, 1), value=Decimal("870")),
            ],
            gold_history=[
                GoldHistoryPoint(obs_date=date(2024, 6, 1), value=Decimal("2400")),
            ],
            narrative_text="Structural bid intact.",
        ),
        cyclical=GoldCyclicalPostureModel(
            zone_label="moderate-trap",
            posture_chip="NEUTRAL",
            cpi_yoy=Decimal("2.8"),
            t5yifr=Decimal("2.31"),
            t5yifr_pct_52w=Decimal("0.48"),
            dfii10=Decimal("1.97"),
            dfii10_60d_change_bps=Decimal("12"),
            dxy=Decimal("102.1"),
            dxy_60d_sigma=Decimal("-0.4"),
            gpr_value=Decimal("371"),
            gpr_pct_52w=Decimal("0.64"),
            factors={"F1": -0.4, "F5": 1.8},
            two_force_text=GoldTwoForceText(
                discount_rate="tightening — would press gold",
                hedge_demand="subdued vol — no panic bid",
            ),
            narrative_text="Cyclical posture suspended.",
        ),
        valuation=GoldValuationPostureModel(
            flag="Severe",
            posture_chip="STRETCHED",
            real_price_percentile=Decimal("0.92"),
            gold_m2_ratio_percentile=Decimal("0.78"),
            gold_oil_ratio_percentile=Decimal("0.89"),
            gold_spx_ratio_percentile=Decimal("0.64"),
            narrative_text="Mean-reversion risk: SEVERE.",
        ),
        inputs_used={
            "DFII10": GoldInputProvenance(
                obs_date=date(2026, 5, 16),
                as_of=datetime(2026, 5, 17, tzinfo=UTC),
            ),
        },
        data_freshness=[
            GoldDataFreshnessSource(
                id="FRED",
                last_as_of=datetime(2026, 5, 17, tzinfo=UTC),
                stale_seconds=60,
            ),
            GoldDataFreshnessSource(
                id="COT",
                last_as_of=datetime(2026, 5, 13, 20, 30, tzinfo=UTC),
                stale_seconds=86400 * 4,
            ),
        ],
        decomposition_rows=[
            GoldDecompositionRow(lens="L1", factor="CB", contribution=Decimal("1.4")),
            GoldDecompositionRow(
                lens="L2", factor="DFII10", contribution=Decimal("-0.4")
            ),
            GoldDecompositionRow(
                lens="L3", factor="Gold/CPI", contribution=Decimal("1.8")
            ),
        ],
        correlation_history=GoldCorrelationHistory(
            gold_dfii10=[
                GoldCorrelationPoint(
                    obs_date=date(2024, 12, 31), value=Decimal("-0.12")
                ),
            ],
            gold_dxy=[],
            gold_gpr=[],
            pre_2022_band=GoldCorrelationBand(
                mean=Decimal("-0.84"), std=Decimal("0.04")
            ),
        ),
    )
    dumped = resp.model_dump_json()
    assert "Severe" in dumped
    assert "moderate-trap" in dumped
    assert "FAVORABLE" in dumped
    assert "L1" in dumped
