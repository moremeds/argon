from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.rates.calculations import (
    compute_curve,
    compute_decomposition,
    compute_slopes,
    compute_source_freshness,
    delta_bps,
    latest_on_or_before,
)


def _point(obs_date: date, value: str):
    return {
        "obs_date": obs_date,
        "value": Decimal(value),
        "last_seen_at": datetime(2026, 5, 21, 21, tzinfo=UTC),
    }


def test_latest_on_or_before_uses_prior_available_observation():
    points = [
        _point(date(2026, 5, 16), "4.50"),
        _point(date(2026, 5, 20), "4.67"),
    ]

    assert latest_on_or_before(points, date(2026, 5, 19))["value"] == Decimal("4.50")
    assert latest_on_or_before(points, date(2026, 5, 15)) is None


def test_delta_bps_converts_percent_points_to_basis_points():
    assert delta_bps(Decimal("4.67"), Decimal("4.61")) == 6.0
    assert delta_bps(None, Decimal("4.61")) is None


def test_compute_curve_outputs_reference_tenors_and_deltas():
    rows = {
        "DGS2": [
            _point(date(2026, 4, 20), "3.90"),
            _point(date(2026, 5, 13), "4.00"),
            _point(date(2026, 5, 19), "4.07"),
            _point(date(2026, 5, 20), "4.13"),
        ],
        "DGS10": [
            _point(date(2026, 4, 20), "4.26"),
            _point(date(2026, 5, 13), "4.46"),
            _point(date(2026, 5, 19), "4.61"),
            _point(date(2026, 5, 20), "4.67"),
        ],
    }

    points = compute_curve(rows, as_of=date(2026, 5, 20))
    two_year = next(point for point in points if point.tenor == "2Y")
    ten_year = next(point for point in points if point.tenor == "10Y")

    assert two_year.value == 4.13
    assert two_year.delta_1d_bps == 6.0
    assert ten_year.delta_1w_bps == 21.0
    assert ten_year.delta_1m_bps == 41.0
    assert next(point for point in points if point.tenor == "30Y").status == "missing"


def test_compute_slopes_includes_spreads_and_butterfly():
    points = compute_curve(
        {
            "DGS3MO": [_point(date(2026, 5, 20), "3.67")],
            "DGS2": [_point(date(2026, 5, 20), "4.13")],
            "DGS5": [_point(date(2026, 5, 20), "4.32")],
            "DGS10": [_point(date(2026, 5, 20), "4.67")],
            "DGS30": [_point(date(2026, 5, 20), "5.18")],
        },
        as_of=date(2026, 5, 20),
    )

    slopes = {row.label: row.value_bps for row in compute_slopes(points)}

    assert slopes["2s10s"] == 54.0
    assert slopes["5s30s"] == 86.0
    assert slopes["3m10y"] == 100.0
    assert slopes["2s5s10s butterfly"] == -16.0


def test_compute_decomposition_uses_live_nominal_real_and_breakeven():
    decomp = compute_decomposition(
        {
            "DGS10": [_point(date(2026, 5, 20), "4.67")],
            "DFII10": [_point(date(2026, 5, 20), "2.13")],
            "T10YIE": [_point(date(2026, 5, 20), "2.48")],
            "T5YIFR": [_point(date(2026, 5, 20), "2.35")],
        },
        as_of=date(2026, 5, 20),
    )

    assert decomp.nominal_10y == 4.67
    assert decomp.real_10y == 2.13
    assert decomp.breakeven_10y == 2.48
    assert decomp.forward_inflation_5y5y == 2.35
    assert decomp.term_forward_compensation == 0.06


def test_compute_source_freshness_marks_missing_series():
    freshness = compute_source_freshness(
        {
            "DGS10": [_point(date(2026, 5, 20), "4.67")],
            "DGS2": [],
        },
        as_of=date(2026, 5, 20),
    )

    by_id = {row.id: row for row in freshness}
    assert by_id["DGS10"].status == "ok"
    assert by_id["DGS10"].latest_obs_date == date(2026, 5, 20)
    assert by_id["DGS2"].status == "missing"
