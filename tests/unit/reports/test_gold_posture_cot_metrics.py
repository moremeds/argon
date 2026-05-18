"""Gold posture COT-derived metric helpers."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.cards.structural_flow import CotSnapshot
from uw_scan.reports.gold_posture import _cot_mm_4w_change_sigma


def test_cot_mm_4w_change_sigma_scores_latest_four_week_change():
    base = date(2026, 3, 6)
    mm_net_values = [
        Decimal("100"),
        Decimal("110"),
        Decimal("130"),
        Decimal("160"),
        Decimal("200"),
        Decimal("250"),
        Decimal("310"),
        Decimal("380"),
        Decimal("460"),
        Decimal("550"),
    ]
    rows = [
        CotSnapshot(release_date=base + timedelta(days=7 * idx), mm_net=value)
        for idx, value in enumerate(mm_net_values)
    ]

    metric = _cot_mm_4w_change_sigma(rows, as_of=date(2026, 5, 15))

    assert metric is not None
    assert float(metric) == pytest.approx(1.464, rel=0.001)


def test_cot_mm_4w_change_sigma_requires_enough_history():
    rows = [
        CotSnapshot(release_date=date(2026, 5, 1), mm_net=Decimal("100")),
        CotSnapshot(release_date=date(2026, 5, 8), mm_net=Decimal("110")),
    ]

    assert _cot_mm_4w_change_sigma(rows, as_of=date(2026, 5, 15)) is None
