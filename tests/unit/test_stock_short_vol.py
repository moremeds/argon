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


def test_skip_uses_gate_skip_reason_when_provided():
    # "no earnings calendar" must not masquerade as "sector vol not sellable".
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=False,
        gate_skip_reason="no earnings calendar",
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no earnings calendar"


class _StubRepo:
    def __init__(self, series, *, sellable_sector=None, has_earnings_calendar=False):
        self._series = series
        self._sellable_sector = sellable_sector
        self._has_earnings = has_earnings_calendar

    def fetch_vrp_daily_series(self, ticker, *, limit=60):
        return self._series

    def fetch_vrp_harvest_by_sector(self):
        if self._sellable_sector is None:
            return []
        return [
            {
                "sector": self._sellable_sector,
                "deviation_class": "RICH",
                "verdict": "HARVEST_SELLABLE",
            }
        ]

    def fetch_vrp_harvest_multihorizon(self):
        return []

    def fetch_watchlist_sector(self, ticker):
        return "Technology"

    def fetch_historical_earnings_dates(self, ticker):
        return {date(2026, 1, 15)} if self._has_earnings else set()

    def fetch_latest_next_earnings_date(self, ticker):
        return CLEAR_EARNINGS


def _row(d, iv=IV):
    return {"market_date": d, "iv": iv, "rv": RV, "vrp": 0.073, "vrp_z_20": 1.6}


def test_build_returns_none_without_history():
    assert build_short_vol(_StubRepo([]), "TSLA", SPOT) is None


def test_build_skips_when_sector_not_sellable():
    sig = build_short_vol(_StubRepo([_row(AS_OF)]), "TSLA", SPOT)
    # empty sellable sets → single_name gate returns None → SKIP with the sector reason
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"


def test_build_skips_with_no_earnings_calendar_reason():
    # sellable sector but no historical earnings → distinct, honest reason (not "sector")
    repo = _StubRepo([_row(AS_OF)], sellable_sector="Technology")
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "no earnings calendar"


def test_build_trades_through_real_gate_path():
    # sellable sector + earnings calendar + clear next print → populated TRADE row.
    repo = _StubRepo(
        [_row(AS_OF)], sellable_sector="Technology", has_earnings_calendar=True
    )
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "TRADE"
    assert sig.short_put is not None and sig.long_put is not None
    assert sig.as_of == AS_OF


def test_build_walks_back_past_null_iv_latest_row():
    # newest row has NULL iv; the card must use the most recent usable row, not go dead.
    newer, older = date(2026, 6, 24), date(2026, 6, 23)
    series = [_row(newer, iv=None), _row(older, iv=IV)]  # DESC, like the real query
    repo = _StubRepo(series, sellable_sector="Technology", has_earnings_calendar=True)
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "TRADE"  # did NOT skip "no usable IV/spot"
    assert sig.as_of == older  # as_of reflects the row actually used
    assert sig.iv == Decimal(str(IV))
