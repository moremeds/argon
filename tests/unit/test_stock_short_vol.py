"""Per-ticker short-vol decision logic. Real TSLA 2026-06-24: spot 382.35, IV30 0.473."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.reports.stock_short_vol import build_short_vol, decide_short_vol

AS_OF = date(2026, 6, 24)
SPOT = 382.35
IV = 0.473
RV = 0.40
CLEAR_EARNINGS = date(2026, 10, 1)  # well beyond AS_OF + 45d (2026-08-08)


def test_trade_when_rich_sellable_and_earnings_clear():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "TRADE"
    assert sig.skip_reason is None
    assert sig.short_put is not None and sig.short_put < Decimal(str(SPOT))
    assert sig.long_put is not None and sig.long_put < sig.short_put
    assert sig.credit is not None and sig.credit > 0
    assert sig.max_loss is not None and sig.max_loss > 0
    assert sig.weight is not None and sig.weight > 0
    assert sig.short_delta == Decimal("0.25")
    assert sig.wing_delta == Decimal("0.125")


def test_skip_when_vol_not_rich():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.01,
        vrp_z_20=0.3,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert "not rich" in (sig.skip_reason or "")
    assert sig.weight == Decimal("0")
    assert sig.short_put is None


def test_skip_when_sector_not_sellable():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=False,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"


def test_skip_when_earnings_unknown():
    # passes_gate proves an earnings calendar EXISTS, but the next date is unknown →
    # never sell vol blind (matches scanner.gates.earnings_gate: None → block).
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=None,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "earnings date unavailable"


def test_macro_class_trades_without_earnings():
    # ETF/index sellable bucket: no earnings to clear, so unknown earnings must NOT
    # block (mirrors vrp_gate exempting non-single_name classes).
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=None,
        require_earnings=False,
    )
    assert sig.action == "TRADE"


def test_skip_when_earnings_in_window():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=date(2026, 7, 5),  # ~11 days out
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "earnings inside hold window"


def test_skip_when_no_iv():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=None,
        rv=RV,
        vrp=None,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no usable IV/spot"


def test_skip_and_no_decimal_nan_when_z_nonfinite():
    # early rolling-window rows carry NaN vrp_z_20 → must NOT reach Decimal("NaN")
    # (Pydantic rejects non-finite). Non-finite numerics normalize to None.
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=float("nan"),
        vrp_z_20=float("nan"),
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "insufficient vol history"
    assert sig.vrp_z is None and sig.vrp is None


class _StubRepo:
    def __init__(self, series):
        self._series = series

    def fetch_vrp_daily_series(self, ticker, *, limit=60):
        return self._series

    def fetch_vrp_harvest_by_sector(self):
        return []

    def fetch_vrp_harvest_multihorizon(self):
        return []

    def fetch_watchlist_sector(self, ticker):
        return "Technology"

    def fetch_historical_earnings_dates(self, ticker):
        return set()

    def fetch_latest_next_earnings_date(self, ticker):
        return CLEAR_EARNINGS


def test_build_returns_none_without_history():
    assert build_short_vol(_StubRepo([]), "TSLA", SPOT) is None


def test_build_skips_when_gate_blocks():
    series = [{"market_date": AS_OF, "iv": IV, "rv": RV, "vrp": 0.073, "vrp_z_20": 1.6}]
    sig = build_short_vol(_StubRepo(series), "TSLA", SPOT)
    # empty sellable sets → single_name gate returns None → SKIP
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"
