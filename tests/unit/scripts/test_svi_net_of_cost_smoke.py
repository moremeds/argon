"""Smoke checks for the SVI residual net-of-cost probe's money path.

This probe exists because a published verdict multiplied a PER-SHARE vega by a
vol-point edge and compared the result to a PER-CONTRACT commission — a 100x unit
error that closed a research question. These tests pin the two things that would
let that class of bug back in: the contract multiplier actually being applied, and
the long/short P&L signs.

Pure — no DB, no network.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.research.svi_residual_net_of_cost import (
    COMMISSION_PER_CONTRACT_PER_SIDE,
    CONTRACT_MULTIPLIER,
    Leg,
    black76,
    build_trade,
    net_dollars,
    net_return,
)


def _smile(fwd: float, t: float, legs: dict[float, tuple[float, float, bool]]) -> dict:
    return {
        "fwd": fwd,
        "t": t,
        "legs": {
            k: Leg(k, iv, vega, is_call) for k, (iv, vega, is_call) in legs.items()
        },
        "resid": {},
    }


def test_black76_put_call_parity():
    c = black76(100.0, 90.0, 1.0, 0.2, True)
    p = black76(100.0, 90.0, 1.0, 0.2, False)
    assert c - p == pytest.approx(100.0 - 90.0, abs=1e-8)


def test_black76_atm_call_equals_put():
    c = black76(100.0, 100.0, 1.0, 0.2, True)
    p = black76(100.0, 100.0, 1.0, 0.2, False)
    assert c == pytest.approx(p, abs=1e-9)
    # ATM Black ~ F * 0.3989 * sigma * sqrt(T)
    assert c == pytest.approx(100.0 * 0.3989 * 0.2, rel=0.01)


def test_black76_call_decreasing_in_strike():
    near = black76(100.0, 105.0, 0.08, 0.2, True)
    far = black76(100.0, 150.0, 0.08, 0.2, True)
    assert far < near


def test_contract_multiplier_is_one_hundred():
    """The constant itself. A silent change here re-opens the original bug."""
    assert CONTRACT_MULTIPLIER == 100


def test_slippage_scales_with_contract_multiplier():
    """Spread cost must be per-CONTRACT dollars, not per-share dollars.

    vega is per share per vol point, so a 0.06 vp spread across two legs of
    0.83 + 0.50 vega is 0.06 * 1.33 * 100 = $7.98 per spread — not $0.0798.
    """
    t = _trade(gross_pnl=100.0, vega_short=0.83, vega_hedge=0.50, max_loss=500.0)
    slip_dollars = net_dollars(t, 0.0) - net_dollars(t, 0.06)
    assert slip_dollars == pytest.approx(0.06 * 1.33 * CONTRACT_MULTIPLIER, rel=1e-9)
    assert slip_dollars == pytest.approx(7.98, rel=1e-6)


def test_commission_is_four_sides():
    """Two legs, entry and exit: four per-contract charges."""
    t = _trade(gross_pnl=0.0, vega_short=0.0, vega_hedge=0.0, max_loss=1000.0)
    assert net_dollars(t, 0.0) == pytest.approx(-4.0 * COMMISSION_PER_CONTRACT_PER_SIDE)


def test_return_denominator_is_width_not_max_loss():
    """Regression: normalizing by max_loss let a cents-sized debit spread post a
    four-figure percentage return, which dominated every monthly mean and inverted
    Sharpe against the actual dollar P&L. Capital must be width x multiplier."""
    t = _trade(gross_pnl=10.0, vega_short=0.0, vega_hedge=0.0, max_loss=0.50)
    # width is 5.0 -> capital 500, so a ~$7.40 net is ~1.5%, NOT ~1480%
    assert net_return(t, 0.0) == pytest.approx(
        net_dollars(t, 0.0) / (t.width * CONTRACT_MULTIPLIER)
    )
    assert abs(net_return(t, 0.0)) < 0.10


def test_return_and_dollars_always_agree_in_sign():
    """The bug's signature was mean-dollars and Sharpe disagreeing in sign. With a
    strictly positive capital base that is impossible trade-by-trade."""
    for gross in (-50.0, -1.0, 0.0, 1.0, 50.0):
        t = _trade(gross_pnl=gross, vega_short=0.8, vega_hedge=0.5, max_loss=123.0)
        d, r = net_dollars(t, 0.05), net_return(t, 0.05)
        assert (d > 0) == (r > 0)
        assert (d < 0) == (r < 0)


def _trade(*, gross_pnl, vega_short, vega_hedge, max_loss):
    from scripts.research.svi_residual_net_of_cost import Trade

    return Trade(
        ticker="SPY",
        expiry=date(2026, 8, 21),
        signal_date=date(2026, 8, 3),
        entry_date=date(2026, 8, 4),
        exit_date=date(2026, 8, 5),
        horizon=1,
        threshold=1.0,
        variant="naive",
        short_strike=105.0,
        hedge_strike=110.0,
        width=5.0,
        signal_resid_vp=1.5,
        hedge_resid_vp=0.0,
        is_credit=True,
        gross_pnl=gross_pnl,
        ivonly_pnl=gross_pnl,
        max_loss=max_loss,
        vega_short=vega_short,
        vega_hedge=vega_hedge,
    )


def test_selling_a_rich_call_profits_when_its_iv_converges():
    """Short the rich strike, long a further-OTM hedge. Rich leg's IV falls to the
    hedge's; forward unchanged. That must be a gain, and (forward unchanged) the
    IV-only P&L must equal the total."""
    ent = _smile(100.0, 0.08, {105.0: (0.30, 0.8, True), 110.0: (0.25, 0.5, True)})
    ex = _smile(100.0, 0.08, {105.0: (0.25, 0.8, True), 110.0: (0.25, 0.5, True)})
    t = build_trade(
        "SPY",
        date(2026, 8, 21),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        1,
        1.0,
        "naive",
        105.0,
        110.0,
        +1.5,
        0.0,
        True,
        True,
        ent,
        ex,
    )
    assert t is not None
    assert t.gross_pnl > 0
    assert t.ivonly_pnl == pytest.approx(t.gross_pnl, rel=1e-9)
    assert t.is_credit is True


def test_buying_a_cheap_call_profits_when_its_iv_converges_up():
    """Mirror direction: cheap strike bought, IV rises to fair. Must also gain."""
    ent = _smile(100.0, 0.08, {105.0: (0.20, 0.8, True), 110.0: (0.25, 0.5, True)})
    ex = _smile(100.0, 0.08, {105.0: (0.25, 0.8, True), 110.0: (0.25, 0.5, True)})
    t = build_trade(
        "SPY",
        date(2026, 8, 21),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        1,
        1.0,
        "naive",
        105.0,
        110.0,
        -1.5,
        0.0,
        False,
        True,
        ent,
        ex,
    )
    assert t is not None
    assert t.gross_pnl > 0
    assert t.is_credit is False  # bought the near strike -> debit


def test_max_loss_is_positive_and_bounded_by_width():
    ent = _smile(100.0, 0.08, {105.0: (0.30, 0.8, True), 110.0: (0.25, 0.5, True)})
    ex = _smile(100.0, 0.08, {105.0: (0.25, 0.8, True), 110.0: (0.25, 0.5, True)})
    t = build_trade(
        "SPY",
        date(2026, 8, 21),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        1,
        1.0,
        "naive",
        105.0,
        110.0,
        +1.5,
        0.0,
        True,
        True,
        ent,
        ex,
    )
    assert t is not None
    assert 0 < t.max_loss <= abs(105.0 - 110.0) * CONTRACT_MULTIPLIER
