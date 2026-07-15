"""Gate/metric math smoke test for the chanlun sub-level probe.

Loads scripts/research/chanlun_sublevel_probe.py by file path (scripts/ is not
an importable package) and feeds hand-built MarkTrace sets (labeled test
doubles, not market data) through compute_metrics/gate_pass.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

_PROBE_PATH = (
    Path(__file__).resolve().parents[3] / "scripts/research/chanlun_sublevel_probe.py"
)
_spec = importlib.util.spec_from_file_location("chanlun_sublevel_probe", _PROBE_PATH)
probe = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec: CPython's dataclasses processing (KW_ONLY
# sentinel check) looks up cls.__module__ in sys.modules when field annotations
# are stringified (`from __future__ import annotations`, as the probe module
# uses) — an unregistered module makes `_process_class` crash on MarkTrace.
sys.modules[_spec.name] = probe
_spec.loader.exec_module(probe)


def _trace(**kw):
    base = dict(
        ticker="AAPL",
        category="vertex",
        kind="bottom",
        extreme_date=date(2026, 1, 5),
        extreme_price=100.0,
        pending_idx=10,
        pending_date=date(2026, 1, 5),
    )
    base.update(kw)
    return probe.MarkTrace(**base)


def test_metrics_survival_breach_latency_lead():
    traces = [
        # survived: latency 11-10=1 session, lead 15-11=4 sessions
        _trace(
            sublevel_idx=11,
            sublevel_date=date(2026, 1, 6),
            native_idx=15,
            native_date=date(2026, 1, 12),
        ),
        # breached after sublevel: latency 12-10=2
        _trace(
            sublevel_idx=12,
            sublevel_date=date(2026, 1, 7),
            invalidated_date=date(2026, 1, 9),
            invalid_reason="breach",
        ),
        # right-censored: sublevel but never resolved
        _trace(sublevel_idx=13, sublevel_date=date(2026, 1, 8)),
        # never reached sublevel: excluded from every sub-level metric
        _trace(),
    ]
    m = probe.compute_metrics(traces)
    assert m.n_sublevel == 3 and m.n_resolved == 2 and m.n_censored == 1
    assert m.survival == 0.5 and m.breach_rate == 0.5
    assert m.median_latency == 2.0  # latencies [1, 2, 3] -> median 2.0
    assert m.median_lead == 4.0


def test_gate_pass_thresholds_are_inclusive():
    good = probe.Metrics(
        n_sublevel=10,
        n_resolved=10,
        n_censored=0,
        survival=0.70,
        breach_rate=0.15,
        median_latency=2.0,
        median_lead=5.0,
    )
    assert probe.gate_pass(good) is True  # spec bounds are inclusive
    assert probe.gate_pass(probe.Metrics(10, 10, 0, 0.69, 0.10, 1.0, 5.0)) is False
    assert probe.gate_pass(probe.Metrics(10, 10, 0, 0.90, 0.16, 1.0, 5.0)) is False
    assert probe.gate_pass(probe.Metrics(10, 10, 0, 0.90, 0.10, 2.5, 5.0)) is False


def test_gate_fails_on_no_evidence():
    empty = probe.Metrics(
        n_sublevel=0,
        n_resolved=0,
        n_censored=0,
        survival=None,
        breach_rate=None,
        median_latency=None,
        median_lead=None,
    )
    assert probe.gate_pass(empty) is False  # no data != pass


def test_split_excluded_marks_leave_the_metrics_entirely():
    traces = [
        _trace(
            sublevel_idx=11,
            sublevel_date=date(2026, 1, 6),
            invalidated_date=date(2026, 1, 9),
            invalid_reason="split_boundary",
        ),
    ]
    m = probe.compute_metrics(traces)
    assert m.n_sublevel == 0  # split-boundary marks never enter the denominators
