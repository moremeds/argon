"""Country → bucket classification for CB gold reserve flows.

Default per docs/research/gold-sdf-framework/05-structural-flow-factors.md.
Revisable without migration.
"""

from __future__ import annotations

STRATEGIC_ACCUMULATORS = frozenset({"CHN", "IND", "RUS", "TUR"})
TACTICAL_DEFENDERS = frozenset({"EGY", "KAZ", "AZE"})
RESERVE_DIVERSIFIERS = frozenset(
    {
        "POL",
        "CZE",
        "SGP",
        "HUN",
        "QAT",
        "PHL",
        "THA",
        "MEX",
        "BRA",
        "ARG",
        "DEU",
        "FRA",
        "ITA",
        "JPN",
        "GBR",
        "USA",
        "CHE",
        "NLD",
    }
)


def classify_bucket(country_iso3: str) -> str:
    code = country_iso3.upper()
    if code in STRATEGIC_ACCUMULATORS:
        return "strategic_accumulator"
    if code in TACTICAL_DEFENDERS:
        return "tactical_defender"
    return "reserve_diversifier"
