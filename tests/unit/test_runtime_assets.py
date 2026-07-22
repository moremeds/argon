"""Runtime assets must resolve from the installed package, not the repo tree.

Regression guard for the 2026-07-08 Docker cutover: `docs/` is not copied into
the image, so anything read from there at runtime vanished in the container
while every checkout-based test stayed green.
"""

from __future__ import annotations

from uw_scan.cards.canary_calibration import (
    COMPOSITE_VERSION,
    DEFAULT_PATH,
    load_calibration,
)


def test_calibration_default_path_is_inside_the_package() -> None:
    resolved = str(DEFAULT_PATH)
    assert "/docs/" not in resolved, (
        f"calibration still resolves through docs/: {resolved}"
    )
    assert resolved.endswith(
        f"uw_scan/cards/data/canary-calibration-v{COMPOSITE_VERSION}.json"
    ), resolved


def test_calibration_loads_from_package_data() -> None:
    cal = load_calibration()
    assert cal.composite_version == COMPOSITE_VERSION
    assert cal.score_form == "linear"
    assert cal.vix_spike_revert.max_points > 0
