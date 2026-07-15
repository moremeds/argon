from __future__ import annotations

from datetime import date, datetime, timedelta

from uw_scan.chanlun.lifecycle import (
    Mark,
    anchor_window,
    breached,
    crosses_split_boundary,
    evaluate_mark,
    find_split_boundaries,
    is_promotable,
    is_stale,
    mark_side,
    promotable_key,
    s1_confirmed,
    session_et_date,
)
from uw_scan.chanlun.types import BiVertex, ChanlunBar


def _M(**k):
    return Mark(
        **{
            "category": "vertex",
            "kind": "bottom",
            "extreme_date": date(2026, 7, 1),
            "extreme_price": 100.0,
            "is_native_confirmed": False,
            **k,
        }
    )


def test_edge_native_confirmed_terminal():
    assert evaluate_mark(
        mark=_M(is_native_confirmed=True),
        split_crossed=False,
        breach=False,
        s1_ok=False,
        promotable=True,
        stale=False,
    ) == ("confirmed_native", None)


def test_edge_split_boundary_wins_over_everything():
    assert evaluate_mark(
        mark=_M(is_native_confirmed=True),
        split_crossed=True,
        breach=True,
        s1_ok=True,
        promotable=True,
        stale=True,
    ) == ("invalidated", "split_boundary")


def test_edge_breach_demotes():
    assert evaluate_mark(
        mark=_M(),
        split_crossed=False,
        breach=True,
        s1_ok=True,
        promotable=True,
        stale=False,
    ) == ("invalidated", "breach")


def test_edge_stale_invalidates():
    assert evaluate_mark(
        mark=_M(),
        split_crossed=False,
        breach=False,
        s1_ok=False,
        promotable=True,
        stale=True,
    ) == ("invalidated", "stale")


def test_edge_promotable_s1_ok_to_sublevel():
    assert evaluate_mark(
        mark=_M(),
        split_crossed=False,
        breach=False,
        s1_ok=True,
        promotable=True,
        stale=False,
    ) == ("confirmed_sublevel", None)


def test_edge_non_promotable_stays_pending_even_with_s1():
    assert evaluate_mark(
        mark=_M(category="point", kind="2B"),
        split_crossed=False,
        breach=False,
        s1_ok=True,
        promotable=False,
        stale=False,
    ) == ("pending", None)


def test_promotable_key_and_applicability():
    assert promotable_key("vertex", "bottom") == "vertex"
    assert promotable_key("divergence", "top") == "divergence"
    assert promotable_key("point", "3B") == "3B"
    assert mark_side("bottom") == "bottom" and mark_side("top") == "top"
    assert mark_side("1B") == "bottom" and mark_side("3B") == "bottom"
    assert mark_side("2S") == "top" and mark_side("3S") == "top"
    p = frozenset({"vertex", "divergence", "3B", "3S"})
    assert is_promotable("point", "3B", p) is True
    assert is_promotable("point", "1B", p) is False  # 1B never sublevel (spec §E)
    assert is_promotable("point", "2S", p) is False  # 2S never sublevel


def test_find_split_boundaries_flags_a_2x_gap_on_real_apex_timestamps():
    # Raw apex `time` is a FULL UTC datetime string (apex contract §2a). An
    # implementation calling date.fromisoformat on the unsliced string raises
    # ValueError — this test feeds real-shaped timestamps to force the [:10] slice.
    bars = [
        {
            "open": 100.0,
            "high": 101,
            "low": 99,
            "close": 100.0,
            "time": "2026-06-30T00:00:00+00:00",
        },
        {
            "open": 50.0,
            "high": 51,
            "low": 49,
            "close": 50.0,
            "time": "2026-07-01T00:00:00+00:00",
        },  # 2:1 split gap
        {
            "open": 50.5,
            "high": 51,
            "low": 50,
            "close": 50.5,
            "time": "2026-07-02T00:00:00+00:00",
        },
    ]
    b = find_split_boundaries(bars)
    assert date(2026, 7, 1) in b  # |ln(50/100)| = 0.69 > ln(1.5)=0.405
    assert date(2026, 7, 2) not in b
    assert (
        crosses_split_boundary(_M(extreme_date=date(2026, 6, 30)), date(2026, 6, 30), b)
        is True
    )


def test_find_split_boundaries_accepts_date_only_strings():
    # The Task 9 integration stub and the golden bars carry bare 'yyyy-mm-dd'
    # times — the [:10] slice must be a no-op for them, not a crash.
    bars = [
        {"open": 100.0, "high": 101, "low": 99, "close": 100.0, "time": "2026-06-30"},
        {"open": 50.0, "high": 51, "low": 49, "close": 50.0, "time": "2026-07-01"},
    ]
    assert find_split_boundaries(bars) == {date(2026, 7, 1)}


def test_breached_bottom_and_top():
    later = [{"low": 95.0, "high": 105.0, "time": "2026-07-02"}]
    assert (
        breached(_M(kind="bottom", extreme_price=100.0), later) is True
    )  # low 95 < 100
    assert (
        breached(_M(kind="top", extreme_price=100.0), later) is True
    )  # high 105 > 100
    assert breached(_M(kind="bottom", extreme_price=90.0), later) is False


def test_is_stale_counts_sessions_after_extreme():
    sessions = [date(2026, 7, d) for d in range(1, 26)]  # 25 sessions
    assert (
        is_stale(_M(extreme_date=date(2026, 7, 1)), date(2026, 7, 25), 20, sessions)
        is True
    )
    assert (
        is_stale(_M(extreme_date=date(2026, 7, 10)), date(2026, 7, 25), 20, sessions)
        is False
    )


