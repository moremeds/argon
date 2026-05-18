"""Discovery — group market-wide alerts by ticker, exclude watchlist, top-N by DCF score."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.discovery import discover_from_alerts

TODAY = date(2026, 5, 17)


def _alert(
    *,
    ticker: str = "ABCD",
    option_type: str = "call",
    total_premium: str = "800000",
    total_ask_side_prem: str = "700000",
    total_bid_side_prem: str = "100000",
    sector: str | None = "Technology",
    created_offset_min: int = 0,
) -> FlowAlert:
    return FlowAlert(
        id=f"{ticker}-{created_offset_min}",
        ticker=ticker,
        type=option_type,
        strike=Decimal("100"),
        underlying_price=Decimal("100"),
        total_premium=Decimal(total_premium),
        total_ask_side_prem=Decimal(total_ask_side_prem),
        total_bid_side_prem=Decimal(total_bid_side_prem),
        volume=2000,
        open_interest=1000,
        has_multileg=False,
        expiry=TODAY + timedelta(days=30),
        next_earnings_date=TODAY + timedelta(days=60),
        sector=sector,
        created_at=datetime(2026, 5, 17, 14, 0, tzinfo=timezone.utc)
        + timedelta(minutes=created_offset_min),
    )


DCF_KWARGS = dict(
    min_premium_usd=Decimal("500000"),
    min_ask_side=Decimal("0.80"),
    max_moneyness=Decimal("0.12"),
    min_dte=6,
    earnings_window_days=14,
)


def test_groups_alerts_by_ticker_and_returns_one_candidate_per_ticker():
    alerts = [
        _alert(ticker="NVDA"),
        _alert(ticker="NVDA"),  # same ticker, qualifies as 2 alerts
        _alert(ticker="AMD"),
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    tickers = sorted(c.ticker for c in out)
    assert tickers == ["AMD", "NVDA"]
    nvda = next(c for c in out if c.ticker == "NVDA")
    assert nvda.alert_count == 2


def test_excludes_watchlist_tickers():
    alerts = [
        _alert(ticker="NVDA"),
        _alert(ticker="UNKNOWN"),  # not on watchlist
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers={"NVDA"},
        **DCF_KWARGS,
    )
    assert [c.ticker for c in out] == ["UNKNOWN"]


def test_watchlist_match_is_case_insensitive():
    alerts = [_alert(ticker="nvda")]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers={"NVDA"},
        **DCF_KWARGS,
    )
    assert out == []


def test_returns_empty_when_no_alerts_qualify_dcf():
    alerts = [
        _alert(ticker="LOWQ", total_premium="100000"),  # below min_premium
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert out == []


def test_sorts_by_dcf_score_descending_then_ticker_ascending():
    # Same score for both — should sort alphabetically
    alerts = [
        _alert(ticker="ZZZZ"),
        _alert(ticker="AAAA"),
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert [c.ticker for c in out] == ["AAAA", "ZZZZ"]

    # Bigger premium → higher DCF score → first in result
    alerts = [
        _alert(ticker="SMALL", total_premium="800000"),
        _alert(
            ticker="BIG",
            total_premium="10000000",
            total_ask_side_prem="9000000",
            total_bid_side_prem="1000000",
        ),
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert [c.ticker for c in out] == ["BIG", "SMALL"]


def test_carries_sector_and_latest_alert_at():
    alerts = [
        _alert(ticker="META", sector="Comm Services", created_offset_min=0),
        _alert(ticker="META", sector="Comm Services", created_offset_min=15),
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert len(out) == 1
    c = out[0]
    assert c.sector == "Comm Services"
    assert c.latest_alert_at == datetime(2026, 5, 17, 14, 15, tzinfo=timezone.utc)


def test_long_call_yields_bullish_bias_with_strength():
    alerts = [_alert(ticker="ABCD", option_type="call", total_premium="800000")]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert out[0].bias == "bullish"
    # DCF score = 0.5 + 0.5 * (800000 / 2000000) = 0.7 → moderate
    assert out[0].bias_strength == "moderate"


def test_put_yields_bearish_bias():
    alerts = [_alert(ticker="XYZ", option_type="put")]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert out[0].bias == "bearish"


def test_respects_limit():
    alerts = [_alert(ticker=f"T{i:02d}") for i in range(25)]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        limit=5,
        **DCF_KWARGS,
    )
    assert len(out) == 5


def test_drops_alerts_without_ticker():
    alerts = [
        _alert(ticker="NVDA"),
        FlowAlert(
            id="no-ticker",
            ticker="",
            type="call",
            strike=Decimal("100"),
            underlying_price=Decimal("100"),
            total_premium=Decimal("1000000"),
            total_ask_side_prem=Decimal("900000"),
            total_bid_side_prem=Decimal("100000"),
            volume=2000,
            open_interest=1000,
            has_multileg=False,
            expiry=TODAY + timedelta(days=30),
            next_earnings_date=TODAY + timedelta(days=60),
        ),
    ]
    out = discover_from_alerts(
        alerts=alerts,
        today=TODAY,
        watchlist_tickers=set(),
        **DCF_KWARGS,
    )
    assert [c.ticker for c in out] == ["NVDA"]
