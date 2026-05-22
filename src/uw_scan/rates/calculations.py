"""Pure calculations for the US rates mirror."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    RatesCurvePoint,
    RatesDecomposition,
    RatesDecompositionAttribution,
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
        attribution=compute_decomposition_attribution(points_by_series, as_of=as_of),
    )


def compute_decomposition_attribution(
    points_by_series: dict[str, list[dict[str, Any]]], *, as_of: date
) -> list[RatesDecompositionAttribution]:
    windows = [
        ("1D", as_of - timedelta(days=1)),
        ("1W", as_of - timedelta(days=7)),
        ("1M", as_of - timedelta(days=30)),
        ("YTD", date(as_of.year, 1, 1)),
    ]
    return [
        _decomposition_attribution_row(points_by_series, as_of, window, prior_date)
        for window, prior_date in windows
    ]


def compute_source_freshness(
    points_by_series: dict[str, list[dict[str, Any]]],
    *,
    as_of: date,
    stale_series: set[str] | None = None,
) -> list[RatesSourceFreshness]:
    out: list[RatesSourceFreshness] = []
    stale_series = stale_series or set()
    for series_id, rows in points_by_series.items():
        latest = max(rows, key=lambda row: row["obs_date"]) if rows else None
        status = _freshness_status(series_id, latest, as_of, stale_series)
        out.append(
            RatesSourceFreshness(
                id=series_id,
                label=series_id,
                latest_obs_date=latest["obs_date"] if latest is not None else None,
                last_seen_at=latest.get("last_seen_at") if latest is not None else None,
                status=status,
            )
        )
    return out


def _latest_value(
    points_by_series: dict[str, list[dict[str, Any]]],
    series_id: str,
    as_of: date,
) -> Decimal | None:
    return _decimal_value(latest_on_or_before(points_by_series.get(series_id, []), as_of))


def _decomposition_attribution_row(
    points_by_series: dict[str, list[dict[str, Any]]],
    as_of: date,
    window: str,
    prior_date: date,
) -> RatesDecompositionAttribution:
    nominal = _latest_value(points_by_series, "DGS10", as_of)
    real = _latest_value(points_by_series, "DFII10", as_of)
    breakeven = _breakeven_value(points_by_series, as_of)
    prior_nominal = _latest_value(points_by_series, "DGS10", prior_date)
    prior_real = _latest_value(points_by_series, "DFII10", prior_date)
    prior_breakeven = _breakeven_value(points_by_series, prior_date)

    nominal_delta = delta_bps(nominal, prior_nominal)
    real_delta = delta_bps(real, prior_real)
    breakeven_delta = delta_bps(breakeven, prior_breakeven)
    residual = _residual_delta(nominal_delta, real_delta, breakeven_delta)
    values = [nominal_delta, real_delta, breakeven_delta]
    status = "ok" if all(value is not None for value in values) else (
        "partial" if any(value is not None for value in values) else "missing"
    )
    return RatesDecompositionAttribution(
        window=window,
        nominal_10y_bps=nominal_delta,
        real_10y_bps=real_delta,
        breakeven_10y_bps=breakeven_delta,
        residual_bps=residual,
        driver=_attribution_driver(real_delta, breakeven_delta, residual),
        status=status,
    )


def _breakeven_value(
    points_by_series: dict[str, list[dict[str, Any]]], as_of: date
) -> Decimal | None:
    breakeven = _latest_value(points_by_series, "T10YIE", as_of)
    if breakeven is not None:
        return breakeven
    nominal = _latest_value(points_by_series, "DGS10", as_of)
    real = _latest_value(points_by_series, "DFII10", as_of)
    return nominal - real if nominal is not None and real is not None else None


def _residual_delta(
    nominal_delta: float | None,
    real_delta: float | None,
    breakeven_delta: float | None,
) -> float | None:
    if nominal_delta is None or real_delta is None or breakeven_delta is None:
        return None
    return round(nominal_delta - real_delta - breakeven_delta, 1)


def _attribution_driver(
    real_delta: float | None,
    breakeven_delta: float | None,
    residual: float | None,
) -> str | None:
    candidates = [
        ("Real rate", real_delta),
        ("Breakeven", breakeven_delta),
        ("Residual", residual),
    ]
    available = [(label, value) for label, value in candidates if value is not None]
    if not available:
        return None
    return max(available, key=lambda item: abs(item[1]))[0]


def _decimal_value(row: dict[str, Any] | None) -> Decimal | None:
    if row is None or row.get("value") is None:
        return None
    value = row["value"]
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _freshness_status(
    series_id: str,
    latest: dict[str, Any] | None,
    as_of: date,
    stale_series: set[str],
):
    if latest is None:
        return "missing"
    if series_id in stale_series:
        return "stale"
    if latest["obs_date"] < as_of:
        return "partial"
    return "ok"


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
