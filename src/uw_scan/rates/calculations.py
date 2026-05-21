"""Pure calculations for the US rates mirror."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    RatesCurvePoint,
    RatesDecomposition,
    RatesSlopeMetric,
    RatesSourceFreshness,
)
from uw_scan.rates.series import YIELD_CURVE_SERIES


def latest_on_or_before(
    points: list[dict[str, Any]], target_date: date
) -> dict[str, Any] | None:
    eligible = [row for row in points if row.get("obs_date") <= target_date]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row["obs_date"])


def delta_bps(current: Decimal | None, prior: Decimal | None) -> float | None:
    if current is None or prior is None:
        return None
    return _float_bps(current - prior)


def compute_curve(
    points_by_series: dict[str, list[dict[str, Any]]], *, as_of: date
) -> list[RatesCurvePoint]:
    out: list[RatesCurvePoint] = []
    for tenor, series_id in YIELD_CURVE_SERIES.items():
        rows = points_by_series.get(series_id, [])
        current = latest_on_or_before(rows, as_of)
        current_value = _decimal_value(current)
        prior_1d = _decimal_value(latest_on_or_before(rows, as_of - timedelta(days=1)))
        prior_1w = _decimal_value(latest_on_or_before(rows, as_of - timedelta(days=7)))
        prior_1m = _decimal_value(latest_on_or_before(rows, as_of - timedelta(days=30)))
        out.append(
            RatesCurvePoint(
                tenor=tenor,
                series_id=series_id,
                value=_float_pct(current_value),
                delta_1d_bps=delta_bps(current_value, prior_1d),
                delta_1w_bps=delta_bps(current_value, prior_1w),
                delta_1m_bps=delta_bps(current_value, prior_1m),
                obs_date=current["obs_date"] if current is not None else None,
                status="ok" if current is not None else "missing",
            )
        )
    return out


def compute_slopes(curve_points: list[RatesCurvePoint]) -> list[RatesSlopeMetric]:
    values = {point.tenor: point.value for point in curve_points}
    return [
        _spread("2s10s", values.get("10Y"), values.get("2Y")),
        _spread("5s30s", values.get("30Y"), values.get("5Y")),
        _spread("3m10y", values.get("10Y"), values.get("3M")),
        _butterfly(values),
    ]


def compute_decomposition(
    points_by_series: dict[str, list[dict[str, Any]]], *, as_of: date
) -> RatesDecomposition:
    nominal = _latest_value(points_by_series, "DGS10", as_of)
    real = _latest_value(points_by_series, "DFII10", as_of)
    breakeven = _latest_value(points_by_series, "T10YIE", as_of)
    forward = _latest_value(points_by_series, "T5YIFR", as_of)
    fallback_be = nominal - real if nominal is not None and real is not None else None
    bei = breakeven if breakeven is not None else fallback_be
    term_forward = (
        nominal - real - bei
        if nominal is not None and real is not None and bei is not None
        else None
    )
    present = [value is not None for value in (nominal, real, bei, forward)]
    status = "ok" if all(present) else ("partial" if any(present) else "missing")
    return RatesDecomposition(
        nominal_10y=_float_pct(nominal),
        real_10y=_float_pct(real),
        breakeven_10y=_float_pct(bei),
        forward_inflation_5y5y=_float_pct(forward),
        term_forward_compensation=_float_pct(term_forward),
        status=status,
    )


def compute_source_freshness(
    points_by_series: dict[str, list[dict[str, Any]]],
) -> list[RatesSourceFreshness]:
    out: list[RatesSourceFreshness] = []
    for series_id, rows in points_by_series.items():
        latest = max(rows, key=lambda row: row["obs_date"]) if rows else None
        out.append(
            RatesSourceFreshness(
                id=series_id,
                label=series_id,
                latest_obs_date=latest["obs_date"] if latest is not None else None,
                last_seen_at=latest.get("last_seen_at") if latest is not None else None,
                status="ok" if latest is not None else "missing",
            )
        )
    return out


def _latest_value(
    points_by_series: dict[str, list[dict[str, Any]]],
    series_id: str,
    as_of: date,
) -> Decimal | None:
    return _decimal_value(latest_on_or_before(points_by_series.get(series_id, []), as_of))


def _decimal_value(row: dict[str, Any] | None) -> Decimal | None:
    if row is None or row.get("value") is None:
        return None
    value = row["value"]
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _float_pct(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01")))


def _float_bps(value: Decimal) -> float:
    return float((value * Decimal("100")).quantize(Decimal("0.1")))


def _spread(label: str, long_value: float | None, short_value: float | None):
    if long_value is None or short_value is None:
        return RatesSlopeMetric(label=label, value_bps=None, status="missing")
    return RatesSlopeMetric(
        label=label,
        value_bps=round((long_value - short_value) * 100, 1),
        status="ok",
    )


def _butterfly(values: dict[str, float | None]) -> RatesSlopeMetric:
    two = values.get("2Y")
    five = values.get("5Y")
    ten = values.get("10Y")
    if two is None or five is None or ten is None:
        return RatesSlopeMetric(
            label="2s5s10s butterfly", value_bps=None, status="missing"
        )
    return RatesSlopeMetric(
        label="2s5s10s butterfly",
        value_bps=round((2 * five - two - ten) * 100, 1),
        status="ok",
    )
