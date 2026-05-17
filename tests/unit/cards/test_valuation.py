"""Lens 3 — valuation overlay tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.valuation import (
    compute_valuation_overlay,
    flag_from_percentile,
)


def test_flag_thresholds():
    assert flag_from_percentile(Decimal("0.30")) == "Low"
    assert flag_from_percentile(Decimal("0.60")) == "Moderate"
    assert flag_from_percentile(Decimal("0.80")) == "High"
    assert flag_from_percentile(Decimal("0.95")) == "Severe"


def test_valuation_overlay_severe_at_extreme():
    base = date(2020, 1, 1)
    gold = [(base + timedelta(days=i), Decimal(str(1500 + i))) for i in range(1500)]
    cpi = [(base + timedelta(days=i * 30), Decimal("100")) for i in range(50)]
    overlay = compute_valuation_overlay(
        gold_series=gold,
        cpi_series=cpi,
        m2_series=[],
        spx_series=[],
        as_of=base + timedelta(days=1500),
    )
    assert overlay.real_price_percentile is not None
    assert overlay.real_price_percentile > Decimal("0.85")
    assert overlay.flag in ("High", "Severe")
