"""compute_watchlist_card_row covers full SingleStockReport → card dict."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.models import (
    FlowSnapshot,
    MarketAggregates,
    MarketStructure,
    SetupClassification,
    SingleStockReport,
    StrikeGexBucket,
    VolatilityProfile,
    VRPAssessment,
)
from uw_scan.sources.ohlc import IntradayQuote, OhlcBar
from uw_scan.storage.repository import PcrHistoryRow


def _make_report() -> SingleStockReport:
    return SingleStockReport(
        run_id=1,
        ticker="TSLA",
        generated_at=datetime(2026, 5, 8, 13, 0, tzinfo=timezone.utc),
        market_structure=MarketStructure(
            spot=Decimal("445.12"),
            net_gex=Decimal("81256"),
            total_call_gex=Decimal("167045"),
            total_put_gex=Decimal("-85789"),
            max_pain=Decimal("410"),
        ),
        volatility=VolatilityProfile(
            iv=Decimal("0.691"),
            iv_rank=Decimal("39.0"),
            skew_25d=Decimal("-0.0146"),
        ),
        flow=FlowSnapshot(
            ticker="TSLA",
            flow_count=42,
            net_premium=Decimal("-50000000"),
            bull_premium=Decimal("60000000"),
            bear_premium=Decimal("110000000"),
            ask_side_premium=Decimal("91000000"),
            bid_side_premium=Decimal("9000000"),
        ),
        vrp=VRPAssessment(vrp=Decimal("-0.02"), signal="rich", note=""),
        setup=SetupClassification(
            setup_type="C",
            label="Deep Conviction",
            direction="bear",
            score=Decimal("1.51"),
        ),
        aggregates=MarketAggregates(
            call_oi_total=1_200_000,
            put_oi_total=2_100_000,
            pcr_oi=Decimal("1.75"),
            pcr_vol=Decimal("1.58"),
        ),
        strike_gex_curve=[
            StrikeGexBucket(
                strike=Decimal("420"),
                expiry=date(2026, 5, 15),
                net_gex=Decimal("-50000"),
            ),
            StrikeGexBucket(
                strike=Decimal("440"),
                expiry=date(2026, 5, 15),
                net_gex=Decimal("-30000"),
            ),
            StrikeGexBucket(
                strike=Decimal("450"),
                expiry=date(2026, 5, 15),
                net_gex=Decimal("20000"),
            ),
            StrikeGexBucket(
                strike=Decimal("440"),
                expiry=date(2026, 6, 20),
                net_gex=Decimal("50000"),
            ),
        ],
    )


def _make_ohlc(days: int = 22) -> list[OhlcBar]:
    today = date(2026, 5, 8)
    return [
        OhlcBar(
            ticker="TSLA",
            date=today - timedelta(days=days - i),
            open=None,
            high=None,
            low=None,
            close=Decimal(str(400 + i)),
            volume=None,
        )
        for i in range(days)
    ]


def test_derive_full_row():
    report = _make_report()
    history = _make_ohlc()
    intraday = IntradayQuote(
        ticker="TSLA",
        price=Decimal("445.12"),
        quoted_at=datetime(2026, 5, 8, 13, 7, 55, tzinfo=timezone.utc),
    )
    prior_pcr = PcrHistoryRow(
        ticker="TSLA",
        snapshot_date=date(2026, 4, 8),
        pcr_oi=Decimal("1.78"),
        pcr_vol=Decimal("1.60"),
    )
    row = compute_watchlist_card_row(report, history, intraday, prior_pcr)

    assert row["ticker"] == "TSLA"
    assert row["spot"] == Decimal("445.12")
    assert row["spot_source"] == "massive.com_intraday"
    assert row["iv_atm"] == Decimal("0.691")
    assert row["iv_rank"] == Decimal("39.0")

    assert row["setup_type"] == "C"
    assert row["setup_direction"] == "bear"
    assert row["setup_score"] == Decimal("1.51")

    assert row["aggression_pct"] == Decimal("0.91")

    assert row["max_gex_strike"] is not None
    assert row["gex_per_1pct_move"] == Decimal("81256") * Decimal("0.01") * Decimal(
        "445.12"
    )
    assert row["gex_expiring_date"] == date(2026, 5, 15)
    assert row["gex_expiring_pct"] is not None

    assert row["skew_25d_30dte"] == Decimal("-0.0146")

    assert row["pcr_oi"] == Decimal("1.75")
    assert row["pcr_vol"] == Decimal("1.58")
    assert row["pcr_delta_30d"] == Decimal("1.75") - Decimal("1.78")


def test_derive_minimal_report_yields_mostly_nulls():
    report = _make_report()
    report.setup = None
    report.aggregates = None
    report.strike_gex_curve = []
    row = compute_watchlist_card_row(report, [], None, None)
    assert row["setup_type"] is None
    assert row["aggression_pct"] is not None
    assert row["gex_flip_price"] is None
    assert row["gex_expiring_pct"] is None
    assert row["ret_1d"] is None
    assert row["pcr_delta_30d"] is None
