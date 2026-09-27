"""Tercile / conditioning / gate logic of the sector RS breadth probe.

Every series here is a labelled TEST DOUBLE: hand-built breadth fractions and
RS signs with no market meaning, on consecutive calendar days. They exercise
indexing and arithmetic only. No prices are involved.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[3] / "scripts/research/sector_rs_breadth_probe.py"
)
_spec = importlib.util.spec_from_file_location("sector_rs_breadth_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = probe
_spec.loader.exec_module(probe)

D0 = date(1998, 12, 22)


def _rows(breadths, rs=None, degraded=()):
    rs = rs or [1.0] * len(breadths)
    return [
        probe.DailyRow("Technology", D0 + timedelta(days=i), rs[i], b, b, i in degraded)
        for i, b in enumerate(breadths)
    ]


def test_grid_is_non_overlapping_and_starts_after_min_history():
    rows = _rows([0.5] * 200)
    pairs = probe.monthly_pairs(rows, "breadth_1m")
    # grid 0, 21, ...; i + 21 < 200; eligible once 63 past values exist
    assert [p.as_of for p in pairs] == [
        rows[i].as_of for i in (63, 84, 105, 126, 147, 168)
    ]


def test_tercile_uses_only_past_values():
    rising = _rows([i / 200 for i in range(200)])
    assert not any(p.cond for p in probe.monthly_pairs(rising, "breadth_1m"))
    falling = _rows([1 - i / 200 for i in range(200)])
    assert all(p.cond for p in probe.monthly_pairs(falling, "breadth_1m"))
    # A future collapse cannot change an earlier observation's cut
    changed = _rows([i / 200 for i in range(199)] + [0.0])
    before = {p.as_of: p.cut for p in probe.monthly_pairs(rising, "breadth_1m")}
    after = {p.as_of: p.cut for p in probe.monthly_pairs(changed, "breadth_1m")}
    assert before == after


def test_condition_requires_positive_rs_and_outcome_reads_t_plus_21():
    b = [1 - i / 200 for i in range(200)]
    rs = [(-1.0 if i == 84 else 1.0) for i in range(200)]
    rs[105] = -2.0  # the outcome of the observation at 84
    pairs = {p.as_of: p for p in probe.monthly_pairs(_rows(b, rs=rs), "breadth_1m")}
    assert pairs[D0 + timedelta(days=84)].cond is False  # rs_1m(t) <= 0
    assert pairs[D0 + timedelta(days=84)].outcome_neg is True
    assert pairs[D0 + timedelta(days=63)].outcome_neg is True  # rs at 84 < 0


def test_degraded_rows_drop_their_pairs():
    pairs = probe.monthly_pairs(_rows([0.5] * 200, degraded={84}), "breadth_1m")
    kept = {p.as_of for p in pairs}
    assert D0 + timedelta(days=84) not in kept  # t degraded
    assert D0 + timedelta(days=63) not in kept  # t+21 degraded


def test_effective_start_is_the_first_clean_row_after_the_thin_years():
    # labelled test double: 300 rows at coverage 0.5 (below the 0.8 floor, so
    # degraded), then 400 rows at coverage 0.9 (clean)
    rows = _rows([0.5] * 700, degraded=set(range(300)))
    assert probe.effective_start(rows) == rows[300].as_of


def test_effective_start_moves_past_a_later_dip_and_can_be_none():
    # 20 degraded rows inside any 252-window → 92% < 95%: the start moves past them
    rows = _rows([0.5] * 700, degraded=set(range(400, 420)))
    assert probe.effective_start(rows) == rows[420].as_of
    # every 10th row degraded → 90% everywhere → never qualifies
    assert (
        probe.effective_start(_rows([0.5] * 700, degraded=set(range(0, 700, 10))))
        is None
    )
    assert probe.effective_start(_rows([0.5] * 100)) is None  # shorter than one window


def _pair(cond, neg, day=0):
    return probe.Pair(
        "Technology", D0 + timedelta(days=day), "breadth_1m", 0.1, 0.2, cond, neg
    )


def test_stats_math():
    ps = [
        _pair(True, True),
        _pair(True, False),
        _pair(False, True),
        _pair(False, False),
        _pair(False, False),
        _pair(False, False),
    ]
    n, n_c, p_c, p_base, diff = probe.stats(ps)
    assert (n, n_c) == (6, 2)
    assert p_c == 0.5 and abs(p_base - 2 / 6) < 1e-12 and abs(diff - 1 / 6) < 1e-12
    assert probe.stats([_pair(False, True)])[2] is None  # C never fired


def test_bootstrap_is_seeded_and_brackets_the_point_estimate():
    ps = [_pair(i % 3 == 0, i % 2 == 0, i) for i in range(60)]
    a = probe.bootstrap_ci(ps, b=500)
    assert a == probe.bootstrap_ci(ps, b=500)
    assert a[0] <= probe.stats(ps)[4] <= a[1]


def _res(group, diff, lo, hi, split="oos"):
    return probe.Result(
        "breadth_1m", split, group, 100, 30, 0.5, 0.5 - diff, diff, lo, hi
    )


def test_gate_passes_and_fails_on_the_right_reasons():
    ok = [_res("POOLED", 0.10, 0.02, 0.18), _res("Technology", 0.05, -0.05, 0.15)]
    assert probe.gate(ok, "breadth_1m") == (True, [])
    ci_spans_zero = [
        _res("POOLED", 0.10, -0.01, 0.21),
        _res("Technology", 0.05, -0.05, 0.15),
    ]
    passed, why = probe.gate(ci_spans_zero, "breadth_1m")
    assert not passed and "pooled OOS" in why[0]
    catastrophic = [
        _res("POOLED", 0.10, 0.02, 0.18),
        _res("Energy", -0.20, -0.30, -0.10),
    ]
    passed, why = probe.gate(catastrophic, "breadth_1m")
    assert not passed and why[0].startswith("Energy")
