"""AUM unit normalization.

UW returns `aum` in billions for the 12 SPDR sector ETFs and in raw dollars for
everything else. Real values below are frozen from a live UW probe on
2026-07-24 (docs/research/2026-07-26-sector-crowding-probe.md).
"""

from decimal import Decimal

import pytest

from uw_scan.storage.market_data import normalize_etf_aum


def test_billions_scaled_to_dollars():
    # XLK, live UW /api/etfs/XLK/info on 2026-07-24 -> 180.775642 (billions)
    assert normalize_etf_aum(Decimal("180.775642")) == Decimal("180775642000")


def test_raw_dollars_passed_through():
    # SOXX, same probe -> already raw dollars
    assert normalize_etf_aum(Decimal("45064294868")) == Decimal("45064294868")


def test_idempotent():
    once = normalize_etf_aum(Decimal("180.775642"))
    assert normalize_etf_aum(once) == once


def test_none_passes_through():
    assert normalize_etf_aum(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        (Decimal("743.252024"), Decimal("743252024000")),  # SPY, billions
        (Decimal("465904858198"), Decimal("465904858198")),  # QQQ, dollars
        (Decimal("11700000000"), Decimal("11700000000")),  # IGV, dollars
    ],
)
def test_probe_universe(raw, expected):
    assert normalize_etf_aum(raw) == expected
