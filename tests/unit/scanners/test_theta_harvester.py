"""Theta Harvester pure compute. Constants ported verbatim from radon's
scripts/theta_harvester_scanner.py — see docs/research/2026-07-28-radon-scanner-port-backlog.md."""

import dataclasses
import math
from datetime import date

import pytest

from uw_scan.scanners.theta_harvester import (
    DEFAULT_WEIGHTS,
    RADON_WEIGHTS,
    DealerSupport,
    OptionLeg,
    Strangle,
    ThetaCandidate,
    build_candidate,
    dealer_support,
    range_metrics,
    realized_vol,
    select_short_strangle,
)
from uw_scan.worker.jobs.theta_harvester import scan_ticker


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
# only ticker for which the gates genuinely pass on real data. The cheap-vol
# negative case uses a different real session (QQQ 2026-07-21), because no
# ticker on 2026-07-24 failed the IV gate.
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


def _structure(**over):
    """Build through select_short_strangle so the sign convention cannot drift.

    Hand-constructing Strangle(...) here is what let the original draft ship a
    short-convention fixture (theta=+0.08) against a long-convention selector:
    the tests passed and production produced zero THETA_HARVEST rows. Always
    derive from the frozen real legs via the selector, then override only the
    field a given test is actually exercising.
    """
    base = select_short_strangle([_PUT_16D, _CALL_16D], spot=_SPOT, as_of=_AS_OF)
    assert base is not None and base.theta > 0 and base.gamma < 0
    return dataclasses.replace(base, **over) if over else base


def _candidate(**over):
    """The real IWM 2026-07-24 candidate. Every gate passes on real data."""
    kwargs = dict(
        ticker="IWM",
        as_of=_AS_OF,
        structure=_structure(),
        spot=_SPOT,
        iv=_IV,
        hv20=_HV20,
        hv60=_HV60,
        trend_20d_pct=_TREND_21D,
        range_score=_RANGE_SCORE,
        # Real IWM net GEX on 2026-07-24 is positive with the flip below spot.
        dealer=DealerSupport("SUPPORT", 5.0e8, 280.0),
    )
    kwargs.update(over)
    return build_candidate(**kwargs)


def test_all_gates_passing_yields_theta_harvest_verdict():
    # Real IWM 2026-07-24 clears all six gates on real data.
    c = _candidate()
    assert isinstance(c, ThetaCandidate)
    assert all(c.gates.values())
    # 55 * (9.7212/15) + 25 * (1 - 0.0018275/0.10) + 20 * 0.534602
    assert c.score == pytest.approx(70.879602930724, rel=1e-9)
    # Deliberately marginal: IWM's edge is ~p85, not top-decile, so a
    # genuinely rich-but-not-extreme name clears the default bar by 0.88.
    # If a weight change moves this, the test SHOULD fail loudly.
    assert c.verdict == "THETA_HARVEST"


def test_directional_book_is_called_out_as_disguise():
    # |net delta| above 0.20 means this is a directional bet wearing a
    # strangle's clothes, regardless of how rich the vol is.
    c = _candidate(structure=_structure(net_delta=0.35))
    assert c.gates["delta_near_zero"] is False
    assert c.verdict == "DIRECTIONAL_DISGUISE"


def test_cheap_vol_is_a_disguise_not_a_watchlist_entry():
    # IV under RV: no edge to harvest. Radon routes this to DIRECTIONAL_DISGUISE
    # via the iv_gate branch even when delta is clean.
    #
    # REAL QQQ readings for session 2026-07-21, read from option_wizard on
    # 2026-07-29: iv_rank_history.volatility 0.241 against HV20 0.25568 — QQQ
    # genuinely failed this gate that day (edge -1.47 vol points, ratio 0.943),
    # so the negative case needs no invented numbers. A single real session is
    # used for all three readings; pairing one date's IV with another date's
    # realised vol would be a fixture that never existed.
    c = _candidate(iv=0.241, hv20=0.25567671527495894, hv60=0.2479297744543768)
    assert c.iv_rv_edge < 0
    assert c.gates["iv_rich_vs_rv"] is False
    assert c.verdict == "DIRECTIONAL_DISGUISE"


