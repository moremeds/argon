"""Theta Harvester pure compute. Constants ported verbatim from radon's
scripts/theta_harvester_scanner.py — see docs/research/2026-07-28-radon-scanner-port-backlog.md."""

import dataclasses
import math
from datetime import date

import pytest

from uw_scan.scanners.theta_harvester import (
    DealerSupport,
    OptionLeg,
    Strangle,
    dealer_support,
    range_metrics,
    realized_vol,
    select_short_strangle,
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


# ---------------------------------------------------------------------------
# FROZEN REAL CAPTURE — IWM, session 2026-07-24, expiry 2026-08-21 (28 DTE).
# Every number below was read out of option_wizard_local's
# option_surface_grid_daily / daily_ohlc / iv_rank_history and pasted verbatim.
# Nothing here is invented, rounded, or a placeholder symbol.
# Re-derive with:
#   select strike, call_iv, call_delta, call_theta, call_gamma, call_vega,
#          put_iv, put_delta, put_theta, put_gamma, put_vega
#     from uw_scan.option_surface_grid_daily
#    where ticker='IWM' and market_date='2026-07-24' and expiry='2026-08-21'
#      and strike in (272, 284, 300, 306);
#
# IWM was chosen because it is the one watchlist name on that session whose
# real IV actually exceeds its realised vol (edge +9.72 vol points) — i.e. the
# only ticker for which the gates genuinely pass on real data. AAPL, the
# obvious choice, had IV 0.2292 vs HV20 0.2969 and FAILS the IV gate; a fixture
# built on it could only reach THETA_HARVEST by inventing prices.
# ---------------------------------------------------------------------------
_AS_OF = date(2026, 7, 24)
_EXP = date(2026, 8, 21)  # 28 DTE — closest to radon's 30-day preference
_SPOT = 291.44  # option_surface_grid_daily.underlying_spot
_IV = 0.208  # iv_rank_history.volatility
_HV20 = 0.1107879091536324
_HV60 = 0.18596313086572983
_TREND_21D = -1.8605278236543121
_RANGE_SCORE = 0.5346021068062862

# The real ~16-delta wings — the pair radon's selector targets.
_PUT_16D = OptionLeg(
    _EXP,
    272.0,
    "P",
    0.251489543772415,
    -0.154573982720319,
    -0.0861128240264245,
    0.0117240381034907,
    0.191878725809937,
)
_CALL_16D = OptionLeg(
    _EXP,
    306.0,
    "C",
    0.172509740706994,
    0.156401472783266,
    -0.0595290822132382,
    0.0172246813925854,
    0.193372401778545,
)
# The real ~30-delta pair, used to prove the selector prefers the 16-delta one.
_PUT_30D = OptionLeg(
    _EXP,
    284.0,
    "P",
    0.218730053018397,
    -0.327454819434478,
    -0.113677825209739,
    0.0204601161742457,
    0.291236782959359,
)
_CALL_30D = OptionLeg(
    _EXP,
    300.0,
    "C",
    0.187568622934882,
    0.293516725982416,
    -0.0929495970921554,
    0.0227497373480449,
    0.277693841589617,
)


def _leg(strike, right, delta, *, expiry=_EXP, theta=-0.0595290822132382):
    """A LONG contract in argon's stored convention.

    Used ONLY for the delta-band / DTE-window / straddle-spot rejection tests,
    which exercise pure predicates where the greek magnitudes are irrelevant —
    the deltas are the input under test. Anything asserting on pricing, greeks
    or gates uses the frozen real legs above instead.

    option_surface_grid_daily holds long-contract greeks — verified on
    2026-07-24: call_theta in [-9.22, 0], call_gamma in [0, 4.34]. Every
    fixture in this file must use those signs, or the tests will validate a
    convention production never sees.
    """
    return OptionLeg(
        expiry=expiry,
        strike=strike,
        right=right,
        iv=0.172509740706994,
        delta=delta,
        theta=theta,  # <= 0: long option decays
        gamma=0.0172246813925854,  # >= 0: long option is convex
        vega=0.193372401778545,  # >= 0: long option is long vol
    )


def test_selected_strangle_carries_short_position_greek_signs():
    # THE regression guard for this port, on the real IWM 2026-07-24 capture.
    # Grid legs are long-convention, the position is short, so Strangle must
    # flip every greek. Without this, gates["theta_positive"] is False for
    # every row ever scanned and the THETA_HARVEST verdict is unreachable in
    # production while the tests still pass.
    out = select_short_strangle([_PUT_16D, _CALL_16D], spot=_SPOT, as_of=_AS_OF)
    assert out is not None
    assert out.theta == pytest.approx(0.145641906239663)
    assert out.gamma == pytest.approx(-0.028948719496076)
    assert out.vega == pytest.approx(-0.385251127588482)
    assert out.net_delta == pytest.approx(-0.001827490062947)
    assert out.theta > 0 and out.gamma < 0 and out.vega < 0


def test_select_short_strangle_prefers_legs_nearest_target_delta():
    # Both real pairs from the same real expiry: ~16-delta (radon's target) and
    # ~30-delta. The 16-delta pair wins on the selection score.
    out = select_short_strangle(
        [_PUT_16D, _CALL_16D, _PUT_30D, _CALL_30D], spot=_SPOT, as_of=_AS_OF
    )
    assert isinstance(out, Strangle)
    assert (out.put.strike, out.call.strike) == (272.0, 306.0)
    assert out.dte == 28


def test_select_short_strangle_rejects_legs_outside_dte_window():
    too_soon = date(2026, 7, 27)  # 3 DTE, under MIN_DTE=7
    legs = [
        _leg(272.0, "P", -0.154573982720319, expiry=too_soon),
        _leg(306.0, "C", 0.156401472783266, expiry=too_soon),
    ]
    assert select_short_strangle(legs, spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_rejects_legs_outside_delta_band():
    # 0.45 delta is above radon's 0.35 candidate ceiling; 0.02 is below the
    # 0.05 floor. Neither side yields a usable candidate.
    legs = [_leg(288.0, "P", -0.45), _leg(340.0, "C", 0.02)]
    assert select_short_strangle(legs, spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_requires_strikes_to_straddle_spot():
    # Both legs OTM on the same side -> not a strangle.
    legs = [_leg(300.0, "P", -0.154573982720319), _leg(306.0, "C", 0.156401472783266)]
    assert select_short_strangle(legs, spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_will_not_pair_across_expiries():
    other = dataclasses.replace(_CALL_16D, expiry=date(2026, 9, 18))
    assert select_short_strangle([_PUT_16D, other], spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_breaks_ties_deterministically():
    # Two pairs with identical selection scores must resolve the same way on
    # every run and every row ordering — otherwise a rescan can silently swap
    # the persisted contract and orphan its own markouts.
    alt_put = dataclasses.replace(_PUT_16D, strike=271.0)
    alt_call = dataclasses.replace(_CALL_16D, strike=307.0)
    forward = select_short_strangle(
        [_PUT_16D, _CALL_16D, alt_put, alt_call], spot=_SPOT, as_of=_AS_OF
    )
    reverse = select_short_strangle(
        [alt_call, alt_put, _CALL_16D, _PUT_16D], spot=_SPOT, as_of=_AS_OF
    )
    assert forward is not None and reverse is not None
    assert (forward.put.strike, forward.call.strike) == (
        reverse.put.strike,
        reverse.call.strike,
    )
