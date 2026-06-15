"""Edge-quality weights must sum to 100 (radon WEIGHTS assert parity)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from uw_scan.config import Settings


def test_default_edge_quality_weights_sum_to_100():
    s = Settings.from_env()
    total = (
        s.scanner_edge_quality_weight_dp_strength
        + s.scanner_edge_quality_weight_dp_sustained
        + s.scanner_edge_quality_weight_confluence
        + s.scanner_edge_quality_weight_vol_oi
        + s.scanner_edge_quality_weight_sweeps
    )
    assert total == Decimal("100")


def test_edge_quality_weights_validator_rejects_non_100(monkeypatch):
    monkeypatch.setenv("SCANNER_EDGE_QUALITY_WEIGHT_SWEEPS", "99")
    with pytest.raises(ValueError, match="edge-quality weights"):
        Settings.from_env()


def test_edge_quality_weight_map_helper():
    s = Settings.from_env()
    w = s.scanner_edge_quality_weights()
    assert set(w) == {"dp_strength", "dp_sustained", "confluence", "vol_oi", "sweeps"}
    assert sum(w.values()) == Decimal("100")
