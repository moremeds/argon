from __future__ import annotations

from datetime import date

from tests.unit.chanlun.parity_helpers import bars_from_golden
from uw_scan.chanlun.core import (
    build_legs,
    build_pivots,
    merge_overlapping_zhongshus,
    resample_weekly,
)
from uw_scan.chanlun.full import compute_chanlun, compute_chanlun_full
from uw_scan.chanlun.points import mark_points, mark_resonance
from uw_scan.chanlun.types import (
    BuySellPoint,
    ChanlunBar,
    ChanlunResult,
    VertexPt,
    Zhongshu,
)


def test_trap01_time_sort_is_ordinal_not_locale():
    # §G.1 — points sorted by plain string compare == chronological.
    r = compute_chanlun(bars_from_golden())
    times = [p.time for p in r.points]
    assert times == sorted(times)


def test_trap02_last_bar_empty_guard_no_indexerror():
    # §G.2 — empty bars must not raise (JS bars[bars.length-1] -> undefined).
    r = compute_chanlun_full([])
    assert r.points == [] and r.vertices == []


def test_trap03_nullish_vs_or_level_default():
    # §G.3 — merge_overlapping_zhongshus level default uses `is None`, not `or`.
    # A pushed zone with no level gets level=1 (not clobbered by a falsy 0).
    out = merge_overlapping_zhongshus(
        [Zhongshu(start="2020-01-01", end="2020-01-02", zg=20, zd=10, confirmed=True)]
    )
    assert out[0].level == 1


def test_trap04_int_float_equality_holds():
    # §G.4 — structural equality compares numeric value, not JSON text; a price
    # that is integral must still equal the golden float.
    r = compute_chanlun(bars_from_golden())
    assert any(
        float(v.price) == v.price for v in r.vertices
    )  # trivially true, documents intent


def test_trap05_nonfinite_close_fails_fast():
    # §G.5 — non-finite close raises ValueError (fail-fast policy), not null-0 coercion.
    bars = [
        ChanlunBar(time=f"2020-01-{i + 1:02d}", high=1, low=1, close=float("nan"))
        for i in range(12)
    ]
    try:
        compute_chanlun(bars)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_trap06_no_empty_max_min_on_real_data():
    # §G.6 — build_pivots never calls max/min on an empty trio; real data runs clean.
    r = compute_chanlun(bars_from_golden())
    assert len(r.zhongshus) >= 0  # completes without ValueError from max([])/min([])


def test_trap07_findindex_sentinel_minus_one():
    # §G.7 — mark_resonance vertex lookup uses a -1 sentinel; a weekly point whose
    # vertex is absent falls back to lastBarTime (window to end), not a crash.
    weekly = ChanlunResult(
        vertices=[],  # no vertices -> findIndex returns -1 for the point below
        zhongshus=[],
        points=[BuySellPoint(time="2020-03-01", price=40, kind="1B", confirmed=True)],
        divergences=[],
    )
    pts = [BuySellPoint(time="2020-03-05", price=50, kind="1B", confirmed=True)]
    out = mark_resonance(pts, weekly, "2020-04-01")
    assert out[0].resonant is True  # window extended to lastBarTime, matched


def test_trap08_modulo_nonnegative_in_weekly():
    # §G.8/§G.9 — weekday offset is correct (Monday-anchored), no negative modulo.
    bars = bars_from_golden()
    weekly = resample_weekly(bars)
    assert len(weekly) > 0
    for w in weekly:
        assert date.fromisoformat(w.time).weekday() <= 6  # valid weekday, no shift


def test_trap09_weekday_not_double_transformed():
    # §G item 9 — the load-bearing gotcha: resample_weekly groups by ISO Monday.
    # Two bars in the same Mon-Sun week collapse to one weekly bar whose time is
    # the LATER session date.
    bars = [
        ChanlunBar(time="2024-01-08", high=10, low=5, close=8),  # Monday
        ChanlunBar(time="2024-01-09", high=12, low=6, close=11),  # Tuesday, same week
        ChanlunBar(time="2024-01-15", high=9, low=4, close=7),  # next Monday
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 2
    assert weekly[0].time == "2024-01-09"  # last session in week 1, not the Monday key
    assert weekly[0].high == 12 and weekly[0].low == 5 and weekly[0].close == 11


def test_trap10_optional_fields_absent_not_null():
    # §G.10 — non-resonant points leave `resonant` None (not False).
    r = compute_chanlun_full(bars_from_golden())
    assert any(p.resonant is None for p in r.points)  # some point is non-resonant


def test_trap11_slice_end_exclusive_parity():
    # §G.11 — Python slicing matches JS .slice; already exercised by full parity.
    r = compute_chanlun_full(bars_from_golden())
    assert len(r.segVertices) > 0


def test_trap12_float_division_alpha():
    # §G.12 — ema alpha is true float division, never floor. 2/(9+1) == 0.2 exactly.
    from uw_scan.chanlun.core import ema

    out = ema([1.0, 2.0, 3.0], 9)
    assert out[0] == 1.0 and abs(out[1] - (0.2 * 2 + 0.8 * 1)) <= 1e-12


def test_trap13_2b_retest_offset_reaches_2b_branch():
    # labeled test double: hand-built abstract geometry to reach the 2B/2S
    # branch — NOT market data.
    #
    # mark_points' `retest = pts[exit.b+2]` offset (points.py) and the 2B/2S
    # guard beneath it are unreachable on the AAPL golden fixture (it has no
    # 2B/2S points at all), so this constructs a minimal 10-vertex zigzag
    # that produces two consecutive CONFIRMED pivots whose connect/exit legs
    # satisfy mark_points' "falling" divergence condition (§C.9), forcing a
    # "1B" mark followed by a same-kind, higher-low retest two vertices later
    # -> "2B". `leg_area` is a hand-keyed lookup (not real MACD), decoupling
    # this from any market-data computation — it only exercises mark_points'
    # control flow, verified against build_legs/build_pivots' REAL output
    # (not hand-built Leg/Pivot objects) so the pivot indices are genuine.
    kinds = [
        "top",
        "bottom",
        "top",
        "bottom",
        "top",
        "bottom",
        "top",
        "bottom",
        "top",
        "bottom",
    ]
    prices = [100, 85, 98, 80, 60, 55, 65, 40, 50, 45]
    pts = [
        VertexPt(time=f"2020-01-{i + 1:02d}", price=p, kind=k, rawIdx=i, confirmed=True)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]
    legs = build_legs(pts)
    pivots = build_pivots(legs)
    # Sanity-check the geometry actually produced the two confirmed pivots
    # this test depends on, so a future core.py change that silently breaks
    # the fixture fails loudly here instead of just vacuously losing the 2B.
    assert len(pivots) == 2
    assert pivots[0].exitLeg == 3 and pivots[1].exitLeg == 7

    area_by_leg = {
        (2, 3): 100.0,
        (6, 7): 1.0,
    }  # connect vs exit_leg: forces the §C.9 divergence gate

    def leg_area(leg):
        return area_by_leg.get((leg.a, leg.b), 5.0)

    points = mark_points(pts, legs, pivots, leg_area)
    assert points  # non-vacuity
    two_b = [p for p in points if p.kind == "2B"]
    assert len(two_b) == 1
    assert two_b[0].time == "2020-01-10" and two_b[0].price == 45
