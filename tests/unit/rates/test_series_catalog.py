from uw_scan.models import (
    RatesCurvePoint,
    RatesScorecardFactor,
    RatesSnapshotResponse,
)
from uw_scan.rates.series import POLICY_TARGET_SERIES, RATES_FRED_SERIES, YIELD_CURVE_SERIES


def test_yield_curve_catalog_has_all_reference_tenors():
    assert list(YIELD_CURVE_SERIES) == [
        "1M",
        "3M",
        "6M",
        "1Y",
        "2Y",
        "3Y",
        "5Y",
        "7Y",
        "10Y",
        "20Y",
        "30Y",
    ]
    assert YIELD_CURVE_SERIES["10Y"] == "DGS10"


def test_rates_fred_series_are_deduplicated():
    assert len(RATES_FRED_SERIES) == len(set(RATES_FRED_SERIES))
    for series_id in YIELD_CURVE_SERIES.values():
        assert series_id in RATES_FRED_SERIES
    for series_id in POLICY_TARGET_SERIES.values():
        assert series_id in RATES_FRED_SERIES


def test_rates_models_are_public_exports():
    assert RatesSnapshotResponse.__module__ == "uw_scan.models"
    assert RatesCurvePoint.__module__ == "uw_scan.models"
    assert RatesScorecardFactor.__module__ == "uw_scan.models"
