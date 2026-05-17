"""Lens 2 — cyclical posture (article zones + two-force narrative).

Thresholds (CPI 2/4%, T5YIFR 2.5/2.7/2.8%) are ARTICLE HEURISTICS — not
empirically calibrated. Phase A2 (open question Q24) calibrates against the
multi-indicator anchoring basket. Until then, the narrative must explicitly
label the zone as 'article-derived' and not present it as a Fed-quality regime.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CyclicalPosture:
    zone_label: str
    cpi_yoy: Decimal | None
    t5yifr: Decimal | None
    dfii10: Decimal | None
    dfii10_60d_change_bps: Decimal | None
    factors: dict[str, float]
    narrative_text: str


CPI_LOW = Decimal("2.0")
CPI_HIGH = Decimal("4.0")
T5YIFR_LOW = Decimal("2.5")
T5YIFR_MID = Decimal("2.7")
T5YIFR_HIGH = Decimal("2.8")


def classify_article_zone(cpi_yoy: Decimal, t5yifr: Decimal) -> str:
    """Article-derived heuristic. NOT empirically calibrated."""
    if cpi_yoy < CPI_LOW and t5yifr < T5YIFR_LOW:
        return "real-rate-driven"
    if CPI_LOW <= cpi_yoy < CPI_HIGH and t5yifr < T5YIFR_MID:
        return "moderate-trap"
    if cpi_yoy >= CPI_HIGH and t5yifr >= T5YIFR_HIGH:
        return "article-unanchored"
    return "transitional"


def compute_cyclical_posture(
    *,
    cpi_yoy: Decimal | None,
    t5yifr: Decimal | None,
    dfii10: Decimal | None,
    dfii10_60d_change_bps: Decimal | None,
    factors: dict[str, float],
    gauge_state: str,
) -> CyclicalPosture:
    if cpi_yoy is None or t5yifr is None:
        zone = "transitional"
    else:
        zone = classify_article_zone(cpi_yoy, t5yifr)

    narrative = _narrate_cyclical(zone, dfii10, dfii10_60d_change_bps, gauge_state)
    return CyclicalPosture(
        zone_label=zone,
        cpi_yoy=cpi_yoy,
        t5yifr=t5yifr,
        dfii10=dfii10,
        dfii10_60d_change_bps=dfii10_60d_change_bps,
        factors=factors,
        narrative_text=narrative,
    )


def _narrate_cyclical(
    zone: str,
    dfii10: Decimal | None,
    dfii10_60d_bps: Decimal | None,
    gauge_state: str,
) -> str:
    base = f"Article zone: '{zone}' (heuristic; thresholds not yet calibrated)."
    if gauge_state == "suspended":
        return (
            base + " Cyclical framework currently suspended — "
            "article view is informative-only, not actionable."
        )
    if dfii10_60d_bps is not None:
        direction = "tightening" if dfii10_60d_bps > 0 else "easing"
        base += (
            f" DFII10 60d change {dfii10_60d_bps:+.0f}bps — "
            f"discount-rate channel {direction}."
        )
    return base
