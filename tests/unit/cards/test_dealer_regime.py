"""Unit tests for the per-ticker dealer regime classifier."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.cards.dealer_regime import (
    classify_regime,
    compute_dealer_regime,
    compute_gamma_decay,
    normalize_score,
)


def test_normalize_score_caps_at_one() -> None:
    assert normalize_score(1e9, scale=1e6) == pytest.approx(1.0)
    assert normalize_score(-1e9, scale=1e6) == pytest.approx(-1.0)
    assert normalize_score(0, scale=1e6) == 0.0


def test_normalize_score_handles_none() -> None:
    assert normalize_score(None, scale=1e6) == 0.0


def test_classify_regime_long_gamma_is_dampening() -> None:
    sig = classify_regime(gamma=0.7, vanna=0.18, charm=-0.12)
    assert sig.label == "dampening"
    assert sig.score > 0
    assert "Long Γ" in sig.headline
    assert "Dampening" in sig.headline


def test_classify_regime_short_gamma_is_amplifying() -> None:
    sig = classify_regime(gamma=-0.4, vanna=0.0, charm=0.0)
    assert sig.label == "amplifying"
    assert sig.score < 0
    assert "Short Γ" in sig.headline


def test_classify_regime_near_zero_is_neutral() -> None:
    sig = classify_regime(gamma=0.02, vanna=0.0, charm=0.0)
    assert sig.label == "neutral"


def test_compute_gamma_decay_buckets_by_dte() -> None:
    today = date(2026, 5, 18)
    curve = [
        {"strike": Decimal("400"), "expiry": today, "net_gex": Decimal("-20133")},
        {
            "strike": Decimal("400"),
            "expiry": date(2026, 5, 20),
            "net_gex": Decimal("-8511"),
        },
        {
            "strike": Decimal("400"),
            "expiry": date(2026, 5, 22),
            "net_gex": Decimal("41550"),
        },
        {
            "strike": Decimal("400"),
            "expiry": date(2026, 5, 26),
            "net_gex": Decimal("5031"),
        },
    ]
    buckets = compute_gamma_decay(curve, today=today)
    by_dte = {b.dte: b for b in buckets}
    assert by_dte[0].net_gex == pytest.approx(-20133.0)
    assert by_dte[2].net_gex == pytest.approx(-8511.0)
    assert by_dte[4].net_gex == pytest.approx(41550.0)
    assert by_dte[8].net_gex == pytest.approx(5031.0)
    total_share = sum(abs(b.share_pct or 0) for b in buckets)
    assert total_share == pytest.approx(1.0, abs=1e-6)


def test_compute_gamma_decay_filters_expired() -> None:
    """Expired buckets (dte < 0) should be filtered out."""
    today = date(2026, 5, 18)
    curve = [
        {
            "strike": Decimal("400"),
            "expiry": date(2026, 5, 15),
            "net_gex": Decimal("9999"),
        },  # expired
        {
            "strike": Decimal("400"),
            "expiry": date(2026, 5, 20),
            "net_gex": Decimal("1000"),
        },
    ]
    buckets = compute_gamma_decay(curve, today=today)
    assert {b.dte for b in buckets} == {2}


def test_compute_gamma_decay_carries_gross_alongside_net() -> None:
    """A bucket with cancelling call/put gamma still shows gross magnitude."""
    today = date(2026, 5, 18)
    curve = [
        {
            "strike": Decimal("400"),
            "expiry": date(2026, 5, 22),
            "net_gex": Decimal("100"),
        },
        {
            "strike": Decimal("405"),
            "expiry": date(2026, 5, 22),
            "net_gex": Decimal("-100"),
        },
    ]
    buckets = compute_gamma_decay(curve, today=today)
    assert len(buckets) == 1
    assert buckets[0].net_gex == pytest.approx(0.0)
    assert buckets[0].gross_abs_gex == pytest.approx(200.0)


def test_compute_gamma_decay_empty_curve_returns_empty() -> None:
    assert compute_gamma_decay([], today=date(2026, 5, 18)) == []


def test_compute_dealer_regime_assembles_full_signal() -> None:
    out = compute_dealer_regime(
        ticker="TSLA",
        spot=410.0,
        net_gex=216_910.0,
        prev_close_net_gex=440_500.0,
        per_expiry_vanna=[Decimal("120000"), Decimal("-30000")],
        per_expiry_charm=[Decimal("-25000"), Decimal("10000")],
        strike_gex_curve=[
            {
                "strike": Decimal("450"),
                "expiry": date(2026, 5, 22),
                "net_gex": Decimal("46550"),
            },
            {
                "strike": Decimal("395"),
                "expiry": date(2026, 5, 22),
                "net_gex": Decimal("-12000"),
            },
            {
                "strike": Decimal("410"),
                "expiry": date(2026, 5, 18),
                "net_gex": Decimal("19210"),
            },
        ],
        levels={
            "call_wall": {"strike": Decimal("450"), "net_gex": Decimal("46550")},
            "put_wall": {"strike": Decimal("395"), "net_gex": Decimal("-966840")},
            "gex_flip": {"strike": Decimal("474.64"), "net_gex": Decimal("0")},
        },
        today=date(2026, 5, 18),
    )
    assert out.signal.label == "dampening"
    assert out.net_gex == pytest.approx(216_910.0)
    assert out.prev_close_net_gex == pytest.approx(440_500.0)
    assert out.odte_gex == pytest.approx(19_210.0)
    assert any(lvl.label.lower().startswith("call wall") for lvl in out.closest_levels)


def test_compute_dealer_regime_handles_missing_inputs() -> None:
    """Empty/None inputs should not crash; should land at neutral."""
    out = compute_dealer_regime(
        ticker="ZZZ",
        spot=None,
        net_gex=None,
        prev_close_net_gex=None,
        per_expiry_vanna=[],
        per_expiry_charm=[],
        strike_gex_curve=[],
        levels=None,
        today=date(2026, 5, 18),
    )
    assert out.signal.label == "neutral"
    assert out.closest_levels == []
    assert out.gamma_decay == []
