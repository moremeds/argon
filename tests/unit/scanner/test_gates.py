"""Gate logic — earnings (advisory), liquidity (advisory), regime (hard)."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.scanner.gates import (
    earnings_gate,
    liquidity_gate,
    regime_gate,
)


TODAY = date(2026, 5, 17)


def test_earnings_gate_passes_when_earnings_more_than_14_days_away():
    assert (
        earnings_gate(
            next_earnings_date=TODAY + timedelta(days=20),
            today=TODAY,
            window_days=14,
        )
        == "pass"
    )


def test_earnings_gate_blocks_when_earnings_within_14_days():
    assert (
        earnings_gate(
            next_earnings_date=TODAY + timedelta(days=7),
            today=TODAY,
            window_days=14,
        )
        == "block"
    )


def test_earnings_gate_blocks_when_earnings_unknown():
    # Conservative-block per xenon _parse_next_earnings.
    assert earnings_gate(next_earnings_date=None, today=TODAY, window_days=14) == "block"


def test_liquidity_gate_passes_at_threshold():
    assert liquidity_gate(option_volume=1000, min_volume=1000) == "pass"


def test_liquidity_gate_blocks_below_threshold():
    assert liquidity_gate(option_volume=999, min_volume=1000) == "block"


def test_liquidity_gate_blocks_on_none():
    assert liquidity_gate(option_volume=None, min_volume=1000) == "block"


def test_regime_gate_passes_on_favorable():
    assert (
        regime_gate(
            structural_posture_chip="FAVORABLE",
            block_chips=("SUSPENDED", "DEGRADED"),
        )
        == "pass"
    )


def test_regime_gate_blocks_on_suspended():
    assert (
        regime_gate(
            structural_posture_chip="SUSPENDED",
            block_chips=("SUSPENDED", "DEGRADED"),
        )
        == "block"
    )


def test_regime_gate_blocks_on_degraded():
    assert (
        regime_gate(
            structural_posture_chip="DEGRADED",
            block_chips=("SUSPENDED", "DEGRADED"),
        )
        == "block"
    )


def test_regime_gate_fails_open_on_missing_posture():
    # Per spec §4: missing posture → treat as NEUTRAL (pass). The
    # scanner must not freeze just because GOLD hasn't run yet.
    assert (
        regime_gate(
            structural_posture_chip=None,
            block_chips=("SUSPENDED", "DEGRADED"),
        )
        == "pass"
    )


def test_regime_gate_respects_custom_block_chips():
    # Allow operator to widen blocking via env override.
    assert (
        regime_gate(
            structural_posture_chip="STRETCHED",
            block_chips=("STRETCHED", "SUSPENDED", "DEGRADED"),
        )
        == "block"
    )
