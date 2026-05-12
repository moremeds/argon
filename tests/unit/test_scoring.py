"""Scoring tests for Type C (Deep Conviction) classification."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from uw_scan.models import (
    FlowSnapshot,
    MarketStructure,
    OiChangeRow,
    SingleStockReport,
    VolatilityProfile,
    VRPAssessment,
)
from uw_scan.scoring import classify_setup_c


def _mk_oi_row(i: int) -> OiChangeRow:
    return OiChangeRow(
        underlying_symbol="TSLA",
        option_symbol=f"TSLA260515C0040{i:04d}",
        curr_oi=10_000 + i,
    )


def _mk_report(
    *,
    net_premium: Decimal,
    iv_rank: Decimal | None,
    dark_pool_notional: Decimal | None = None,
    oi_change_top_count: int = 0,
) -> SingleStockReport:
    return SingleStockReport(
        run_id=1,
        ticker="TSLA",
        generated_at=datetime.now(UTC),
        market_structure=MarketStructure(),
        volatility=VolatilityProfile(iv_rank=iv_rank),
        flow=FlowSnapshot(
            ticker="TSLA",
            flow_count=10,
            net_premium=net_premium,
            bull_premium=Decimal("10000000"),
            bear_premium=Decimal("0"),
            ask_side_premium=Decimal("0"),
            bid_side_premium=Decimal("0"),
        ),
        vrp=VRPAssessment(vrp=None, signal="unknown", note=""),
        dark_pool_notional=dark_pool_notional,
        oi_change_top=[_mk_oi_row(i) for i in range(oi_change_top_count)],
    )


def test_classify_bull_setup_with_dark_pool():
    r = _mk_report(
        net_premium=Decimal("20000000"),
        iv_rank=Decimal("80"),
        dark_pool_notional=Decimal("500000000"),
    )
    setup = classify_setup_c(r)
    assert setup is not None
    assert setup.setup_type == "C"
    assert setup.direction == "bull"
    assert setup.score > 0


def test_classify_bear_setup_with_oi_build():
    r = _mk_report(
        net_premium=Decimal("-15000000"),
        iv_rank=Decimal("20"),
        oi_change_top_count=5,
    )
    setup = classify_setup_c(r)
    assert setup is not None
    assert setup.setup_type == "C"
    assert setup.direction == "bear"


def test_low_premium_returns_none():
    r = _mk_report(
        net_premium=Decimal("1000000"),
        iv_rank=Decimal("80"),
        dark_pool_notional=Decimal("500000000"),
    )
    assert classify_setup_c(r) is None


def test_wrong_direction_iv_rank_returns_none():
    # Bull flow but low IV rank → no C
    r = _mk_report(
        net_premium=Decimal("20000000"),
        iv_rank=Decimal("20"),
        dark_pool_notional=Decimal("500000000"),
    )
    assert classify_setup_c(r) is None


def test_missing_iv_rank_returns_none():
    r = _mk_report(
        net_premium=Decimal("20000000"),
        iv_rank=None,
        dark_pool_notional=Decimal("500000000"),
    )
    assert classify_setup_c(r) is None


def test_no_corroborating_signal_returns_none():
    r = _mk_report(
        net_premium=Decimal("20000000"),
        iv_rank=Decimal("80"),
        dark_pool_notional=None,
        oi_change_top_count=0,
    )
    assert classify_setup_c(r) is None


def test_score_caps_at_5():
    r = _mk_report(
        net_premium=Decimal("10000000000"),
        iv_rank=Decimal("100"),
        dark_pool_notional=Decimal("999000000000"),
        oi_change_top_count=20,
    )
    setup = classify_setup_c(r)
    assert setup is not None
    assert setup.score <= Decimal("5")
