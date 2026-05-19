"""derive_intraday_profile — pure derivation of TAPE-view metrics from
per-minute UW option-contract intraday bars. Mirrors the bucket dict shape
returned by OptionIntradayBucketRepository.fetch_buckets.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from uw_scan.cards.intraday_profile import (
    DEFAULT_SPARKLINE_BUCKETS,
    derive_intraday_profile,
)

SYMBOL = "TSLA260515C00450000"
DAY = date(2026, 5, 14)


def _bucket(
    minute: int,
    *,
    ask: int = 0,
    bid: int = 0,
    mid: int = 0,
    multi: int = 0,
    hour: int = 13,
) -> dict[str, Any]:
    return {
        "start_time": datetime(2026, 5, 14, hour, minute, 0, tzinfo=UTC),
        "volume_ask_side": ask,
        "volume_bid_side": bid,
        "volume_mid_side": mid,
        "volume_multi": multi,
    }


def test_empty_buckets_returns_zero_profile():
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=[])
    assert p.option_symbol == SYMBOL
    assert p.trade_date == DAY
    assert p.total_volume == 0
    assert p.first_trade_time is None
    assert p.last_trade_time is None
    assert p.peak_window_start is None
    assert p.peak_window_share_pct is None
    assert p.sparkline == []


def test_all_zero_volume_buckets_returns_zero_profile():
    """Deep OTM contract whose OI built outside the captured window —
    common case; we expect zero volume + None timestamps, not a crash."""
    buckets = [_bucket(30), _bucket(31), _bucket(32)]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert p.total_volume == 0
    assert p.first_trade_time is None
    assert p.peak_window_share_pct is None


def test_first_and_last_trade_skip_zero_volume_buckets():
    """A bucket with all-zero side volumes should not count as a trade
    minute even if UW emitted a price bar for it."""
    buckets = [
        _bucket(30),  # zero
        _bucket(31, ask=100),
        _bucket(32),  # zero between trades
        _bucket(33, bid=50),
        _bucket(34),  # trailing zero
    ]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert p.first_trade_time == datetime(2026, 5, 14, 13, 31, tzinfo=UTC)
    assert p.last_trade_time == datetime(2026, 5, 14, 13, 33, tzinfo=UTC)


def test_peak_window_picks_30min_max():
    """Place 300 contracts in a 30-min cluster surrounded by trickling
    activity. The peak window must anchor at the cluster, not at the
    chronologically first trade."""
    buckets = [
        _bucket(0, ask=10, hour=10),
        _bucket(45, ask=20, hour=10),  # trickle
        _bucket(0, ask=100, hour=13),
        _bucket(5, ask=100, hour=13),
        _bucket(15, ask=100, hour=13),  # peak cluster
        _bucket(45, ask=10, hour=14),
    ]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert p.peak_window_start == datetime(2026, 5, 14, 13, 0, tzinfo=UTC)
    assert p.peak_window_end == datetime(2026, 5, 14, 13, 30, tzinfo=UTC)


def test_peak_window_share_pct_is_decimal_one_dp():
    """Peak share = peak_volume / total_volume, rendered as Decimal with
    one decimal place so the UI doesn't have to re-round."""
    buckets = [
        _bucket(0, ask=60, hour=13),  # in peak
        _bucket(15, ask=40, hour=13),  # in peak
        _bucket(45, ask=100, hour=14),  # outside peak (30-min later)
    ]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    # peak window starting at 13:00 captures 60+40 = 100 of 200 total.
    assert p.peak_window_share_pct == Decimal("50.0")
    assert isinstance(p.peak_window_share_pct, Decimal)


def test_peak_window_handles_all_volume_in_one_bucket():
    """A single block-print minute should anchor the peak there and
    register 100% share — the most informative TAPE label for OI that
    built in one trade."""
    buckets = [_bucket(30, ask=500)]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert p.total_volume == 500
    assert p.peak_window_share_pct == Decimal("100.0")
    assert p.peak_window_start == datetime(2026, 5, 14, 13, 30, tzinfo=UTC)


def test_sums_all_four_side_volumes():
    """Total volume aggregates ask + bid + mid + multi — that's the
    operator denominator for OI mover intent classification."""
    buckets = [_bucket(30, ask=10, bid=20, mid=30, multi=40)]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert p.total_volume == 100


def test_sparkline_downsamples_to_fixed_length():
    """Sparkline is always exactly DEFAULT_SPARKLINE_BUCKETS long — the UI
    relies on a stable width regardless of how many minute bars exist."""
    # 60-minute span, one bucket every 5 minutes, equal volume.
    buckets = [
        _bucket(m, ask=10, hour=13)
        for m in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)
    ] + [_bucket(0, ask=10, hour=14)]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert len(p.sparkline) == DEFAULT_SPARKLINE_BUCKETS
    assert sum(p.sparkline) == p.total_volume


def test_sparkline_concentrates_volume_into_correct_bucket():
    """Volume clustered in the first third of the session should produce
    higher counts in the early sparkline indexes, zeros in the later ones."""
    # Session spans 11:00..14:00 (3 hours = 180 min); 12 buckets = 15 min each.
    buckets = [
        _bucket(0, ask=100, hour=11),  # bucket 0
        _bucket(15, ask=100, hour=11),  # bucket 1
        _bucket(30, ask=100, hour=11),  # bucket 2
        _bucket(0, ask=0, hour=14),  # bucket 11 — last_trade anchor (no volume,
        # but extends the span; this row is filtered
        # out by the zero-volume guard)
        _bucket(0, ask=50, hour=14),  # actually trades at end
    ]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    # last_trade_time anchors at the 14:00 ask=50 row; span = 3h.
    assert p.last_trade_time == datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    assert p.first_trade_time == datetime(2026, 5, 14, 11, 0, tzinfo=UTC)
    # Early three buckets concentrated in the first 30 minutes → all in idx 0/1/2.
    assert p.sparkline[0] > 0
    # The 14:00 trade lands in the last bucket (idx 11).
    assert p.sparkline[-1] == 50


def test_sparkline_single_minute_packs_into_first_bucket():
    """When all trades happen in the same minute (span = 0), the sparkline
    packs the whole volume into index 0 and leaves the rest at 0."""
    buckets = [_bucket(30, ask=500)]
    p = derive_intraday_profile(option_symbol=SYMBOL, trade_date=DAY, buckets=buckets)
    assert p.sparkline[0] == 500
    assert p.sparkline[1:] == [0] * (DEFAULT_SPARKLINE_BUCKETS - 1)


def test_custom_peak_window_and_sparkline_length():
    """The function exposes both knobs so callers can experiment without
    monkey-patching defaults."""
    buckets = [_bucket(0, ask=100, hour=13), _bucket(10, ask=100, hour=13)]
    p = derive_intraday_profile(
        option_symbol=SYMBOL,
        trade_date=DAY,
        buckets=buckets,
        peak_window=timedelta(minutes=15),
        sparkline_buckets=4,
    )
    assert len(p.sparkline) == 4
    assert p.peak_window_end - p.peak_window_start == timedelta(minutes=15)
