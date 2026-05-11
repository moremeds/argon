from uw_scan.tracking import ReconciliationConfig, reconcile_oi_change


def test_reconcile_likely_opening_when_oi_follow_through_is_strong():
    assert (
        reconcile_oi_change(
            flow_volume=1000,
            previous_oi=500,
            current_oi=900,
            side_consistent=True,
            config=ReconciliationConfig(),
        )
        == "likely_opening"
    )


def test_reconcile_fading_when_volume_has_no_oi_follow_through():
    assert (
        reconcile_oi_change(
            flow_volume=1000,
            previous_oi=500,
            current_oi=530,
            side_consistent=True,
            config=ReconciliationConfig(),
        )
        == "fading"
    )


def test_reconcile_unknown_on_conflict():
    assert (
        reconcile_oi_change(
            flow_volume=1000,
            previous_oi=500,
            current_oi=900,
            side_consistent=False,
            config=ReconciliationConfig(),
        )
        == "unknown"
    )
