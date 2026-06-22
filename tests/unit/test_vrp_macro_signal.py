"""vrp-z size-weight rules — the dominant lever, as pure functions."""

import math

from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    MacroSignalConfig,
    size_weight,
)


def test_winner_defaults_are_the_promoted_config():
    assert WINNER.short_delta == 0.25
    assert WINNER.wing_delta == 0.125  # short_delta * wing_frac
    assert WINNER.hold_days == 30
    assert WINNER.cadence == 5
    assert WINNER.sizing == "ramp+"
    assert WINNER.structure == "bull_put_spread"


def test_ramp_plus_is_zero_until_rich_then_linear_to_full():
    # the winner: skip until vol is rich, size up linearly, cap at full
    assert size_weight(-1.0, WINNER) == 0.0
    assert size_weight(0.0, WINNER) == 0.0
    assert size_weight(0.25, WINNER) == 0.5  # halfway to ramp_full_z=0.5
    assert size_weight(0.5, WINNER) == 1.0
    assert size_weight(2.0, WINNER) == 1.0  # capped
    assert size_weight(None, WINNER) == 0.0  # insufficient history → skip


def test_gate0_is_a_hard_rich_gate():
    cfg = MacroSignalConfig(sizing="gate0")
    assert size_weight(-0.01, cfg) == 0.0
    assert size_weight(0.0, cfg) == 1.0
    assert size_weight(3.0, cfg) == 1.0
    assert size_weight(None, cfg) == 0.0


def test_ramp_derisks_below_zero_down_to_minus_half():
    cfg = MacroSignalConfig(sizing="ramp")
    assert size_weight(1.0, cfg) == 1.0
    assert size_weight(0.0, cfg) == 1.0
    assert size_weight(-0.25, cfg) == 0.5  # halfway to -ramp_full_z
    assert size_weight(-0.5, cfg) == 0.0
    assert size_weight(-1.0, cfg) == 0.0
    assert size_weight(None, cfg) == 0.0


def test_always_ignores_the_signal():
    cfg = MacroSignalConfig(sizing="always")
    assert size_weight(-5.0, cfg) == 1.0
    assert size_weight(None, cfg) == 1.0  # no signal → still full


def test_unknown_sizing_rule_raises():
    cfg = MacroSignalConfig(sizing="bogus")
    try:
        size_weight(0.3, cfg)
    except ValueError as exc:
        assert "bogus" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown sizing rule")


def test_ramp_plus_weight_is_monotonic_in_z():
    zs = [x / 20 for x in range(-20, 41)]
    ws = [size_weight(z, WINNER) for z in zs]
    assert all(b >= a - 1e-12 for a, b in zip(ws, ws[1:], strict=False))
    assert math.isclose(max(ws), 1.0) and min(ws) == 0.0
