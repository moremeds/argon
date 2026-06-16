"""Pure strike-by-delta structure selection (defined-risk, lean-gated)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards import skew_first_principles as sk


def _exposures():
    # one expiry at dte=33; put_delta spans the wing range we need
    ex = date(2026, 7, 18)
    return [
        {
            "expiry": ex,
            "strike": Decimal("105"),
            "dte": 33,
            "put_delta": Decimal("-0.50"),
        },
        {
            "expiry": ex,
            "strike": Decimal("100"),
            "dte": 33,
            "put_delta": Decimal("-0.38"),
        },
        {
            "expiry": ex,
            "strike": Decimal("95"),
            "dte": 33,
            "put_delta": Decimal("-0.26"),
        },
        {
            "expiry": ex,
            "strike": Decimal("88"),
            "dte": 33,
            "put_delta": Decimal("-0.13"),
        },
        {
            "expiry": ex,
            "strike": Decimal("80"),
            "dte": 33,
            "put_delta": Decimal("-0.05"),
        },
    ]


def test_bearish_picks_put_debit_spread_by_delta():
    fam = sk.structure_family({"lean": "BEARISH_TILT"})
    assert fam["kind"] == "put_debit_spread"
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=_exposures(), dte_lo=21, dte_hi=60, dte_pref=35
    )
    assert detail["status"] == "ready"
    assert detail["kind"] == "put_debit_spread"
    legs = detail["legs"]
    assert len(legs) == 2
    buy, sell = legs[0], legs[1]
    assert buy["action"] == "BUY" and buy["right"] == "PUT"
    assert buy["strike"] == Decimal("95")  # closest to -0.25
    assert sell["action"] == "SELL" and sell["strike"] == Decimal(
        "88"
    )  # closest to -0.12
    # defined-risk: long wing strike strictly above the short wing strike
    assert buy["strike"] > sell["strike"]


def test_no_chain_when_exposures_empty():
    fam = sk.structure_family({"lean": "BULLISH_TILT"})
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=[], dte_lo=21, dte_hi=60, dte_pref=35
    )
    assert detail["status"] == "no_chain"
    assert detail["legs"] == []


def test_neutral_has_no_family():
    assert sk.structure_family({"lean": "NEUTRAL"}) is None


def test_inverted_put_chain_yields_no_chain():
    # non-monotonic chain: the -0.25-target leg lands on a LOWER strike than the
    # -0.12-target leg -> would be a credit (short-premium) spread -> rejected.
    ex = date(2026, 7, 18)
    bad = [
        {
            "expiry": ex,
            "strike": Decimal("95"),
            "dte": 33,
            "put_delta": Decimal("-0.12"),
        },
        {
            "expiry": ex,
            "strike": Decimal("88"),
            "dte": 33,
            "put_delta": Decimal("-0.26"),
        },
    ]
    fam = sk.structure_family({"lean": "BEARISH_TILT"})
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=bad, dte_lo=21, dte_hi=60, dte_pref=35
    )
    assert detail["status"] == "no_chain"
    assert detail["legs"] == []


def test_bullish_picks_call_debit_spread_by_delta():
    ex = date(2026, 7, 18)
    chain = [
        {
            "expiry": ex,
            "strike": Decimal("100"),
            "dte": 33,
            "call_delta": Decimal("0.50"),
        },
        {
            "expiry": ex,
            "strike": Decimal("105"),
            "dte": 33,
            "call_delta": Decimal("0.26"),
        },
        {
            "expiry": ex,
            "strike": Decimal("112"),
            "dte": 33,
            "call_delta": Decimal("0.13"),
        },
        {
            "expiry": ex,
            "strike": Decimal("120"),
            "dte": 33,
            "call_delta": Decimal("0.05"),
        },
    ]
    fam = sk.structure_family({"lean": "BULLISH_TILT"})
    assert fam["kind"] == "call_debit_spread"
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=chain, dte_lo=21, dte_hi=60, dte_pref=35
    )
    assert detail["status"] == "ready"
    buy, sell = detail["legs"]
    assert buy["action"] == "BUY" and buy["right"] == "CALL"
    assert buy["strike"] == Decimal("105")  # closest to +0.25
    assert sell["strike"] == Decimal("112")  # closest to +0.12
    assert buy["strike"] < sell["strike"]  # defined-risk bull call (debit) spread
