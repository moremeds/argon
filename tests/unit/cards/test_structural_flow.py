"""Lens 1 — structural-flow posture."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.structural_flow import (
    CbReserveSnapshot,
    EtfFlowSnapshot,
    compute_structural_posture,
)


def test_structural_posture_bucket_sums_12m():
    cb_rows = [
        CbReserveSnapshot(
            country_iso3="CHN",
            obs_month=date(2026, 5, 1) - timedelta(days=30 * month_offset),
            reserves_t=Decimal(str(2200 + month_offset * 5)),
            bucket="strategic_accumulator",
        )
        for month_offset in range(12)
    ]
    posture = compute_structural_posture(
        cb_rows=cb_rows,
        etf_rows=[],
        inventory_rows=[],
        cot_rows=[],
        fx_rows=[],
        gold_series=[],
        as_of=date(2026, 5, 16),
    )
    assert posture.cb_strategic_12m_sum_t is not None
    assert posture.cb_strategic_12m_sum_t > Decimal("0")


def test_structural_posture_emits_narrative():
    posture = compute_structural_posture(
        cb_rows=[],
        etf_rows=[],
        inventory_rows=[],
        cot_rows=[],
        fx_rows=[],
        gold_series=[],
        as_of=date(2026, 5, 16),
    )
    assert posture.narrative_text
    assert posture.structural_state_label == "structural-mixed"


def test_structural_posture_uses_gld_share_flows_when_holdings_absent():
    posture = compute_structural_posture(
        cb_rows=[],
        etf_rows=[],
        inventory_rows=[],
        cot_rows=[],
        fx_rows=[],
        gold_series=[],
        as_of=date(2026, 5, 16),
        etf_flow_rows=[
            EtfFlowSnapshot(
                ticker="GLD",
                obs_date=date(2026, 5, 15),
                share_change=Decimal("-900000"),
            )
        ],
    )

    assert posture.gld_holdings_t is None
    assert posture.gld_30d_net_flow_t is not None
    assert posture.gld_30d_net_flow_t.quantize(Decimal("0.001")) == Decimal("-2.606")
    assert "GLD 30d net flow: -2.6 tonnes." in posture.narrative_text
