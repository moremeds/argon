"""Lens 3 — valuation overlay (tail-risk flag, NEVER a sizing input).

Computes real-price-of-gold percentile (CPI-deflated, USD) and two alternative
anchors: gold/M2 ratio, gold/SPX ratio. Returns a flag in {Low, Moderate,
High, Severe}. Per docs/research/gold-sdf-framework/07-valuation-overlay.md
this signal is exclusively contextual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ValuationOverlay:
    flag: str
    real_price_percentile: Decimal | None
    gold_m2_ratio_percentile: Decimal | None
    gold_spx_ratio_percentile: Decimal | None
    narrative_text: str


def flag_from_percentile(p: Decimal | None) -> str:
    if p is None:
        return "Low"
    if p < Decimal("0.5"):
        return "Low"
    if p < Decimal("0.75"):
        return "Moderate"
    if p < Decimal("0.9"):
        return "High"
    return "Severe"


def _last_value_before(
    series: list[tuple[date, Decimal]], cutoff: date
) -> Decimal | None:
    eligible = [v for d, v in series if d <= cutoff]
    return eligible[-1] if eligible else None


def _percentile(history: list[Decimal], current: Decimal) -> Decimal | None:
    if not history:
        return None
    below = sum(1 for v in history if v <= current)
    return Decimal(str(below / len(history))).quantize(Decimal("0.001"))


def _real_price_series(
    gold_series: list[tuple[date, Decimal]],
    cpi_series: list[tuple[date, Decimal]],
) -> list[Decimal]:
    if not cpi_series:
        return []
    cpi_sorted = sorted(cpi_series, key=lambda r: r[0])
    out: list[Decimal] = []
    for d, gold_v in sorted(gold_series, key=lambda r: r[0]):
        cpi_v: Decimal | None = None
        for cd, cv in cpi_sorted:
            if cd <= d:
                cpi_v = cv
            else:
                break
        if cpi_v is None or cpi_v == 0:
            continue
        out.append(gold_v / cpi_v)
    return out


def compute_valuation_overlay(
    *,
    gold_series: list[tuple[date, Decimal]],
    cpi_series: list[tuple[date, Decimal]],
    m2_series: list[tuple[date, Decimal]],
    spx_series: list[tuple[date, Decimal]],
    as_of: date,
) -> ValuationOverlay:
    real_series = _real_price_series(gold_series, cpi_series)
    real_now = real_series[-1] if real_series else None
    real_pct = _percentile(real_series, real_now) if real_now is not None else None

    m2_pct = None
    if m2_series:
        ratios: list[Decimal] = []
        for d, gold_v in sorted(gold_series, key=lambda r: r[0]):
            m2_v = _last_value_before(m2_series, d)
            if m2_v and m2_v != 0:
                ratios.append(gold_v / m2_v)
        if ratios:
            m2_pct = _percentile(ratios, ratios[-1])

    spx_pct = None
    if spx_series:
        ratios = []
        for d, gold_v in sorted(gold_series, key=lambda r: r[0]):
            spx_v = _last_value_before(spx_series, d)
            if spx_v and spx_v != 0:
                ratios.append(gold_v / spx_v)
        if ratios:
            spx_pct = _percentile(ratios, ratios[-1])

    flag = flag_from_percentile(real_pct)
    narrative = (
        f"Real-price percentile: {real_pct}; flag: {flag}. "
        "Mean-reversion risk is context, never a sizing input. "
        "See Lens 1 for whether structural support is intact."
    )
    return ValuationOverlay(
        flag=flag,
        real_price_percentile=real_pct,
        gold_m2_ratio_percentile=m2_pct,
        gold_spx_ratio_percentile=spx_pct,
        narrative_text=narrative,
    )
