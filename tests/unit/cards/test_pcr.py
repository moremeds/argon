"""PCR delta-30d helper."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.cards.pcr import compute_pcr_delta_30d


def test_pcr_delta_returns_diff():
    assert compute_pcr_delta_30d(Decimal("1.75"), Decimal("1.50")) == Decimal("0.25")


def test_pcr_delta_none_when_prior_missing():
    assert compute_pcr_delta_30d(Decimal("1.75"), None) is None


def test_pcr_delta_none_when_today_missing():
    assert compute_pcr_delta_30d(None, Decimal("1.50")) is None
