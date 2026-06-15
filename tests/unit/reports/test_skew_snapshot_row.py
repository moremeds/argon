"""Unit test: build_skew_snapshot_row stitches derivers into a column dict."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.skew_analytics import build_skew_snapshot_row


def _rr_series(n=200, val=0.001):
    base = date(2026, 1, 1)
    rows = [
        {
            "market_date": base + timedelta(days=i),
            "risk_reversal": val,
            "expiry": base + timedelta(days=40),
        }
        for i in range(n)
    ]
    rows.append(
        {
            "market_date": base + timedelta(days=n),
            "risk_reversal": 0.05,
            "expiry": base + timedelta(days=40),
        }
    )  # spike RICH
    return rows


def _rv_series(n=210):
    base = date(2026, 1, 1)
    out = []
    p, iv = 100.0, 0.2
    for i in range(n):
        p *= 0.999
        iv += 0.0005
        out.append(
            {
                "market_date": base + timedelta(days=i),
                "price": p,
                "implied_volatility": iv,
                "realized_volatility": 0.18,
            }
        )
    return out


def test_build_row_rich_panic_neutral_without_verdict():
    rr = _rr_series()
    row = build_skew_snapshot_row(
        ticker="NVDA",
        market_date=rr[-1]["market_date"],
        rr_series=rr,
        expiry_rows=[{"expiry": date(2026, 8, 1), "risk_reversal": 0.05}],
        rv_series=_rv_series(),
        spy_rv_series=_rv_series(),
        positioning={"si_fee_rate": 0.25, "si_days_to_cover": 1.2},
        next_earnings_date=None,
        verdict=None,
        sector=None,
        today=rr[-1]["market_date"],
    )
    assert row["ticker"] == "NVDA"
    assert row["deviation_class"] == "RICH"
    assert row["directional_lean"] == "NEUTRAL"  # no verdict
    assert row["borrow_flag"] == "normal"
    assert row["spot"] is not None  # markout anchor present


def test_build_row_bearish_with_seeded_verdict():
    rr = _rr_series()
    row = build_skew_snapshot_row(
        ticker="NVDA",
        market_date=rr[-1]["market_date"],
        rr_series=rr,
        expiry_rows=[{"expiry": date(2026, 8, 1), "risk_reversal": 0.05}],
        rv_series=_rv_series(),
        spy_rv_series=_rv_series(),
        positioning={"si_fee_rate": 0.25, "si_days_to_cover": 1.2},
        next_earnings_date=None,
        verdict={
            "verdict": "TRADABLE_BEAR",
            "confidence": "med",
            "forward_sep": -0.02,
            "borrow_clean": True,
            "survives_gate": True,
        },
        sector=None,
        today=rr[-1]["market_date"],
    )
    assert row["directional_lean"] == "BEARISH_TILT"
    assert row["lean_confidence"] == "med"
