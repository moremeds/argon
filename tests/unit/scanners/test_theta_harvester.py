"""Theta Harvester pure compute. Constants ported verbatim from radon's
scripts/theta_harvester_scanner.py — see docs/research/2026-07-28-radon-scanner-port-backlog.md."""

import math

import pytest
from uw_scan.scanners.theta_harvester import (
    DealerSupport,
    dealer_support,
    range_metrics,
    realized_vol,
)


def test_realized_vol_matches_hand_computed_annualised_sigma():
    # Deterministic alternating 1% moves: daily log-return std is exactly
    # 0.01*ln-ish, so annualised vol = std(log returns) * sqrt(252).
    closes = [100.0]
    for i in range(20):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    expected = math.sqrt(var) * math.sqrt(252)
    assert realized_vol(closes, 20) == pytest.approx(expected, rel=1e-9)


def test_realized_vol_returns_none_when_window_not_covered():
    assert realized_vol([100.0, 101.0], 20) is None


def test_range_metrics_flat_tape_scores_fully_range_bound():
    # No drift over 21 sessions -> trend 0 -> range_score clamps to 1.0.
    closes = [100.0] * 22
    trend, score = range_metrics(closes, hv20=0.25)
    assert trend == pytest.approx(0.0)
    assert score == pytest.approx(1.0)


def test_range_metrics_strong_trend_scores_zero():
    # +40% over 21 sessions dwarfs a 25%-vol 21-day expected move -> clamps to 0.
    closes = [100.0 * (1.0165**i) for i in range(22)]
    trend, score = range_metrics(closes, hv20=0.25)
    assert trend > 30.0
    assert score == pytest.approx(0.0)


def test_range_metrics_expected_move_uses_the_same_21_sessions_as_the_trend():
    # The expected move must be scaled over 21 sessions, matching closes[-22].
    # A 20-session scaling understates it by ~2.5% and tightens the gate.
    closes = [100.0] * 21 + [105.0]
    _, score = range_metrics(closes, hv20=0.25)
    expected_pct = 0.25 * math.sqrt(21.0 / 252) * 100.0
    assert score == pytest.approx(1.0 - 5.0 / (expected_pct * 1.25))


def test_range_metrics_returns_none_on_thin_history():
    # Must NOT return (0.0, 0.0): score 0.0 means "violently trending", so
    # encoding "unknown" that way silently fails the range gate on new listings.
    assert range_metrics([100.0] * 10, hv20=0.25) is None


def test_dealer_support_flags_support_above_positive_gex_flip():
    # Net GEX turns negative->positive at 95; spot 100 sits above the flip and
    # total net GEX is positive -> dealers are long gamma and damping moves.
    rows = [
        {"strike": 90.0, "call_gex": 1.0e8, "put_gex": -3.0e8},
        {"strike": 95.0, "call_gex": 4.0e8, "put_gex": -1.0e8},
        {"strike": 105.0, "call_gex": 5.0e8, "put_gex": -1.0e8},
    ]
    out = dealer_support(rows, spot=100.0)
    assert out == DealerSupport(label="SUPPORT", net_gex=5.0e8, gex_flip=95.0)


def test_dealer_support_flags_no_support_when_net_gex_negative():
    rows = [
        {"strike": 95.0, "call_gex": 1.0e8, "put_gex": -5.0e8},
        {"strike": 105.0, "call_gex": 1.0e8, "put_gex": -2.0e8},
    ]
    assert dealer_support(rows, spot=100.0).label == "NO_SUPPORT"


def test_dealer_support_holds_when_cumulative_gex_never_turns_negative():
    # Dealers long gamma at every strike: cumulative net GEX never crosses
    # zero, so there is no flip. Radon keyed SUPPORT on `flip is not None` and
    # therefore returned NO_SUPPORT here — a false negative on exactly the most
    # unambiguously dealer-long names.
    rows = [
        {"strike": 95.0, "call_gex": 2.0e8, "put_gex": -1.0e8},
        {"strike": 105.0, "call_gex": 3.0e8, "put_gex": -1.0e8},
    ]
    out = dealer_support(rows, spot=100.0)
    assert out.label == "SUPPORT"
    assert out.gex_flip is None
    assert out.net_gex == pytest.approx(3.0e8)


def test_dealer_support_unknown_without_rows():
    out = dealer_support([], spot=100.0)
    assert out == DealerSupport(label="UNKNOWN", net_gex=None, gex_flip=None)
