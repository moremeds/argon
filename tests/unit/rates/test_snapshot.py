from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.rates.snapshot import build_rates_snapshot


def _point(obs_date: date, value: str):
    return {
        "obs_date": obs_date,
        "value": Decimal(value),
        "last_seen_at": datetime(2026, 5, 21, 21, tzinfo=UTC),
    }


def test_build_rates_snapshot_populates_live_fred_sections_without_static_fillers():
    snapshot = build_rates_snapshot(
        {
            "DGS2": [
                _point(date(2026, 5, 13), "4.00"),
                _point(date(2026, 5, 19), "4.07"),
                _point(date(2026, 5, 20), "4.13"),
            ],
            "DGS5": [_point(date(2026, 5, 20), "4.32")],
            "DGS10": [
                _point(date(2026, 5, 13), "4.46"),
                _point(date(2026, 5, 19), "4.61"),
                _point(date(2026, 5, 20), "4.67"),
            ],
            "DGS30": [_point(date(2026, 5, 20), "5.18")],
            "DFII10": [_point(date(2026, 5, 20), "2.13")],
            "T10YIE": [_point(date(2026, 5, 20), "2.48")],
            "T5YIFR": [_point(date(2026, 5, 20), "2.35")],
            "EFFR": [_point(date(2026, 5, 20), "3.63")],
            "SOFR": [_point(date(2026, 5, 20), "3.65")],
        },
        computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
    )

    assert snapshot.as_of == date(2026, 5, 20)
    assert len(snapshot.curve.points) == 11
    assert next(tile for tile in snapshot.summary if tile.label == "10Y").value == 4.67
    assert snapshot.decomposition.nominal_10y == 4.67
    assert snapshot.policy.effr == 3.63
    assert snapshot.supply.status == "missing"
    assert snapshot.positioning.status == "missing"
    assert snapshot.scorecard.groups
    assert snapshot.synthesis.duration_view


def test_build_rates_snapshot_requires_observations():
    try:
        build_rates_snapshot({}, computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC))
    except ValueError as exc:
        assert "rates observations" in str(exc)
    else:
        raise AssertionError("empty observations should not build a snapshot")
