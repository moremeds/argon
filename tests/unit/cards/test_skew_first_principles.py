"""Unit tests for skew first-principles derivers."""

from __future__ import annotations

import math

import pytest

from uw_scan.cards import skew_first_principles as sk


def test_rho_negative_when_vol_rises_as_price_falls():
    # Daily moves VARY in magnitude and IV moves opposite to price -> rho ~ -1.
    # (Constant-ratio decay would give zero-variance deltas and a degenerate corr.)
    rows = []
    p, iv = 100.0, 0.20
    for i in range(70):
        dr = -0.01 * (1.0 + 0.5 * math.sin(i))  # varying daily return, mostly down
        p *= 1.0 + dr
        iv += -dr * 2.0  # vol rises as price falls, by a varying amount
        rows.append({"price": p, "implied_volatility": iv})
    rho = sk.compute_spot_vol_rho(rows, window=63)
    assert rho is not None and rho < -0.9


def test_rho_none_when_insufficient_history():
    rows = [{"price": 100, "implied_volatility": 0.2}] * 10
    assert sk.compute_spot_vol_rho(rows, window=63) is None


def test_baseline_z_and_percentile():
    series = [0.0] * 200 + [10.0]
    out = sk.compute_skew_baseline(series, z_window=180, pct_window=252)
    assert out["z"] is not None and out["z"] > 3
    assert out["pct"] is not None and out["pct"] > 99


def test_baseline_cold_start_returns_none_z():
    out = sk.compute_skew_baseline([0.1, 0.2, 0.3], z_window=180, pct_window=252)
    assert out["z"] is None and out["pct"] is None


@pytest.mark.parametrize(
    "z,pct,expected",
    [
        (2.0, 90, "RICH"),
        (-2.0, 5, "CHEAP"),
        (0.0, 50, "NORMAL"),
        (None, 88, "RICH"),
        (None, 12, "CHEAP"),
        (None, None, "NORMAL"),
    ],
)
def test_classify_deviation(z, pct, expected):
    assert sk.classify_deviation(z, pct) == expected


def test_classify_skew_term():
    assert sk.classify_skew_term(0.02, 0.01) == "front_steep"
    assert sk.classify_skew_term(0.01, 0.02) == "back_steep"
    assert sk.classify_skew_term(0.010, 0.010) == "flat"
    assert sk.classify_skew_term(0.01, None) == "flat"


def test_classify_drive():
    assert sk.classify_drive(price_trend=-0.1, rho=-0.5) == "PANIC"
    assert sk.classify_drive(price_trend=0.1, rho=0.5) == "CHASE"
    assert sk.classify_drive(price_trend=0.1, rho=-0.5) == "STRUCTURAL"
    assert sk.classify_drive(price_trend=None, rho=-0.5) == "STRUCTURAL"


def test_classify_market_regime():
    calm = [{"market_date": i, "price": 100 + (i % 2)} for i in range(260)]
    assert sk.classify_market_regime(calm) in {"LOW_VOL", "HIGH_VOL", "UNKNOWN"}
    assert sk.classify_market_regime([]) == "UNKNOWN"


def test_asset_class_baseline_index_and_single_name():
    assert sk.asset_class_baseline("SPY")["asset_class"] == "index_macro"
    assert sk.asset_class_baseline("SPY")["expected_sign"] == "put_skew"
    assert sk.asset_class_baseline("NVDA")["asset_class"] == "single_name"
    assert sk.asset_class_baseline("HYG", sector="Credit")["asset_class"] == "credit"


def test_borrow_flag():
    assert sk.borrow_flag(2.0, 1.5) == "hard_to_borrow"
    assert sk.borrow_flag(0.25, 1.0) == "normal"
    assert sk.borrow_flag(None, None) == "unknown"


def test_sign_convention_guard():
    # Documented invariant: positive rr_25d means put-skew (downside hedging rich).
    assert sk.skew_sign_label(0.005) == "put_skew"
    assert sk.skew_sign_label(-0.012) == "call_skew"
    assert sk.skew_sign_label(0.0) == "flat"


