"""The replay refusal must live in code, not in a comment."""

import pytest

from uw_scan.pipeline_replay_policy import (
    REPLAY_REFUSED,
    REPLAY_SAFE,
    ReplayRefused,
    assert_replayable,
)


def test_safe_dataset_passes():
    assert assert_replayable("oi_by_strike") is None


@pytest.mark.parametrize(
    "dataset",
    ["options_volume_daily", "short_interest_snapshots", "uw_positioning"],
)
def test_endpoints_that_ignore_date_are_refused(dataset):
    """Measured 2026-08-16: these three return a byte-identical body for
    date=2026-08-11 and date=2026-08-13, so the param is ignored and a
    historical stamp would present today's numbers as history."""
    with pytest.raises(ReplayRefused) as exc:
        assert_replayable(dataset)
    assert "ignores" in str(exc.value).lower()


def test_safe_and_refused_are_disjoint():
    assert not (REPLAY_SAFE & set(REPLAY_REFUSED))


def test_every_refusal_carries_its_measurement_date():
    for dataset, reason in REPLAY_REFUSED.items():
        assert "2026-08-16" in reason, (
            f"{dataset}: a refusal without the date it was measured is an "
            f"assumption, and assumptions in this registry have been wrong before"
        )
