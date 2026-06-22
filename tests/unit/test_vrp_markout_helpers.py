from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports import vrp_markout as vm

_BASE = date(2026, 1, 5)  # Monday; calendar-day spacing is fine for unit logic


def _panel(n, *, iv=0.30, rv=0.20, z=1.2):
    """n consecutive daily vrp_daily-shaped rows (one row per trading day)."""
    return [
        {"market_date": _BASE + timedelta(days=i), "iv": iv, "rv": rv, "vrp_z_20": z}
        for i in range(n)
    ]


def test_deviation_class_thresholds():
    assert vm._deviation_class(1.0) == "RICH"
    assert vm._deviation_class(1.5) == "RICH"
    assert vm._deviation_class(-1.0) == "CHEAP"
    assert vm._deviation_class(-1.5) == "CHEAP"
    assert vm._deviation_class(0.0) == "NORMAL"
    assert vm._deviation_class(0.99) == "NORMAL"
    assert vm._deviation_class(None) is None


def test_earnings_in_window_is_left_open_right_closed():
    earn = {date(2026, 1, 15)}
    # window (t, end]; t itself excluded, end included
    assert vm._earnings_in_window(date(2026, 1, 1), date(2026, 1, 20), earn) is True
    assert (
        vm._earnings_in_window(date(2026, 1, 15), date(2026, 1, 20), earn) is False
    )  # t == earn, open lower bound
    assert (
        vm._earnings_in_window(date(2026, 1, 1), date(2026, 1, 15), earn) is True
    )  # end == earn, closed upper
    assert vm._earnings_in_window(date(2026, 1, 16), date(2026, 1, 30), earn) is False
    assert vm._earnings_in_window(date(2026, 1, 1), date(2026, 1, 20), set()) is False


def test_harvest_obs_computes_iv_minus_forward_rv():
    # 25 daily rows; constant iv=0.30, rv=0.20 → realized_vrp = 0.10.
    obs = vm._harvest_obs(_panel(25), earnings=set())
    # anchors i with i+HORIZON(20) < 25 → i in 0..4 → 5 obs.
    assert len(obs) == 5
    assert all(o["deviation_class"] == "RICH" for o in obs)
    assert all(abs(o["realized_vrp"] - 0.10) < 1e-9 for o in obs)
    assert obs[0]["market_date"] == _BASE


def test_harvest_obs_reads_exact_t20_row_not_skipping_nulls():
    # ISSUE-1 regression: the forward read must be the EXACT 20th trading-day
    # row by position, NOT the 20th non-null-RV row. Null RV at index 20 means
    # anchor 0 (whose exact t+20 IS index 20) must be DROPPED — a skip-nulls
    # impl would instead grab index 21 and wrongly keep anchor 0.
    rows = _panel(30)
    rows[20]["rv"] = None
    obs = vm._harvest_obs(rows, earnings=set())
    dates = {o["market_date"] for o in obs}
    assert _BASE not in dates  # anchor 0 dropped (exact t+20 null)
    assert (_BASE + timedelta(days=1)) in dates  # anchor 1 (t+20=index 21) kept
    assert len(obs) == 9  # scorable 0..9, minus anchor 0


def test_harvest_obs_drops_null_signal_and_iv_in_scorable_region():
    # ISSUE-8: nulls placed in the SCORABLE region (not the unscorable tail) so
    # the test fails if the guards are removed. Compare against a clean control.
    control = vm._harvest_obs(_panel(30), earnings=set())
    assert len(control) == 10  # anchors 0..9
    rows = _panel(30)
    rows[2]["iv"] = None
    rows[5]["vrp_z_20"] = None
    obs = vm._harvest_obs(rows, earnings=set())
    dates = {o["market_date"] for o in obs}
    assert len(obs) == 8  # 10 control - 2 nulled anchors
    assert (_BASE + timedelta(days=2)) not in dates
    assert (_BASE + timedelta(days=5)) not in dates


def test_harvest_obs_count_at_min_n_boundary():
    # ISSUE-9: pin the off-by-one. 40 rows → 20 scorable obs (== MIN_N);
    # 39 rows → 19 (< MIN_N).
    assert len(vm._harvest_obs(_panel(40), earnings=set())) == 20
    assert len(vm._harvest_obs(_panel(39), earnings=set())) == 19


def test_harvest_obs_excludes_earnings_spanning_windows():
    # earnings at index 10; for anchor i the window is (t_i, t_{i+20}]. All
    # scorable anchors (i in 0..4 for a 25-row panel) span index 10 → all dropped.
    obs = vm._harvest_obs(_panel(25), earnings={_BASE + timedelta(days=10)})
    assert obs == []
