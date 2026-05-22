"""FRED series catalog for the US rates mirror."""

from __future__ import annotations

YIELD_CURVE_SERIES: dict[str, str] = {
    "1M": "DGS1MO",
    "3M": "DGS3MO",
    "6M": "DGS6MO",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "3Y": "DGS3",
    "5Y": "DGS5",
    "7Y": "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
}

REAL_YIELD_SERIES: dict[str, str] = {
    "5Y": "DFII5",
    "7Y": "DFII7",
    "10Y": "DFII10",
    "20Y": "DFII20",
    "30Y": "DFII30",
}

BREAKEVEN_SERIES: dict[str, str] = {
    "5Y": "T5YIE",
    "10Y": "T10YIE",
    "5Y5Y": "T5YIFR",
}

POLICY_SERIES: dict[str, str] = {
    "EFFR": "EFFR",
    "SOFR": "SOFR",
}

FED_PLUMBING_SERIES: dict[str, str] = {
    "assets": "WALCL",
    "reserves": "WRESBAL",
    "on_rrp": "RRPONTSYD",
    "tga": "WTREGEN",
}

CLEVE_EXPECTED_INFLATION_10Y = "CLEVE_EXPECTED_INFLATION_10Y"
CLEVE_REAL_RISK_PREMIUM_10Y = "CLEVE_REAL_RISK_PREMIUM_10Y"
CLEVE_INFLATION_RISK_PREMIUM_10Y = "CLEVE_INFLATION_RISK_PREMIUM_10Y"
CLEVE_MODEL_REAL_YIELD_10Y = "CLEVE_MODEL_REAL_YIELD_10Y"

CLEVELAND_FED_MODEL_SERIES: tuple[str, ...] = (
    CLEVE_EXPECTED_INFLATION_10Y,
    CLEVE_REAL_RISK_PREMIUM_10Y,
    CLEVE_INFLATION_RISK_PREMIUM_10Y,
    CLEVE_MODEL_REAL_YIELD_10Y,
)

SERIES_LABELS: dict[str, str] = {
    "DGS1MO": "1M Treasury nominal",
    "DGS3MO": "3M Treasury nominal",
    "DGS6MO": "6M Treasury nominal",
    "DGS1": "1Y Treasury nominal",
    "DGS2": "2Y Treasury nominal",
    "DGS3": "3Y Treasury nominal",
    "DGS5": "5Y Treasury nominal",
    "DGS7": "7Y Treasury nominal",
    "DGS10": "10Y Treasury nominal",
    "DGS20": "20Y Treasury nominal",
    "DGS30": "30Y Treasury nominal",
    "DFII5": "5Y TIPS real yield",
    "DFII7": "7Y TIPS real yield",
    "DFII10": "10Y TIPS real yield",
    "DFII20": "20Y TIPS real yield",
    "DFII30": "30Y TIPS real yield",
    "T5YIE": "5Y breakeven inflation",
    "T10YIE": "10Y breakeven inflation",
    "T5YIFR": "5Y5Y forward inflation",
    "EFFR": "Effective fed funds rate",
    "SOFR": "SOFR",
    "WALCL": "Fed total assets",
    "WRESBAL": "Reserve balances",
    "RRPONTSYD": "ON RRP operations",
    "WTREGEN": "Treasury General Account",
    CLEVE_EXPECTED_INFLATION_10Y: "Cleveland Fed 10Y expected inflation",
    CLEVE_REAL_RISK_PREMIUM_10Y: "Cleveland Fed 10Y real term premium",
    CLEVE_INFLATION_RISK_PREMIUM_10Y: "Cleveland Fed 10Y inflation risk premium",
    CLEVE_MODEL_REAL_YIELD_10Y: "Cleveland Fed 10Y model real yield",
}


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


RATES_FRED_SERIES: tuple[str, ...] = _dedupe(
    [
        *YIELD_CURVE_SERIES.values(),
        *REAL_YIELD_SERIES.values(),
        *BREAKEVEN_SERIES.values(),
        *POLICY_SERIES.values(),
        *FED_PLUMBING_SERIES.values(),
    ]
)
