"""compute_gex_flip: negative→positive net-GEX crossing nearest to spot.

Regression tests for issue #123 — the old implementation kept only crossings
at strikes <= spot, silently returning None for the entire short-gamma regime
shape (net GEX negative through/below spot, crossing only above).
"""

from uw_scan.scanners.gex import compute_gex_flip


def _profile(net_by_strike: dict[float, float]) -> list[dict]:
    return [
        {"strike": s, "net_gex": g, "call_gex": 0.0, "put_gex": 0.0}
        for s, g in sorted(net_by_strike.items())
    ]


def test_flip_below_spot_preserved() -> None:
    # Long-gamma shape: negative tail below, positive through spot.
    profile = _profile({7000: -5.0, 7100: -2.0, 7200: 3.0, 7300: 6.0})
    assert compute_gex_flip(profile, spot=7250.0) == 7200


def test_flip_above_spot_now_returned() -> None:
    # Short-gamma regime: net GEX negative through and below spot, the
    # negative→positive crossing only appears at an upper strike. The old
    # `strike <= spot` filter returned None here.
    profile = _profile({7000: -8.0, 7200: -4.0, 7400: -1.0, 7600: 2.0})
    assert compute_gex_flip(profile, spot=7266.0) == 7600


def test_multiple_crossings_returns_nearest_to_spot() -> None:
    # Crossings at 7100 (below) and 7350 (above); spot 7300 is nearer 7350.
    profile = _profile(
        {7000: -3.0, 7100: 1.0, 7200: -2.0, 7350: 4.0, 7500: 5.0}
    )
    assert compute_gex_flip(profile, spot=7300.0) == 7350
    # Same profile, spot near the lower crossing.
    assert compute_gex_flip(profile, spot=7120.0) == 7100


def test_no_crossing_returns_none() -> None:
    all_negative = _profile({7000: -3.0, 7100: -2.0, 7200: -1.0})
    assert compute_gex_flip(all_negative, spot=7100.0) is None
    all_positive = _profile({7000: 1.0, 7100: 2.0, 7200: 3.0})
    assert compute_gex_flip(all_positive, spot=7100.0) is None


def test_empty_profile_returns_none() -> None:
    assert compute_gex_flip([], spot=7100.0) is None
