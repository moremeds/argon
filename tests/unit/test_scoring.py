"""Scoring tests for Type C (Deep Conviction) classification."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from uw_scan.models import (
    BulkScreenerRow,
    FlowSnapshot,
    MarketStructure,
    OiChangeRow,
    SingleStockReport,
    VolatilityProfile,
    VRPAssessment,
)
from uw_scan.scoring import (
    classify_setup_c,
    classify_setup_c_from_row,
    classify_setup_f,
    detect_f_signals,
)


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


# ---------------------------------------------------------------------------
# Setup Type F (Multi-Signal Confluence) — scan-row scoring
# ---------------------------------------------------------------------------


def _mk_row(
    *,
    ticker: str = "TSLA",
    net_call_premium: Decimal | None = Decimal("100000000"),
    net_put_premium: Decimal | None = Decimal("0"),
    iv_rank: Decimal | None = Decimal("80"),
    gex_net_change: Decimal | None = None,
    total_open_interest: int | None = 1_000_000,
    variance_risk_premium: Decimal | None = None,
    relative_volume: Decimal | None = None,
) -> BulkScreenerRow:
    return BulkScreenerRow(
        ticker=ticker,
        net_call_premium=net_call_premium,
        net_put_premium=net_put_premium,
        iv_rank=iv_rank,
        gex_net_change=gex_net_change,
        total_open_interest=total_open_interest,
        variance_risk_premium=variance_risk_premium,
        relative_volume=relative_volume,
    )


def test_classify_setup_f_two_signals_qualifies():
    """Bull base met + GEX/OI shift + VRP magnitude → F."""
    row = _mk_row(
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("80"),
        gex_net_change=Decimal("50000"),  # 50000 / 1_000_000 = 0.05 > 0.01
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("-0.07"),  # |0.07| > 0.05
    )
    setup = classify_setup_f(row)
    assert setup is not None
    assert setup.setup_type == "F"
    assert setup.direction == "bull"
    assert setup.score > Decimal("1")


def test_classify_setup_f_one_signal_returns_none():
    """Base met but only 1 corroborating signal → not F."""
    row = _mk_row(
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("80"),
        gex_net_change=Decimal("50000"),  # 1 signal
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("0.01"),  # below 0.05 threshold
        relative_volume=Decimal("1.0"),  # below 1.5 threshold
    )
    # flow polarization = 100M > 50M → that's the 2nd signal! Adjust to avoid.
    row.net_call_premium = Decimal("10000000")  # 10M total polarization → below 50M
    row.net_put_premium = Decimal("0")
    # but then base C may not be met (net=10M ≥ 5M, OK)
    setup = classify_setup_f(row)
    assert setup is None


def test_classify_setup_f_base_miss_returns_none():
    """Net premium below threshold → None even with all 4 signals."""
    row = _mk_row(
        net_call_premium=Decimal("1000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("80"),
        gex_net_change=Decimal("50000"),
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("-0.10"),
        relative_volume=Decimal("3.0"),
    )
    assert classify_setup_f(row) is None


def test_classify_setup_f_iv_rank_gate_returns_none():
    """Bull flow but low IV rank → no F."""
    row = _mk_row(
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("20"),
        gex_net_change=Decimal("50000"),
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("-0.10"),
        relative_volume=Decimal("3.0"),
    )
    assert classify_setup_f(row) is None


def test_classify_setup_f_bear_with_signals():
    """Bear: net put-buying dominates, low IV rank, multiple signals."""
    row = _mk_row(
        net_call_premium=Decimal("0"),
        net_put_premium=Decimal("100000000"),  # net = -100M (bear)
        iv_rank=Decimal("20"),
        gex_net_change=Decimal("-30000"),  # |-30000|/1M = 0.03 > 0.01
        total_open_interest=1_000_000,
        relative_volume=Decimal("2.5"),  # > 1.5
    )
    setup = classify_setup_f(row)
    assert setup is not None
    assert setup.direction == "bear"
    assert setup.setup_type == "F"


def test_classify_setup_f_missing_iv_rank_returns_none():
    row = _mk_row(
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=None,
        gex_net_change=Decimal("50000"),
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("-0.10"),
    )
    assert classify_setup_f(row) is None


def test_detect_f_signals_counts_correctly():
    row = _mk_row(
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("80"),
        gex_net_change=Decimal("50000"),
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("-0.07"),
        relative_volume=Decimal("2.0"),
    )
    signals = detect_f_signals(row)
    # GEX/OI=0.05, VRP=0.07, rel_vol=2.0, polarization=100M → 4 signals
    assert len(signals) == 4


def test_classify_setup_c_from_row_qualifies():
    row = _mk_row(
        net_call_premium=Decimal("20000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("75"),
    )
    setup = classify_setup_c_from_row(row)
    assert setup is not None
    assert setup.setup_type == "C"
    assert setup.direction == "bull"


def test_classify_setup_c_from_row_below_premium():
    row = _mk_row(
        net_call_premium=Decimal("1000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("75"),
    )
    assert classify_setup_c_from_row(row) is None
