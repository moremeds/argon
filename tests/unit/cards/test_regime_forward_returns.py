"""Pure-function tests for regime_forward_returns.

Verifies the date-aligned LEAD-by-index logic on synthetic data (no DB).
"""

from __future__ import annotations

from datetime import date

import pytest
from uw_scan.cards.regime_forward_returns import (
    attach_forward_returns,
    summarize_stress_returns,
)


def _spx_series(rows: list[tuple[str, float]]) -> list[tuple[date, float]]:
    return [(date.fromisoformat(d), c) for d, c in rows]


def test_attach_forward_returns_basic_lead_logic() -> None:
    spx = _spx_series(
        [
            ("2026-01-02", 100.0),  # entry
            ("2026-01-03", 101.0),
            ("2026-01-04", 102.0),
            ("2026-01-05", 103.0),
            ("2026-01-06", 104.0),
            ("2026-01-07", 105.0),  # +5d from entry
        ]
    )
    entries = [{"date": "2026-01-02", "interpretation": "PANIC"}]

    enriched = attach_forward_returns(entries, spx, horizons=(5,))

    assert enriched[0]["fwd_5d_pct"] == 5.0  # (105 - 100) / 100 * 100


def test_attach_forward_returns_null_at_tail() -> None:
    """When entry date is within `horizon` of series tail, fwd return is None."""
    spx = _spx_series(
        [("2026-05-25", 100.0), ("2026-05-26", 101.0), ("2026-05-27", 102.0)]
    )
    entries = [{"date": "2026-05-27", "interpretation": "PANIC"}]

    enriched = attach_forward_returns(entries, spx, horizons=(5,))

    assert enriched[0]["fwd_5d_pct"] is None


def test_attach_forward_returns_handles_missing_spx_date() -> None:
    """If the entry date isn't in the SPX series (holiday alignment), return None."""
    spx = _spx_series([("2026-01-02", 100.0), ("2026-01-09", 101.0)])
    entries = [{"date": "2026-01-05", "interpretation": "PANIC"}]  # holiday

    enriched = attach_forward_returns(entries, spx, horizons=(5,))

    assert enriched[0]["fwd_5d_pct"] is None


def test_summarize_stress_returns_groups_by_interpretation() -> None:
    enriched = [
        {"interpretation": "PANIC", "fwd_20d_pct": 5.0, "fwd_60d_pct": 8.0},
        {"interpretation": "PANIC", "fwd_20d_pct": -3.0, "fwd_60d_pct": 2.0},
        {"interpretation": "PANIC", "fwd_20d_pct": None, "fwd_60d_pct": None},
        {"interpretation": "RISK_OFF", "fwd_20d_pct": 1.0, "fwd_60d_pct": 4.0},
    ]
    summary = summarize_stress_returns(enriched)
    by = {row["interpretation"]: row for row in summary}

    # PANIC: n=3 total, but means / winrates skip None
    assert by["PANIC"]["n"] == 3
    assert by["PANIC"]["mean_fwd_20d_pct"] == 1.0  # (5 + -3) / 2
    assert by["PANIC"]["winrate_20d_pct"] == 50.0  # 1 of 2 non-null positive
    # RISK_OFF: n=1
    assert by["RISK_OFF"]["n"] == 1
    assert by["RISK_OFF"]["mean_fwd_60d_pct"] == 4.0


def test_summarize_stress_returns_handles_all_null_horizon() -> None:
    """If every entry has None for a horizon, mean is None (not 0, not NaN)."""
    enriched = [
        {"interpretation": "PANIC", "fwd_20d_pct": None, "fwd_60d_pct": None},
    ]
    summary = summarize_stress_returns(enriched)
    assert summary[0]["mean_fwd_20d_pct"] is None
    assert summary[0]["winrate_20d_pct"] is None


def test_attach_forward_returns_rejects_unsorted_spx_series() -> None:
    """Defensive — silent wrong fwd returns from a refactored SQL
    dropping ORDER BY is worse than a loud crash."""
    unsorted = _spx_series(
        [("2026-01-03", 101.0), ("2026-01-02", 100.0)]  # out of order
    )
    with pytest.raises(ValueError, match="sorted ascending"):
        attach_forward_returns(
            [{"date": "2026-01-02", "interpretation": "PANIC"}], unsorted
        )


def test_attach_forward_returns_empty_entries() -> None:
    """Empty entry list returns empty list (no error)."""
    spx = _spx_series([("2026-01-02", 100.0)])
    assert attach_forward_returns([], spx) == []
