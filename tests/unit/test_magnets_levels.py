import pytest

from tests.fixtures.aapl_daily import aapl_frame
from uw_scan.cards.magnets import magnet_levels

# all_pivots(aapl_frame(), k=3.0) confirms three pivots; the last two are
# bottom 275.15 (2026-06-25) and top 340.08 (2026-07-28). Verified against the
# mini 2026-08-09.
_R, _S = 340.08, 275.15


def test_magnet_levels_picks_the_last_two_confirmed_pivots():
    lv = magnet_levels(aapl_frame(), k=3.0)
    assert lv["resistance"] == pytest.approx(_R)
    assert lv["support"] == pytest.approx(_S)


def test_magnet_levels_reproduces_the_0618_arithmetic():
    lv = magnet_levels(aapl_frame(), k=3.0)
    assert lv["stretch"] == pytest.approx(_R + 0.618 * (_R - _S))
    assert lv["down"] == pytest.approx(_S - 0.618 * (_R - _S))


def test_magnet_levels_marks_falling_when_the_top_is_the_later_pivot():
    # The later pivot is the 340.08 top and price has come off it, so the leg
    # is working DOWN from resistance.
    assert magnet_levels(aapl_frame(), k=3.0)["leg_state"] == "falling"


def test_magnet_levels_returns_none_when_no_pivot_confirms():
    # k=50 puts the reversal threshold at 50x ATR(14) — nothing confirms.
    assert magnet_levels(aapl_frame(), k=50.0) is None


def test_magnet_levels_returns_none_on_a_frame_below_the_pivot_floor():
    # all_pivots requires >= 30 bars; 20 must yield None, not a fabricated swing.
    assert magnet_levels(aapl_frame().head(20), k=3.0) is None


def test_magnet_levels_reports_sma20_and_last():
    df = aapl_frame()
    lv = magnet_levels(df, k=3.0)
    assert lv["last"] == pytest.approx(313.33)
    assert lv["sma20"] == pytest.approx(float(df["close"].tail(20).mean()))
