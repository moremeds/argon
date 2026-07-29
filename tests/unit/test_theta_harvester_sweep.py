"""Weight-sweep metrics — pure, no DB.

The sweep is the only thing in the feature that can say whether the score
carries information, so its metrics are tested directly rather than inferred
from a green end-to-end run.
"""

from datetime import date

import pytest

from scripts.research.theta_harvester_weight_sweep import (
    Row,
    build_grid,
    cross_sectional_ic,
    evaluate_config,
    selected_rows,
)
from uw_scan.scanners.theta_harvester import DEFAULT_WEIGHTS, RADON_WEIGHTS

_DEFAULT = {"kind": "weights", **DEFAULT_WEIGHTS.__dict__}
_RADON = {"kind": "weights", **RADON_WEIGHTS.__dict__}
_UNCOND = {"kind": "unconditional"}


def _row(
    edge: float,
    nd: float,
    rs: float,
    ret: float,
    *,
    ratio: float = 1.5,
    dealer: str = "SUPPORT",
    as_of: date = date(2026, 3, 2),
) -> Row:
    return Row(
        ticker="IWM",
        as_of=as_of,
        iv_rv_edge=edge,
        iv_rv_ratio=ratio,
        net_delta=nd,
        range_score=rs,
        dealer_support=dealer,
        theta_positive=True,
        ret=ret,
    )


def _ordered_session(as_of: date, *, sign: float = 1.0) -> list[Row]:
    """One session whose score ordering matches its outcome ordering exactly.

    Edges stay strictly below DEFAULT_WEIGHTS.edge_saturation_pts (15.0). Above
    it vol_c pins at 1.0 and every score ties, which would cap Spearman well
    under 1 and make a perfect-ordering assertion unsatisfiable.
    """
    return [
        _row(float(e), 0.0, 0.5, sign * float(e) / 1000.0, as_of=as_of)
        for e in range(1, 15)
    ]


def test_unconditional_takes_every_row():
    rows = [_row(0.0, 0.5, 0.0, -0.01), _row(30.0, 0.0, 1.0, 0.02)]
    assert len(selected_rows(rows, config=_UNCOND)) == 2


def test_weighted_config_filters_on_score_and_gates():
    rows = [
        _row(30.0, 0.0, 1.0, 0.02),  # max score, clears everything
        _row(0.0, 0.5, 0.0, -0.01, ratio=0.95),  # fails the iv AND delta gates
    ]
    assert [r.ret for r in selected_rows(rows, config=_DEFAULT)] == [0.02]


def test_iv_gate_accepts_either_the_edge_or_the_ratio_branch():
    # threshold=0 isolates the gate: at the default 70 a low-edge row is
    # rejected by the SCORE, so the test would pass without the gate existing.
    open_gate = {**_DEFAULT, "threshold": 0.0}
    assert selected_rows([_row(6.0, 0.0, 1.0, 0.01, ratio=0.95)], config=open_gate)
    assert selected_rows([_row(0.0, 0.0, 1.0, 0.01, ratio=1.20)], config=open_gate)
    assert not selected_rows([_row(0.0, 0.0, 1.0, 0.01, ratio=0.95)], config=open_gate)


def test_dealer_gate_only_bites_when_critical():
    rows = [_row(30.0, 0.0, 1.0, 0.02, dealer="NO_SUPPORT")]
    assert selected_rows(rows, config=_DEFAULT)
    assert not selected_rows(rows, config=_RADON)


def test_evaluate_reports_effective_n_not_row_count():
    # 40 rows but only two distinct entry months -> effective N is months. A
    # Sharpe over 40 overlapping rows would overstate significance ~4x.
    rows = [_row(30.0, 0.0, 1.0, 0.01, as_of=date(2026, 3, d)) for d in range(2, 22)]
    rows += [_row(30.0, 0.0, 1.0, 0.01, as_of=date(2026, 4, d)) for d in range(2, 22)]
    out = evaluate_config(rows, config=_UNCOND)
    assert out["n_trades"] == 40
    assert out["metrics"]["effective_n_months"] == 2


def test_empty_selection_returns_metrics_not_an_exception():
    out = evaluate_config([], config=_UNCOND)
    assert out["n_trades"] == 0
    assert out["metrics"]["sharpe"] is None


def test_ic_is_positive_when_score_orders_outcomes_correctly():
    rows = [r for d in (2, 3, 4) for r in _ordered_session(date(2026, 3, d))]
    out = cross_sectional_ic(rows, config=_DEFAULT)
    assert out["session_ic"] == pytest.approx(1.0)
    assert out["ic_sessions"] == 3


def test_ic_is_negative_when_the_score_is_backwards():
    rows = [r for d in (2, 3, 4) for r in _ordered_session(date(2026, 3, d), sign=-1.0)]
    out = cross_sectional_ic(rows, config=_DEFAULT)
    assert out["session_ic"] == pytest.approx(-1.0)


def test_ic_is_none_for_the_unconditional_control():
    # The control arm has no score, therefore no ordering hypothesis to test.
    rows = [r for d in (2, 3, 4) for r in _ordered_session(date(2026, 3, d))]
    out = cross_sectional_ic(rows, config=_UNCOND)
    assert out["session_ic"] is None


def test_ic_needs_at_least_three_sessions():
    rows = [r for d in (2, 3) for r in _ordered_session(date(2026, 3, d))]
    out = cross_sectional_ic(rows, config=_DEFAULT)
    assert out["session_ic"] is None
    assert out["ic_t_stat"] is None
    assert out["ic_sessions"] == 2


def test_ic_ignores_the_threshold_and_keeps_the_whole_cross_section():
    """Scoring only the rows above the threshold would discard the bottom of
    the cross-section — exactly the part that reveals whether the score orders
    anything. A threshold high enough to select nothing must still yield an IC.
    """
    rows = [r for d in (2, 3, 4) for r in _ordered_session(date(2026, 3, d))]
    config = {**_DEFAULT, "threshold": 999.0}
    assert selected_rows(rows, config=config) == []
    assert cross_sectional_ic(rows, config=config)["session_ic"] == pytest.approx(1.0)


def test_grid_always_contains_the_three_named_configs():
    assert {"unconditional", "radon", "default"} <= {
        c.get("name") for c in build_grid()
    }
