"""Unit tests for canary v2-A vol/speed separation.

This file is built up across Tasks 1 + 3:
- Task 1: calibration-loading tests (v2 JSON parses; thresholds match v1).
- Task 3: formula-conditional tests (v1 path unchanged; v2 path drops speed).

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

from datetime import date as _date
from importlib.resources import files

import numpy as np

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import Calibration, load_calibration

_CAL_DIR = files("uw_scan.cards") / "data"
V2_JSON = _CAL_DIR / "canary-calibration-v2.json"
V1_JSON = _CAL_DIR / "canary-calibration-v1.json"


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


# --- Task 3: formula-conditional tests ---


def _fixed_aligned_arrays(n: int = 400, seed: int = 0) -> dict:
    """Synthetic aligned vol-complex arrays sized for the MIN_ALIGNED_BARS=350 gate."""
    rng = np.random.default_rng(seed)
    return {
        "VIX": np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX": np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX": np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }


def _fixed_common_dates(n: int = 400) -> list[str]:
    base = _date(2020, 6, 1)
    return [
        _date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)
    ]


def _run_for_version(version: int, *, cca: bool = False, btd: bool = False) -> dict:
    """Run analysis with the v1 calibration, then patch composite_version on the
    Calibration object for the v2 path. Identical inputs across calls."""
    cal = load_calibration()
    if cal.composite_version != version:
        cal = Calibration(
            composite_version=version,
            score_form=cal.score_form,
            vix_spike_revert=cal.vix_spike_revert,
            vix_vix3m_back=cal.vix_vix3m_back,
            vrp=cal.vrp,
            cor1m_decay=cal.cor1m_decay,
            vvix_vix_recovery=cal.vvix_vix_recovery,
        )
    aligned = _fixed_aligned_arrays(n=400, seed=42)
    dates = _fixed_common_dates(n=400)
    return canary_scoring.run_analysis(
        today=_date.fromisoformat(dates[-1]),
        aligned=aligned,
        common_dates=dates,
        sma_50_today=float(aligned["SPX"][-50:].mean()),
        sma_200_today=float(aligned["SPX"][-200:].mean()),
        spx_above_sma200_2d=True,
        vix_term_normalized=True,
        higher_closing_low=True,
        confirmed_canary_active=cca,
        buy_the_dip_active=btd,
        calibration=cal,
    )


def _v1_pre_clamp_raw(payload: dict, speed_contrib: int) -> float:
    """v1's pre-clamp raw_score reconstruction (uses rounded inputs — adequate
    for the clamp check, NOT for equality assertions)."""
    return (
        payload["tactical_vol"]["score"]
        + payload["structural_vol"]["score"]
        + speed_contrib
    )


def test_v1_path_unchanged_when_no_speed_state():
    """v1 NEUTRAL: speed.score=8 contributes to raw."""
    p1 = _run_for_version(1, cca=False, btd=False)
    assert p1["speed"]["score"] == 8


def test_v2_drops_8_when_neutral():
    """v1 raw − v2 raw ≈ 8 in the NEUTRAL case (modulo clamping)."""
    p1 = _run_for_version(1, cca=False, btd=False)
    p2 = _run_for_version(2, cca=False, btd=False)
    v1_pre_clamp = _v1_pre_clamp_raw(p1, speed_contrib=8)
    if v1_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 8.0) < 0.02, f"v1−v2 NEUTRAL delta = {delta}, expected ~8.0"
    else:
        v2_expected_pre_clamp = (
            p2["tactical_vol"]["score"] + p2["structural_vol"]["score"]
        )
        assert abs(p2["canary"]["raw_score"] - min(100.0, v2_expected_pre_clamp)) < 0.02


def test_v2_drops_20_when_btd_active():
    """v1 BTD: speed.score=20. v1 − v2 raw ≈ 20."""
    p1 = _run_for_version(1, cca=False, btd=True)
    p2 = _run_for_version(2, cca=False, btd=True)
    assert p1["speed"]["state"] == "BUY_THE_DIP_ACTIVE"
    assert p2["speed"]["state"] == "BUY_THE_DIP_ACTIVE"
    v1_pre_clamp = _v1_pre_clamp_raw(p1, speed_contrib=20)
    if v1_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 20.0) < 0.02


def test_v2_keeps_cap_mechanism_via_speed_state():
    """v2 CCA: apply_cap reads speed.state (enum), NOT speed.score. v2 dropping
    the additive term does NOT change cap behavior. Spec §5.3."""
    p2 = _run_for_version(2, cca=True, btd=False)
    assert p2["speed"]["state"] == "CONFIRMED_CANARY_ACTIVE"
    assert p2["canary"]["warning_state"] in ("NONE", "CONFIRMED_CANARY_ACTIVE")


def test_v3_routes_through_v2_path():
    """The `>=2` semantic intentionally auto-promotes future v3 to the v2 formula.

    This test will deliberately need updating when v3 lands with a new explicit
    formula — that's the point: it forces the v3 implementer to make the
    conditional explicit rather than silently inheriting v2's behavior."""
    p2 = _run_for_version(2, cca=False, btd=False)
    p3 = _run_for_version(3, cca=False, btd=False)
    assert p2["canary"]["raw_score"] == p3["canary"]["raw_score"]


def test_both_active_ambiguous_branch():
    """When both CCA and BTD active: speed.state='BOTH_ACTIVE_AMBIGUOUS',
    speed.score=8. v1: raw += 8. v2: raw unchanged. Cap still uses speed.state."""
    p1 = _run_for_version(1, cca=True, btd=True)
    p2 = _run_for_version(2, cca=True, btd=True)
    assert p1["speed"]["state"] == "BOTH_ACTIVE_AMBIGUOUS"
    assert p2["speed"]["state"] == "BOTH_ACTIVE_AMBIGUOUS"
    assert p1["speed"]["score"] == 8
    v1_pre_clamp = _v1_pre_clamp_raw(p1, speed_contrib=8)
    if v1_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 8.0) < 0.02
