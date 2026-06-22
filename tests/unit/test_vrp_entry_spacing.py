from datetime import date

from uw_scan.reports.vrp_backtest import (
    TradeResult,
    flag_holdout,
    select_non_overlapping,
)


def _t(entry: date, expiry: date) -> TradeResult:
    """Minimal real-shaped TradeResult (ASML-like) for spacing tests."""
    return TradeResult(
        ticker="ASML",
        entry_date=entry,
        expiry_date=expiry,
        spot_entry=900.0,
        spot_exit=905.0,
        iv_entry=0.35,
        entry_credit=2.0,
        max_loss=4.0,
        gross_pnl=200.0,
        net_pnl=150.0,
        return_on_risk=0.3,
        breached=False,
        in_holdout=False,
    )


def test_entry_spacing_drops_overlapping_same_name_trades():
    # Five candidate entries; each holds ~4 weeks. A new entry is taken only when
    # the prior position has already expired (trade-only-when-flat).
    trades = [
        _t(date(2024, 1, 2), date(2024, 1, 30)),  # kept (first, opens flat)
        _t(date(2024, 1, 10), date(2024, 2, 7)),  # dropped (opens before 1/30)
        _t(date(2024, 1, 31), date(2024, 2, 28)),  # kept (opens after 1/30)
        _t(date(2024, 2, 15), date(2024, 3, 14)),  # dropped (opens before 2/28)
        _t(date(2024, 3, 1), date(2024, 3, 29)),  # kept (opens after 2/28)
    ]
    kept = select_non_overlapping(trades)
    assert [t.entry_date for t in kept] == [
        date(2024, 1, 2),
        date(2024, 1, 31),
        date(2024, 3, 1),
    ]


def test_entry_spacing_is_order_independent():
    a = _t(date(2024, 1, 2), date(2024, 1, 30))
    b = _t(date(2024, 1, 31), date(2024, 2, 28))
    assert [t.entry_date for t in select_non_overlapping([b, a])] == [
        a.entry_date,
        b.entry_date,
    ]


def test_holdout_recomputed_on_survivors():
    # Three non-overlapping trades survive spacing; latest HOLDOUT_FRAC (0.40) →
    # cut = round(3 * 0.6) = 2, so only the last trade is in the holdout.
    trades = [
        _t(date(2024, 1, 2), date(2024, 1, 30)),
        _t(date(2024, 1, 31), date(2024, 2, 28)),
        _t(date(2024, 3, 1), date(2024, 3, 29)),
    ]
    kept = select_non_overlapping(trades)
    assert [t.in_holdout for t in kept] == [False, False, True]


def test_flag_holdout_does_not_mutate_input():
    trades = [_t(date(2024, 1, 2), date(2024, 1, 30))]
    flag_holdout(trades)
    assert trades[0].in_holdout is False  # original frozen dataclass untouched
