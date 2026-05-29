"""Unit tests for derive_framework_tape (pure OHLCV price-action deriver, M6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.framework_tape import derive_framework_tape


@dataclass
class _Bar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


def _series(closes: list[float], *, start: date = date(2026, 1, 1)) -> list[_Bar]:
    bars = []
    for i, c in enumerate(closes):
        cd = Decimal(str(c))
        bars.append(
            _Bar(
                date=start + timedelta(days=i),
                open=cd,
                high=cd + Decimal("1"),
                low=cd - Decimal("1"),
                close=cd,
                volume=1000,
            )
        )
    return bars


def test_empty_input_is_all_na_no_crash():
    out = derive_framework_tape([])
    assert out["available"] is False
    assert out["bars"] == 0
    assert out["latest_close"] is None
    assert out["trend_3close"] is None
    assert out["dma_50"] is None
    assert out["drawdown_from_6m_high"] is None


def test_trend_up_down_mixed():
    assert derive_framework_tape(_series([1, 2, 3]))["trend_3close"] == "up"
    assert derive_framework_tape(_series([3, 2, 1]))["trend_3close"] == "down"
    assert derive_framework_tape(_series([1, 3, 2]))["trend_3close"] == "mixed"


def test_latest_close_and_bars():
    out = derive_framework_tape(_series([10, 11, 12]))
    assert out["available"] is True
    assert out["bars"] == 3
    assert out["latest_close"] == Decimal("12")


def test_input_order_does_not_matter():
    asc = derive_framework_tape(_series([10, 20, 30]))
    desc = derive_framework_tape(list(reversed(_series([10, 20, 30]))))
    assert asc["latest_close"] == desc["latest_close"] == Decimal("30")
    assert asc["trend_3close"] == desc["trend_3close"] == "up"


def test_dma_and_price_vs_dma():
    # 60 ascending closes 1..60 → dma_50 = mean(11..60) = 35.5; latest=60
    out = derive_framework_tape(_series(list(range(1, 61))))
    assert out["dma_50"] == Decimal("35.5")
    assert out["dma_200"] is None  # < 200 bars
    assert out["price_vs_dma50"] == Decimal("60") / Decimal("35.5") - 1


def test_returns_5d_and_20d():
    out = derive_framework_tape(_series(list(range(1, 31))))  # closes 1..30
    # return_5d = 30/25 - 1 (close 6 bars ago = 25)
    assert out["return_5d"] == Decimal("30") / Decimal("25") - 1
    # return_20d = 30/10 - 1 (close 21 bars ago = 10)
    assert out["return_20d"] == Decimal("30") / Decimal("10") - 1


def test_drawdown_from_high():
    # rises to 50 then falls to 40 → drawdown negative
    closes = list(range(1, 51)) + [49, 48, 47, 46, 45, 44, 43, 42, 41, 40]
    out = derive_framework_tape(_series(closes))
    # 6m high among highs (close+1) is 51; latest close 40
    assert out["drawdown_from_6m_high"] is not None
    assert out["drawdown_from_6m_high"] < 0


def test_distribution_day_flag():
    bars = _series([10, 11, 12])
    # down close (12 -> 11.5 is up; force below prior close 11) on higher volume
    bars[-1].close = Decimal("10.5")  # below prior close 11 → down day
    bars[-1].volume = 5000  # higher than prior bar's 1000
    out = derive_framework_tape(bars)
    assert out["distribution_day"] is True


def test_no_distribution_day_on_up_close():
    bars = _series([10, 11, 12])
    bars[-1].volume = 9999  # high volume but up close
    out = derive_framework_tape(bars)
    assert out["distribution_day"] is False


def test_support_resistance_levels():
    # V shape: down to a trough then back up; latest sits mid-range
    closes = [20, 18, 16, 14, 12, 10, 12, 14, 16, 15]
    out = derive_framework_tape(_series(closes))
    # there should be a support below the latest close (15) and possibly resistance
    assert out["nearest_support"] is None or out["nearest_support"] < Decimal("15")
    if out["nearest_resistance"] is not None:
        assert out["nearest_resistance"] > Decimal("15")


def test_days_to_earnings():
    bars = _series([10, 11, 12], start=date(2026, 1, 1))
    # latest bar date = 2026-01-03; earnings 2026-01-13 → 10 days
    out = derive_framework_tape(bars, next_earnings_date=date(2026, 1, 13))
    assert out["days_to_earnings"] == 10


def test_days_to_earnings_na_when_absent():
    out = derive_framework_tape(_series([10, 11, 12]))
    assert out["days_to_earnings"] is None


def test_overnight_gap():
    bars = _series([10, 11, 12])
    bars[-1].open = Decimal("11.5")  # gapped up from prev close 11
    out = derive_framework_tape(bars)
    assert out["last_overnight_gap"] == Decimal("11.5") / Decimal("11") - 1


def test_accepts_dict_rows():
    rows = [
        {
            "date": date(2026, 1, 1),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
        },
        {
            "date": date(2026, 1, 2),
            "open": 10,
            "high": 12,
            "low": 10,
            "close": 11,
            "volume": 100,
        },
        {
            "date": date(2026, 1, 3),
            "open": 11,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 100,
        },
    ]
    out = derive_framework_tape(rows)
    assert out["latest_close"] == Decimal("12")
    assert out["trend_3close"] == "up"