def _verdict(v="TRADABLE_BEAR", conf="med"):
    return {
        "verdict": v,
        "confidence": conf,
        "forward_sep": -0.021,
        "borrow_clean": True,
        "survives_gate": True,
    }


def test_lean_neutral_when_no_verdict():
    out = sk.resolve_directional_lean(
        deviation_class="RICH",
        drive_class="PANIC",
        asset_class="single_name",
        regime="HIGH_VOL",
        borrow_flag="normal",
        earnings_gate="pass",
        verdict=None,
    )
    assert out["lean"] == "NEUTRAL"
    assert "not" in out["basis"].lower() or "no proven" in out["basis"].lower()


def test_lean_bearish_when_tradable_bear_and_gates_pass():
    out = sk.resolve_directional_lean(
        deviation_class="RICH",
        drive_class="PANIC",
        asset_class="single_name",
        regime="HIGH_VOL",
        borrow_flag="normal",
        earnings_gate="pass",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    assert out["lean"] == "BEARISH_TILT"
    assert out["confidence"] == "med"
    assert out["express"]


def test_lean_bullish_when_tradable_bull():
    out = sk.resolve_directional_lean(
        deviation_class="CHEAP",
        drive_class="STRUCTURAL",
        asset_class="single_name",
        regime="LOW_VOL",
        borrow_flag="normal",
        earnings_gate="pass",
        verdict=_verdict("TRADABLE_BULL"),
    )
    assert out["lean"] == "BULLISH_TILT"


def test_lean_suppressed_by_hard_to_borrow():
    out = sk.resolve_directional_lean(
        deviation_class="RICH",
        drive_class="PANIC",
        asset_class="single_name",
        regime="HIGH_VOL",
        borrow_flag="hard_to_borrow",
        earnings_gate="pass",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    assert out["lean"] == "NEUTRAL"
    assert "borrow" in out["basis"].lower()


def test_lean_suppressed_by_earnings_window():
    out = sk.resolve_directional_lean(
        deviation_class="RICH",
        drive_class="PANIC",
        asset_class="single_name",
        regime="HIGH_VOL",
        borrow_flag="normal",
        earnings_gate="block",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    assert out["lean"] == "NEUTRAL"
    assert "earnings" in out["basis"].lower()


def test_lean_none_verdict_value_is_neutral():
    out = sk.resolve_directional_lean(
        deviation_class="NORMAL",
        drive_class="STRUCTURAL",
        asset_class="single_name",
        regime="LOW_VOL",
        borrow_flag="normal",
        earnings_gate="pass",
        verdict=_verdict("NONE"),
    )
    assert out["lean"] == "NEUTRAL"


def test_lean_suppressed_when_verdict_regime_mismatches():
    out = sk.resolve_directional_lean(
        deviation_class="RICH",
        drive_class="PANIC",
        asset_class="single_name",
        regime="LOW_VOL",
        borrow_flag="normal",
        earnings_gate="pass",
        verdict={**_verdict("TRADABLE_BEAR"), "regime": "HIGH_VOL"},
    )
    assert out["lean"] == "NEUTRAL"
    assert "regime" in out["basis"].lower()


def test_build_read_includes_lean_and_summary():
    lean = sk.resolve_directional_lean(
        deviation_class="RICH",
        drive_class="PANIC",
        asset_class="single_name",
        regime="HIGH_VOL",
        borrow_flag="normal",
        earnings_gate="pass",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    read = sk.build_read(
        tail="put",
        rho=-0.5,
        rho_confirms=True,
        drive_class="PANIC",
        deviation_class="RICH",
        asset_class="single_name",
        class_expected_sign="mixed",
        borrow_flag="normal",
        earnings_gate="pass",
        directional_lean=lean,
    )
    assert read["directional_lean"]["lean"] == "BEARISH_TILT"
    assert isinstance(read["summary_line"], str) and read["summary_line"]
    # Spec §11: no directional language leaks into the RV summary body.
    assert (
        "BEARISH" not in read["summary_line"] and "BULLISH" not in read["summary_line"]
    )
    assert "Lean" not in read["summary_line"]
