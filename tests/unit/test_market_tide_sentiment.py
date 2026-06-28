"""Market-tide slope/sentiment classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from uw_scan.reports.market_tide_sentiment import compute_sentiment

_T0 = datetime(2026, 6, 26, 13, 30, tzinfo=timezone.utc)


def _bar(i, ncp, npp, nv=0):
    return {
        "ts": _T0 + timedelta(minutes=5 * i),
        "net_call_premium": ncp,
        "net_put_premium": npp,
        "net_volume": nv,
    }


def test_monotone_bullish_is_strong_call_led_confirmed():
    # Spread S = NCP - NPP widens monotonically up; volume rises with it.
    bars = [
        _bar(i, ncp=1_000_000 * i, npp=-200_000 * i, nv=1000 * i) for i in range(12)
    ]
    s = compute_sentiment(bars)
    assert s.state == "BULLISH"
    assert s.magnitude == "STRONG"  # monotone → trend_strength ~1
    assert s.driver == "call buying"
    assert s.volume_confirms is True
    assert s.spread is not None and s.spread > 0


def test_monotone_bearish_via_put_buying():
    # Puts bought at ask (NPP rising) with flat calls → bearish, put-led.
    bars = [_bar(i, ncp=0, npp=1_000_000 * i, nv=-1000 * i) for i in range(12)]
    s = compute_sentiment(bars)
    assert s.state == "BEARISH"
    assert s.driver == "put buying"
    assert s.session_slope is not None and s.session_slope < 0


def test_flat_spread_is_balanced():
    bars = [_bar(i, ncp=1_000_000, npp=1_000_000) for i in range(12)]
    s = compute_sentiment(bars)
    assert s.state == "BALANCED"
    assert s.magnitude == "FLAT"


def test_round_trip_is_not_strong():
    # Spread climbs then fully retraces → small net displacement vs big range.
    up = [_bar(i, ncp=1_000_000 * i, npp=0) for i in range(6)]
    down = [_bar(6 + i, ncp=5_000_000 - 1_000_000 * i, npp=0) for i in range(6)]
    s = compute_sentiment(up + down)
    assert s.trend_strength is not None and s.trend_strength < 0.6  # not STRONG


def test_thin_session_warms_up():
    assert compute_sentiment([_bar(0, 1_000_000, 0)]).state == "WARMING_UP"
    assert compute_sentiment([]).state == "WARMING_UP"