def test_dealer_support_is_recorded_but_not_critical_by_default():
    # DEFAULT_WEIGHTS.dealer_gate_critical is False, so short-gamma dealers
    # are RECORDED and still harvest-eligible. This is the deliberate change
    # that keeps 116 backtestable sessions instead of 24.
    c = _candidate(dealer=DealerSupport("NO_SUPPORT", -3.0e8, None))
    assert c.gates["dealer_support"] is False
    assert c.verdict == "THETA_HARVEST"


def test_dealer_gate_becomes_critical_under_radon_weights():
    c = _candidate(
        dealer=DealerSupport("NO_SUPPORT", -3.0e8, None), weights=RADON_WEIGHTS
    )
    assert c.gates["dealer_support"] is False
    assert c.verdict == "WATCHLIST"


def test_radon_weights_reproduce_the_original_score():
    # Radon's published number for this row is 94.19. Its formula carried a
    # constant +40 once the critical gates passed; ours drops it. The two
    # must therefore differ by exactly 40 -- if they don't, the reweight
    # changed something other than the constant, which is a bug.
    c = _candidate(weights=RADON_WEIGHTS)
    assert c.score == pytest.approx(54.192171263918, rel=1e-9)
    assert c.score + 40.0 == pytest.approx(94.192171263918, rel=1e-9)
    assert c.verdict == "THETA_HARVEST"  # 54.19 >= threshold 30


def test_weights_version_is_stamped_on_the_candidate():
    assert _candidate().weights_version == DEFAULT_WEIGHTS.version
    assert _candidate(weights=RADON_WEIGHTS).weights_version == RADON_WEIGHTS.version
    assert DEFAULT_WEIGHTS.version != RADON_WEIGHTS.version


def test_iv_edge_and_ratio_are_reported_in_vol_points():
    c = _candidate()
    # Real IWM: IV 0.208 vs HV20 0.11079 -> +9.72 vol points, ratio 1.877.
    assert c.iv_rv_edge == pytest.approx((_IV - _HV20) * 100.0)
    assert c.iv_rv_edge == pytest.approx(9.7212090846368, rel=1e-9)
    assert c.iv_rv_ratio == pytest.approx(_IV / _HV20)


def test_entry_credit_is_the_sum_of_both_black_scholes_leg_marks():
    c = _candidate()
    assert c.entry_credit_theo == pytest.approx(c.put_mark + c.call_mark)
    assert c.put_mark > 0 and c.call_mark > 0


def test_score_is_bounded_to_one_hundred():
    c = _candidate(iv=2.0, hv20=0.10, range_score=1.0)
    assert c.score <= 100.0


# The REAL IWM 90-close series ending 2026-07-24, read from
# uw_scan.daily_ohlc. This is what makes _HV20/_HV60/_TREND_21D/_RANGE_SCORE
# above reproducible: realized_vol(_CLOSES, 20) == _HV20 exactly.
_CLOSES = [
    250.05,
    246.02,
    247.63,
    242.22,
    247.45,
    248.78,
    251.82,
    247.44,
    243.1,
    239.61,
    248.0,
    249.56,
    251.29,
    252.36,
    252.91,
    260.47,
    261.96,
    261.3,
    265.07,
    268.72,
    269.39,
    269.95,
    275.78,
    277.35,
    274.51,
    276.48,
    275.52,
    276.65,
    277.14,
    273.91,
    272.08,
    277.97,
    279.28,
    277.88,
    282.56,
    286.8,
    282.26,
    284.17,
    285.33,
    282.57,
    282.67,
    284.45,
    277.6,
    275.97,
    273.0,
    279.87,
    282.49,
    285.12,
    290.51,
    290.37,
    292.03,
    290.43,
    288.98,
    291.66,
    287.67,
    292.01,
    281.65,
    284.11,
    285.02,
    282.05,
    290.41,
    292.95,
    294.64,
    292.08,
    289.88,
    295.59,
    298.18,
    295.32,
    296.69,
    298.91,
    299.83,
    298.97,
    300.45,
    299.32,
    297.58,
    298.9,
    296.19,
    293.48,
    297.24,
    295.99,
    293.48,
    294.51,
    295.77,
    295.59,
    294.04,
    292.31,
    296.54,
    293.79,
    292.09,
    291.17,
]


