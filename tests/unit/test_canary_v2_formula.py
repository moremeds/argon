"""Unit tests for canary v2-A vol/speed separation.

This file is built up across Tasks 1 + 3:
- Task 1: calibration-loading tests (v2 JSON parses; thresholds match v1).
- Task 3: formula-conditional tests (v1 path unchanged; v2 path drops speed).

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.cards.canary_calibration import Calibration, load_calibration

V2_JSON = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "regime"
    / "canary-calibration-v2.json"
)
V1_JSON = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "regime"
    / "canary-calibration-v1.json"
)


def test_v2_calibration_parses_with_version_2():
    """The v2 JSON parses into a Calibration with composite_version=2."""
    cal = load_calibration(path=V2_JSON)
    assert isinstance(cal, Calibration)
    assert cal.composite_version == 2
    assert cal.score_form == "linear"


def test_v2_calibration_thresholds_match_v1():
    """v2 thresholds are bit-identical to v1 (only the version field changes).

    This is deliberate: v2-A tests a structural formula change with v1
    calibration held fixed, so any AUC change is attributable to the
    formula change, not threshold drift. Spec §5.4.
    """
    v1 = load_calibration(path=V1_JSON)
    v2 = load_calibration(path=V2_JSON)
    assert v1.vix_spike_revert == v2.vix_spike_revert
    assert v1.vix_vix3m_back == v2.vix_vix3m_back
    assert v1.vrp == v2.vrp
    assert v1.cor1m_decay == v2.cor1m_decay
    assert v1.vvix_vix_recovery == v2.vvix_vix_recovery
    assert v1.score_form == v2.score_form
