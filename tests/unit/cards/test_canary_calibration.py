from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, load_calibration


def test_load_calibration_returns_expected_signals():
    cal = load_calibration()
    assert cal.composite_version == COMPOSITE_VERSION
    assert cal.score_form in ("linear", "convex", "concave", "sigmoid")
    assert cal.vix_spike_revert.max_points == 15
    assert cal.vix_vix3m_back.max_points == 15
    assert cal.vrp.max_points == 21
    assert cal.cor1m_decay.max_points == 17
    assert cal.vvix_vix_recovery.max_points == 12
    # Total smooth-signal points == 80; speed contributes the remaining 20.
    smooth_total = sum(
        s.max_points
        for s in (
            cal.vix_spike_revert,
            cal.vix_vix3m_back,
            cal.vrp,
            cal.cor1m_decay,
            cal.vvix_vix_recovery,
        )
    )
    assert smooth_total == 80


def test_extras_are_preserved():
    cal = load_calibration()
    assert cal.vix_spike_revert.extras["spike_active_at_vix"] == 30.0
    assert cal.cor1m_decay.extras["peak_elevated_at"] == 60.0
