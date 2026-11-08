"""aggregates_from_screener: pcr_oi is put OI / call OI, never UW's put_call_ratio.

UW's spec defines the screener ``put_call_ratio`` as put VOLUME / call volume;
the scan stored it as pcr_oi until 2026-11-08. The row below is UW's own AAPL
spec example (docs/uw-samples/unusual_whales_api_spec.yaml), where the volume
and OI ratios differ, so a regression to the vendor field fails here.
"""

from __future__ import annotations

from decimal import Decimal

from uw_scan.models import BulkScreenerRow
from uw_scan.pipeline import aggregates_from_screener


def _row(**overrides) -> BulkScreenerRow:
    base = dict(
        ticker="AAPL",
        call_open_interest=3975333,
        put_open_interest=3564153,
        call_volume=990943,
        put_volume=808326,
        put_call_ratio=Decimal("0.815713920982337"),
    )
    base.update(overrides)
    return BulkScreenerRow(**base)


def test_pcr_oi_is_open_interest_ratio_not_vendor_volume_ratio() -> None:
    agg = aggregates_from_screener(_row(), aum=None)
    assert agg.pcr_oi == Decimal(3564153) / Decimal(3975333)
    assert agg.pcr_vol == Decimal(808326) / Decimal(990943)
    assert round(agg.pcr_vol, 6) == round(Decimal("0.815713920982337"), 6)
    assert agg.pcr_oi != agg.pcr_vol


def test_zero_puts_is_zero_and_zero_calls_is_no_ratio() -> None:
    agg = aggregates_from_screener(
        _row(put_volume=0, call_open_interest=0), aum=Decimal("5")
    )
    assert agg.pcr_vol == Decimal(0)
    assert agg.pcr_oi is None
    assert agg.aum == Decimal("5")


def test_missing_counts_give_no_ratio() -> None:
    agg = aggregates_from_screener(
        _row(put_open_interest=None, call_volume=None), aum=None
    )
    assert agg.pcr_oi is None
    assert agg.pcr_vol is None
