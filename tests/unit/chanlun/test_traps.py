from __future__ import annotations

from datetime import date, timedelta

from tests.unit.chanlun.parity_helpers import GOLDEN, bars_from_golden
from uw_scan.chanlun.core import (
    build_legs,
    build_pivots,
    macd_hist,
    merge_overlapping_zhongshus,
    resample_weekly,
)
from uw_scan.chanlun.full import compute_chanlun, compute_chanlun_full
from uw_scan.chanlun.points import mark_divergences, mark_points, mark_resonance
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
    # §G.4 — structural equality compares numeric VALUE, not JSON text or
    # Python type. The golden JSON stores whole-dollar prices as ints (JS
    # Number formatting drops the trailing .0), so a record like price=196
    # parses as Python int while the computed pipeline value is float 196.0.
    # Pin that our parity comparison is value-based: coerce the input bars to
    # float (as any real feed would), find the golden int-typed prices, and
    # assert value equality holds exactly where a type-strict comparison
    # (`type(a) is type(g)`) would have failed. Catches a wrong port that
    # compares via JSON text ("196" != "196.0") or via type-strict equality.
    bars = [
        ChanlunBar(
            time=b.time, high=float(b.high), low=float(b.low), close=float(b.close)
        )
        for b in bars_from_golden()
    ]
    r = compute_chanlun(bars)
    int_idxs = [
        i for i, g in enumerate(GOLDEN["vertices"]) if isinstance(g["price"], int)
    ]
    assert int_idxs  # non-vacuity: fixture must contain whole-dollar JSON ints
    for i in int_idxs:
        g = GOLDEN["vertices"][i]["price"]
        a = r.vertices[i].price
        assert isinstance(a, float) and type(a) is not type(g)  # boundary is real
        assert a == g  # value-based equality is what parity relies on


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


def test_trap06_no_empty_max_min_on_short_inputs():
    # §G.6 — JS Math.max(...[]) silently yields -Infinity; Python max([])
    # raises ValueError. build_pivots' `while i <= len(legs) - 3` guard must
    # structurally exclude an empty (or short) trio slice — feed it inputs
    # BELOW the trio window and require empty output with no exception.
    # Catches a mis-ported loop guard (e.g. `while i < len(legs)`): verified
    # by mutation — on the 2-leg input below the broken guard fabricates a
    # pivot from a 2-leg "trio" (failing `== []`), and any variant that walks
    # past the end hits max(())/min(()) -> ValueError, the §G.6 divergence.
    assert build_pivots([]) == []
    # labeled test double: hand-built abstract geometry (3 vertices -> 2 legs,
    # one below the trio window) — NOT market data.
    pts = [
        VertexPt(time="2020-01-01", price=100, kind="top", rawIdx=0, confirmed=True),
        VertexPt(time="2020-01-02", price=90, kind="bottom", rawIdx=1, confirmed=True),
        VertexPt(time="2020-01-03", price=95, kind="top", rawIdx=2, confirmed=True),
    ]
    legs = build_legs(pts)
    assert len(legs) == 2  # below the 3-leg window
    assert build_pivots(legs) == []


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


