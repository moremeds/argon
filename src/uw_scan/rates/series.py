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

