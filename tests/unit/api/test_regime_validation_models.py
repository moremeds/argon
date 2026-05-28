"""Contract tests for the regime-validation Pydantic models."""

from __future__ import annotations

from uw_scan.api.models.regime_validation import (
    VcgStressHistoryEntry,
    VcgStressHistorySummary,
    VcgStressHistorySummaryRow,
    VcgValidationResponse,
)


def test_stress_history_entry_forward_return_fields_default_none() -> None:
    entry = VcgStressHistoryEntry(date="2020-03-16", interpretation="PANIC")
    assert entry.fwd_5d_pct is None
    assert entry.fwd_20d_pct is None
    assert entry.fwd_60d_pct is None


def test_stress_history_summary_row_shape() -> None:
    row = VcgStressHistorySummaryRow(
        interpretation="PANIC",
        n=83,
        mean_fwd_5d_pct=0.20,
        mean_fwd_20d_pct=2.88,
        mean_fwd_60d_pct=2.29,
        winrate_20d_pct=53.0,
        winrate_60d_pct=41.0,
    )
    assert row.n == 83
    assert row.mean_fwd_20d_pct == 2.88


def test_validation_response_summary_optional() -> None:
    """stress_history_summary must default to None so we don't break
    existing clients before backfill."""
    resp = VcgValidationResponse(
        backtest_md="",
        n_days=0,
        composite_version="2",
        credit_proxy="HY_OAS",
        interpretation_distribution=[],
        named_crash_window=[],
    )
    assert resp.stress_history_summary is None