def test_trap08_sunday_monday_week_boundary():
    # §G.8/§G.9 — the ISO week runs Monday..Sunday. JS getUTCDay() numbers
    # Sunday=0; Python weekday() numbers Sunday=6 — the exact numbering trap.
    # labeled test double: hand-built abstract geometry spanning a Sunday —
    # NOT market data (dates chosen purely for their weekday positions).
    #
    # Catches (a) a port that used JS getUTCDay() numbering (Sunday offset 0
    # -> Sunday starts its own week, splitting Fri/Sun), and (b) a port that
    # double-applied the (x+6)%7 transform on top of weekday() (Monday offset
    # 6 -> Monday joins the PREVIOUS week, merging all three bars).
    bars = [
        ChanlunBar(time="2024-01-12", high=10, low=5, close=8),  # Friday
        ChanlunBar(time="2024-01-14", high=12, low=4, close=6),  # Sunday, same ISO week
        ChanlunBar(time="2024-01-15", high=9, low=6, close=7),  # Monday, NEXT week
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 2  # Fri+Sun merge; Monday starts a new week
    assert weekly[0].time == "2024-01-14"  # last session of week 1 (the Sunday)
    assert weekly[0].high == 12 and weekly[0].low == 4 and weekly[0].close == 6
    assert weekly[1].time == "2024-01-15"
    # And a full Monday..Friday run stays ONE week (no boundary inside it).
    week_run = [
        ChanlunBar(
            time=(date(2024, 1, 15) + timedelta(days=k)).isoformat(),
            high=10 + k,
            low=5,
            close=8,
        )
        for k in range(5)  # Mon 2024-01-15 .. Fri 2024-01-19
    ]
    merged = resample_weekly(week_run)
    assert len(merged) == 1 and merged[0].time == "2024-01-19"


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


def test_trap11_leg_area_end_inclusive():
    # §G.11 — the TS MACD-area loop `for (let r = l.rawA + 1; r <= l.rawB; r++)`
    # is END-INCLUSIVE; the Python port must be range(rawA+1, rawB+1). A naive
    # range(rawA+1, rawB) port drops hist[rawB] from every leg area, which on
    # the golden data flips the 2025-12-03 divergence decision (verified by
    # mutation). Recompute the divergence set with an explicit end-inclusive
    # while-loop (independent of Python's range idiom, mirroring the TS <=
    # bound verbatim) and require the real pipeline to agree exactly.
    bars = bars_from_golden()
    r = compute_chanlun(bars)
    idx_by_time = {b.time: i for i, b in enumerate(bars)}
    pts = [
        VertexPt(
            time=v.time,
            price=v.price,
            kind=v.kind,
            rawIdx=idx_by_time[v.time],
            confirmed=v.confirmed,
        )
        for v in r.vertices
    ]
    legs = build_legs(pts)
    hist = macd_hist([b.close for b in bars])

    def leg_area_inclusive(leg):
        s = 0.0
        k = leg.rawA + 1
        while k <= leg.rawB:  # TS `r <= l.rawB` bound, ported literally
            s += abs(hist[k])
            k += 1
        return s

    expected = mark_divergences(pts, legs, leg_area_inclusive)
    assert expected  # non-vacuity
    assert [(d.time, d.price, d.kind, d.confirmed) for d in r.divergences] == [
        (d.time, d.price, d.kind, d.confirmed) for d in expected
    ]


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


def _zigzag_bars(waypoints: list[float], leg_days: list[int]) -> list[ChanlunBar]:
    """Deterministic piecewise-linear daily bars through `waypoints`.

    labeled test double: hand-built abstract geometry — NOT market data.
    Closes interpolate linearly between waypoints over `leg_days` weekday
    sessions each; high/low = close +/- 0.5 (strictly monotone along a leg,
    so no inclusion-merging noise). Dates are consecutive weekdays from
    Monday 2020-01-06.
    """
    closes = [waypoints[0]]
    for w0, w1, n in zip(waypoints, waypoints[1:], leg_days):
        for k in range(1, n + 1):
            closes.append(w0 + (w1 - w0) * k / n)
    dates: list[str] = []
    d = date(2020, 1, 6)  # a Monday
    while len(dates) < len(closes):
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return [
        ChanlunBar(time=t, high=c + 0.5, low=c - 0.5, close=c)
        for t, c in zip(dates, closes)
    ]


def test_resonance_true_end_to_end():
    # §C.13 区间套 — the `resonant=True` branch exercised through the REAL
    # compute_chanlun_full daily+weekly chain (GOLDEN["points"] has zero
    # resonant points, so full parity never reaches this branch; trap07 only
    # covers it against a hand-built weekly ChanlunResult).
    #
    # Geometry: a ~48-week zigzag (legs ~6 weeks each) whose swings are big
    # and slow enough that the DAILY and WEEKLY pipelines see the same 中枢
    # (80-95 pivot from the first three legs) and the same 3B pullback low.
    # Leg lengths are tuned so the pullback bottom (97 waypoint) lands on a
    # FRIDAY — the last session of its ISO week — making the daily vertex
    # time equal the weekly candle time, so the daily 3B sits exactly at the
    # start of the weekly 3B's resonance window (w.from <= p.time <= w.to).
    bars = _zigzag_bars(
        waypoints=[100, 80, 95, 78, 120, 97, 125, 98, 130],
        leg_days=[30, 30, 30, 30, 29, 30, 30, 30],  # 29 puts the 97-low on a Friday
    )
    r = compute_chanlun_full(bars)
    assert r.points  # non-vacuity
    resonant = [p for p in r.points if p.resonant is True]
    assert len(resonant) == 1
    p = resonant[0]
    assert p.kind == "3B" and p.confirmed
    assert p.time == "2020-07-31"  # the Friday pullback low
    # §C.13: the resonance must be corroborated by a same-side confirmed
    # weekly point sitting on a weekly vertex — recompute the weekly level
    # via the same public pipeline and check side + window anchoring.
    weekly = compute_chanlun(resample_weekly(bars))
    weekly_b = [q for q in weekly.points if q.confirmed and q.kind.endswith("B")]
    assert weekly_b  # a confirmed same-side weekly point exists
    assert any(
        q.time <= p.time
        and any(v.time == q.time and v.price == q.price for v in weekly.vertices)
        for q in weekly_b
    )