def test_frozen_closes_reproduce_the_frozen_vol_fixtures():
    # Pins the provenance chain: if this fails, the _HV20/_RANGE_SCORE
    # constants above no longer describe the price series they came from.
    assert realized_vol(_CLOSES, 20) == pytest.approx(_HV20, rel=1e-12)
    assert realized_vol(_CLOSES, 60) == pytest.approx(_HV60, rel=1e-12)
    trend, score = range_metrics(_CLOSES, _HV20)
    assert trend == pytest.approx(_TREND_21D, rel=1e-12)
    assert score == pytest.approx(_RANGE_SCORE, rel=1e-12)


class _StubRepo:
    """In-memory stand-in for ThetaHarvesterRepository — the frozen real IWM
    2026-07-24 capture. No network, no DB, and no invented prices: the closes,
    chain legs, spot and IV are all the real readings for that session.
    """

    def __init__(self, *, closes=None, chain=None, gex=None, iv=_IV, spot=_SPOT):
        self._closes = _CLOSES if closes is None else closes
        # LONG-convention legs, as load_chain returns them. theta must be <= 0
        # here — the selector negates.
        self._chain = [_PUT_16D, _CALL_16D] if chain is None else chain
        self._gex = (
            [
                {"strike": 272.0, "call_gex": 4.0e8, "put_gex": -1.0e8},
                {"strike": 306.0, "call_gex": 3.0e8, "put_gex": -1.0e8},
            ]
            if gex is None
            else gex
        )
        self._iv, self._spot = iv, spot

    def load_closes(self, ticker, as_of, lookback=90):
        return self._closes

    def load_chain(self, ticker, as_of):
        return self._chain

    def load_gex_rows(self, ticker, as_of):
        return self._gex

    def load_atm_iv(self, ticker, as_of, expiry, spot):
        # spot is asserted, not ignored: passing it is what keeps the IV, the
        # legs and the moneyness on one number after the NULL-underlying_spot fix.
        assert spot == self._spot
        return self._iv

    def load_spot(self, ticker, as_of):
        return self._spot


def test_scan_ticker_produces_a_candidate_from_warm_store_rows():
    out = scan_ticker(_StubRepo(), "IWM", _AS_OF)
    assert out is not None
    assert out.ticker == "IWM"
    assert out.structure.put.strike == 272.0
    # End-to-end on real data: the scan reproduces the Task 4 score exactly.
    assert out.score == pytest.approx(70.879602930724, rel=1e-9)
    assert out.verdict == "THETA_HARVEST"


def test_scan_ticker_returns_none_without_enough_price_history():
    # HV20 needs 21 closes; 10 is not enough and a partial window would
    # understate vol and loosen the IV-edge gate.
    assert scan_ticker(_StubRepo(closes=_CLOSES[:10]), "IWM", _AS_OF) is None


def test_scan_ticker_returns_none_when_the_chain_is_empty():
    assert scan_ticker(_StubRepo(chain=[]), "IWM", _AS_OF) is None


def test_scan_ticker_returns_none_without_an_iv_reading():
    assert scan_ticker(_StubRepo(iv=None), "IWM", _AS_OF) is None


def test_scan_ticker_still_scores_when_gex_is_missing():
    # No dealer data must not kill the row — it fails one gate and lands on
    # the watchlist, which is information, unlike a dropped ticker.
    out = scan_ticker(_StubRepo(gex=[]), "IWM", _AS_OF)
    assert out is not None
    assert out.dealer.label == "UNKNOWN"
    assert out.gates["dealer_support"] is False
