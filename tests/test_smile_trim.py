"""Tests for _trim_flat_wings (smile-curve wing trimming).

Background: UW returns stale IV (often the same Decimal byte-for-byte) across
deep-OTM strikes that don't trade. These render as long horizontal segments
that obscure the real smile shape. The trimmer drops contiguous head/tail
runs of identical IV while preserving the smile's actual U-curve.
"""

from __future__ import annotations

from decimal import Decimal

from uw_scan.models import SmilePoint
from uw_scan.reports.volatility_series import (
    _clip_smile_to_spot_range,
    _trim_flat_wings,
)


def _pt(strike: str, iv: str | None) -> SmilePoint:
    return SmilePoint(
        strike=Decimal(strike),
        iv=Decimal(iv) if iv is not None else None,
    )


def test_trims_leading_flat_wing():
    pts = [
        _pt("5", "3.04"),
        _pt("10", "3.04"),
        _pt("100", "3.04"),
        _pt("400", "0.60"),
        _pt("405", "0.55"),
        _pt("410", "0.58"),
    ]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [
        Decimal("100"),
        Decimal("400"),
        Decimal("405"),
        Decimal("410"),
    ]


def test_trims_trailing_flat_wing():
    pts = [
        _pt("400", "0.60"),
        _pt("405", "0.55"),
        _pt("410", "0.58"),
        _pt("500", "0.95"),
        _pt("600", "0.95"),
        _pt("700", "0.95"),
    ]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [
        Decimal("400"),
        Decimal("405"),
        Decimal("410"),
        Decimal("500"),
    ]


def test_trims_both_wings():
    pts = [
        _pt("5", "3.04"),
        _pt("10", "3.04"),
        _pt("400", "0.60"),
        _pt("405", "0.55"),
        _pt("700", "0.95"),
        _pt("800", "0.95"),
    ]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [
        Decimal("10"),
        Decimal("400"),
        Decimal("405"),
        Decimal("700"),
    ]


def test_preserves_curve_without_flat_wings():
    pts = [
        _pt("400", "0.70"),
        _pt("405", "0.60"),
        _pt("410", "0.55"),
        _pt("415", "0.58"),
    ]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [p.strike for p in pts]


def test_short_curves_pass_through():
    # Fewer than 3 points — nothing to trim safely; return as-is.
    pts = [_pt("400", "0.60"), _pt("405", "0.60")]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [Decimal("400"), Decimal("405")]
    out_single = _trim_flat_wings([_pt("400", "0.60")])
    assert [p.strike for p in out_single] == [Decimal("400")]


def test_keeps_real_internal_flats_intact():
    # Body of curve has a legitimate flat segment — must NOT be trimmed.
    pts = [
        _pt("395", "0.70"),
        _pt("400", "0.55"),
        _pt("405", "0.55"),
        _pt("410", "0.55"),
        _pt("415", "0.60"),
    ]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [p.strike for p in pts]


def test_handles_unordered_input():
    pts = [
        _pt("700", "0.95"),
        _pt("5", "3.04"),
        _pt("400", "0.60"),
        _pt("10", "3.04"),
        _pt("800", "0.95"),
    ]
    out = _trim_flat_wings(pts)
    # After sort: [5, 10, 400, 700, 800] with IVs [3.04, 3.04, 0.60, 0.95, 0.95]
    # Trim leading 3.04 dupes → start at index 1 (strike 10).
    # Trim trailing 0.95 dupes → end at index 3 (strike 700).
    assert [p.strike for p in out] == [Decimal("10"), Decimal("400"), Decimal("700")]


def test_clip_keeps_strikes_within_frac_of_spot():
    spot = Decimal("400")
    pts = [
        _pt("100", "1.50"),
        _pt("250", "0.90"),
        _pt("300", "0.70"),
        _pt("400", "0.55"),
        _pt("500", "0.60"),
        _pt("540", "0.65"),
        _pt("700", "0.90"),
    ]
    out = _clip_smile_to_spot_range(pts, spot)
    # ±35% of 400 → [260, 540]
    assert [p.strike for p in out] == [
        Decimal("300"),
        Decimal("400"),
        Decimal("500"),
        Decimal("540"),
    ]


def test_clip_falls_back_when_spot_missing():
    pts = [_pt("100", "1.5"), _pt("400", "0.5"), _pt("700", "0.9")]
    out = _clip_smile_to_spot_range(pts, None)
    assert [p.strike for p in out] == [p.strike for p in pts]


def test_clip_falls_back_when_result_too_thin():
    # Spot way outside the chain leaves <3 points after clip — return full.
    pts = [_pt("100", "1.5"), _pt("105", "1.2"), _pt("110", "1.0")]
    out = _clip_smile_to_spot_range(pts, Decimal("1000"))
    assert [p.strike for p in out] == [p.strike for p in pts]


def test_iv_none_short_circuits_trim():
    # If wing values are None, equality check (== None == None) is True but we
    # explicitly require iv is not None before trimming, so None-wing points
    # are preserved.
    pts = [
        _pt("5", None),
        _pt("10", None),
        _pt("400", "0.60"),
        _pt("405", "0.55"),
        _pt("410", "0.58"),
    ]
    out = _trim_flat_wings(pts)
    assert [p.strike for p in out] == [p.strike for p in pts]
