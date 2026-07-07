"""Pure-function tests for the positioning signal derivation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.reports.positioning import (
    build_screener_row,
    build_signals,
    build_snapshot,
)

# Frozen real-ish HIMS positioning shape (values observed 2026-07-06 in the
# warm store; used here as a static fixture, no network).
_HIMS = {
    "ticker": "HIMS",
    "snapshot_date": date(2026, 7, 6),
    "si_pct_float": Decimal("0.2934941808"),
    "si_days_to_cover": Decimal("3.53"),
    "si_fee_rate": Decimal("0.4519"),
    "insider_net_flow": Decimal("753258606.0676"),
    "analyst_buy": 51,
    "analyst_hold": 54,
    "analyst_sell": 12,
    "analyst_target_avg": Decimal("25.4765"),
    "earn_reactions_positive": 0,
    "earn_reactions_total": 3,
    "next_er_date": date(2026, 8, 1),
}


def test_squeeze_score_elevated_high_si_low_fee():
    # si_pct_float 29% -> HIGH (2), dtc 3.53 -> elevated (1), fee 0.45% -> below (0)
    sig = build_signals(_HIMS, Decimal("20"))
    assert sig.squeeze_score == 3
    assert sig.squeeze_label == "ELEVATED"


def test_hard_to_borrow_scores_high():
    row = {
        "snapshot_date": date(2026, 7, 6),
        "si_pct_float": Decimal("0.25"),  # HIGH -> 2
        "si_days_to_cover": Decimal("6"),  # HIGH -> 2
        "si_fee_rate": Decimal("7.1"),  # HIGH -> 2
    }
    sig = build_signals(row, None)
    assert sig.squeeze_score == 6
    assert sig.squeeze_label == "HIGH"


def test_squeeze_none_when_all_inputs_missing():
    sig = build_signals({"snapshot_date": date(2026, 7, 6)}, None)
    assert sig.squeeze_score is None
    assert sig.squeeze_label == "unknown"


def test_insider_tilt_and_upside_and_base_rate():
    sig = build_signals(_HIMS, Decimal("20"))
    assert sig.insider_tilt == "BUYING"
    # (25.4765 - 20) / 20 * 100
    assert sig.analyst_implied_upside_pct == Decimal("27.3825")
    # (51 - 12) / (51 + 54 + 12)
    assert sig.analyst_rating_skew == Decimal("39") / Decimal("117")
    assert sig.er_positive_base_rate == Decimal("0")
    assert sig.days_to_next_er == 26


def test_upside_none_without_spot():
    sig = build_signals(_HIMS, None)
    assert sig.analyst_implied_upside_pct is None


def test_build_snapshot_unavailable():
    snap = build_snapshot("NOPE", None, None)
    assert snap.available is False
    assert snap.ticker == "NOPE"
    assert snap.signals.squeeze_label == "unknown"


def test_build_snapshot_roundtrips_columns():
    snap = build_snapshot("hims", _HIMS, Decimal("20"))
    assert snap.available is True
    assert snap.ticker == "HIMS"
    assert snap.si_pct_float == Decimal("0.2934941808")
    assert snap.analyst_buy == 51
    assert snap.signals.squeeze_label == "ELEVATED"


def test_screener_row_uses_joined_spot():
    row = {**_HIMS, "spot": Decimal("20")}
    sr = build_screener_row(row)
    assert sr.ticker == "HIMS"
    assert sr.squeeze_score == 3
    assert sr.insider_tilt == "BUYING"
    assert sr.analyst_implied_upside_pct == Decimal("27.3825")