def _bars_30m(
    prices: list[tuple[float, float, float]], start_utc: str
) -> list[ChanlunBar]:
    """Abstract 30m bars (labeled test double) at 30-minute spacing from
    `start_utc`; each tuple is (high, low, close). Keyword-arg construction —
    ChanlunBar has exactly time/high/low/close (port contract §A, no open)."""
    t0 = datetime.fromisoformat(start_utc)
    return [
        ChanlunBar(
            time=(t0 + timedelta(minutes=30 * i)).isoformat(),
            high=h,
            low=lo,
            close=c,
        )
        for i, (h, lo, c) in enumerate(prices)
    ]


# V-shape with a strict fractal bottom at 100.0 (index 5) AND a later top
# fractal (index 10, peak 128) whose merged-candle gap (10-5=5 >= MIN_VERTEX_GAP)
# and strict price acceptance make the bottom endpoint CONFIRMED (buildEndpoints
# yields [bottom@5, top@10] -> confirmedCount=1 -> bottom confirmed=True). No
# two adjacent bars are mutually inclusive, so merged idx == raw idx throughout.
_V_LADDER: list[tuple[float, float, float]] = [
    (120, 118, 119),
    (118, 115, 116),
    (116, 112, 113),
    (112, 108, 109),
    (108, 104, 105),
    (104, 100, 100),  # index 5 — the low, 100.0
    (105, 101, 104),
    (110, 106, 109),
    (115, 111, 114),
    (120, 116, 119),
    (128, 124, 127),  # index 10 — the peak (top fractal)
    (126, 122, 123),
    (124, 120, 121),
    (122, 118, 119),
]


def test_s1_confirmed_matches_a_30m_bottom_at_the_daily_low():
    # Regular-hours case: low bar at 16:30 UTC (12:30 ET), same date both ways.
    bars_30m = _bars_30m(_V_LADDER, "2026-07-01T14:00:00+00:00")
    mark = _M(kind="bottom", extreme_date=date(2026, 7, 1), extreme_price=100.0)
    ok, info = s1_confirmed(mark, bars_30m, tol=0.0)
    assert ok is True and info  # non-vacuity: info carries v30 anchor
    # Perturb the mark price so nothing reconciles -> no S1.
    ok2, _ = s1_confirmed(_M(kind="bottom", extreme_price=999.0), bars_30m, tol=0.0)
    assert ok2 is False


def test_s1_session_match_uses_et_date_not_utc_date():
    # UTC-rollover regression: starting at 21:30Z puts the low bar (index 5)
    # at 2026-07-02T00:00:00Z == 2026-07-01 20:00 ET. A naive UTC-date
    # comparison (ts[:10]) sees July 2 != extreme_date July 1 and would
    # silently false-negate; the ET-date match must still confirm.
    bars_30m = _bars_30m(_V_LADDER, "2026-07-01T21:30:00+00:00")
    mark = _M(kind="bottom", extreme_date=date(2026, 7, 1), extreme_price=100.0)
    ok, info = s1_confirmed(mark, bars_30m, tol=0.0)
    assert ok is True and info


def test_s1_condition4_later_undercut_kills_the_match():
    # Conjunct 4 regression: append one tail bar that dips BELOW the anchored
    # low (99.5 < 100.0). The bottom vertex at 100.0 stays confirmed (the tail
    # bar forms no new fractal), but a later 30m bar now beats v30 on its side
    # -> S1 must refuse. The monotone-rising _V_LADDER alone can never exercise
    # this clause, which is exactly why this test exists.
    ladder = list(_V_LADDER) + [(104, 99.5, 100.5)]
    bars_30m = _bars_30m(ladder, "2026-07-01T14:00:00+00:00")
    mark = _M(kind="bottom", extreme_date=date(2026, 7, 1), extreme_price=100.0)
    ok, info = s1_confirmed(mark, bars_30m, tol=0.0)
    assert ok is False and info == {}


def test_session_et_date_rolls_utc_midnight_back_to_the_et_session():
    # 00:00 UTC July 2 == 20:00 ET July 1 (EDT) -> ET session date July 1.
    assert session_et_date("2026-07-02T00:00:00+00:00") == date(2026, 7, 1)
    # A mid-session timestamp stays on its own date.
    assert session_et_date("2026-07-01T14:00:00+00:00") == date(2026, 7, 1)
    # A bare daily date string passes through unchanged.
    assert session_et_date("2026-07-01") == date(2026, 7, 1)


def test_anchor_window_primary_path_uses_previous_opposite_confirmed_vertex():
    # W starts at the LATEST confirmed OPPOSITE-side vertex strictly before the
    # extreme. The unconfirmed top at [46] must be skipped; the confirmed top
    # at [42] wins.
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    verts = [
        BiVertex(
            time=sessions[42].isoformat(), price=110.0, kind="top", confirmed=True
        ),
        BiVertex(
            time=sessions[46].isoformat(), price=104.0, kind="top", confirmed=False
        ),
        BiVertex(
            time=sessions[50].isoformat(), price=100.0, kind="bottom", confirmed=False
        ),
    ]
    mark = _M(kind="bottom", extreme_date=sessions[50])
    assert anchor_window(mark, verts, sessions) == sessions[42]


def test_anchor_window_fallback_counts_40_sessions_not_calendar_days():
    # 60 consecutive dates as the session list (labeled test double). With no
    # opposite confirmed vertex, the fallback must step back exactly 40 SESSIONS.
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    mark = _M(extreme_date=sessions[50])
    assert anchor_window(mark, [], sessions) == sessions[10]  # 50 - 40 = 10
    early = _M(extreme_date=sessions[5])
    assert anchor_window(early, [], sessions) == sessions[0]  # clamps at start
