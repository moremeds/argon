"""Unit tests for render_canary_v1_v2_compare (pure renderer)."""

from __future__ import annotations

from copy import deepcopy

import pytest

from uw_scan.reports.regime_canary_v1_v2_compare import (
    CANONICAL_WINDOWS,
    CCA_EVENT_DATES,
    FlipGateEvidence,
    render_canary_v1_v2_compare,
)


def _mk_run(*, version: str, scope: str, window_id: str, auc_60d: float = 0.65) -> dict:
    return {
        "id": 100 + ord(window_id[-1]),
        "composite_version": version,
        "run_scope": scope,
        "params": {
            "phase": "walk_forward",
            "batch_id": "batch-v2-test" if version == "2" else "batch-v1-test",
            "window_id": window_id,
            "score_form": "linear",
        },
        "summary": {
            "aucs": {
                "composite": {
                    "up5d_2pct": 0.62,
                    "up20d_5pct": 0.63,
                    "up60d_10pct": auc_60d,
                }
            }
        },
    }


def _happy_evidence() -> FlipGateEvidence:
    return FlipGateEvidence(
        v1_runs=[
            _mk_run(version="1", scope="production", window_id=w)
            for w in CANONICAL_WINDOWS
        ],
        v2_runs=[
            _mk_run(version="2", scope="research", window_id=w)
            for w in CANONICAL_WINDOWS
        ],
        v2_robustness_run={
            "id": 999,
            "composite_version": "2",
            "run_scope": "research",
            "params": {"phase": "robustness", "batch_id": "batch-v2-test"},
            "summary": {},
        },
        v1_full_history_aucs={
            "up5d_2pct": 0.620,
            "up20d_5pct": 0.627,
            "up60d_10pct": 0.619,
        },
        v2_full_history_aucs={
            "up5d_2pct": 0.625,
            "up20d_5pct": 0.635,
            "up60d_10pct": 0.640,
        },
        v1_band_distribution={
            "NONE": 55.0,
            "WATCH": 39.3,
            "BUY": 5.5,
            "STRONG_BUY": 0.2,
        },
        v2_band_distribution={
            "NONE": 60.0,
            "WATCH": 35.0,
            "BUY": 4.9,
            "STRONG_BUY": 0.1,
        },
        v2_cca_event_states={d: True for d in CCA_EVENT_DATES},
        oos_gate_passed=True,
        v1_payload_hash_golden_passed=True,
    )


def _replace(ev: FlipGateEvidence, **overrides) -> FlipGateEvidence:
    data = {
        f.name: getattr(ev, f.name)
        for f in FlipGateEvidence.__dataclass_fields__.values()
    }
    data.update(overrides)
    return FlipGateEvidence(**data)


def test_happy_path_ship_verdict():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Verdict: **SHIP**" in out
    for label in (
        "AC-F1 [PASS]",
        "AC-F2 [PASS]",
        "AC-F3 [PASS]",
        "AC-F4 [PASS]",
        "AC-F5 [PASS]",
        "AC-F6 [PASS]",
    ):
        assert label in out


def test_ac_f1_fail_below_bar():
    ev = _replace(
        _happy_evidence(),
        v2_full_history_aucs={
            "up5d_2pct": 0.625,
            "up20d_5pct": 0.635,
            "up60d_10pct": 0.620,
        },
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F1 [FAIL]" in out
    assert "Verdict: **STOP**" in out


def test_ac_f2_fail_20d_horizon():
    ev = _replace(
        _happy_evidence(),
        v2_full_history_aucs={
            "up5d_2pct": 0.625,
            "up20d_5pct": 0.610,
            "up60d_10pct": 0.640,
        },
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F2 [FAIL]" in out


def test_ac_f3_fail_when_cca_event_missing_fire():
    cca = {d: True for d in CCA_EVENT_DATES}
    cca["2011-08-08"] = False
    out = render_canary_v1_v2_compare(
        _replace(_happy_evidence(), v2_cca_event_states=cca)
    )
    assert "AC-F3 [FAIL]" in out
    assert "2011-08-08" in out


def test_ac_f4_fail_when_window_regresses_more_than_002():
    v2_runs = list(deepcopy(_happy_evidence().v2_runs))
    v2_runs[2]["summary"]["aucs"]["composite"]["up60d_10pct"] = 0.60
    out = render_canary_v1_v2_compare(_replace(_happy_evidence(), v2_runs=v2_runs))
    assert "AC-F4 [FAIL]" in out
    assert "WF-3" in out


def test_ac_f5_fail_when_watch_pct_too_high():
    bd = {"NONE": 44.5, "WATCH": 50.0, "BUY": 5.4, "STRONG_BUY": 0.1}
    out = render_canary_v1_v2_compare(
        _replace(_happy_evidence(), v2_band_distribution=bd)
    )
    assert "AC-F5 [FAIL]" in out


def test_ac_f6_fail_when_oos_gate_fails():
    out = render_canary_v1_v2_compare(
        _replace(_happy_evidence(), oos_gate_passed=False)
    )
    assert "AC-F6 [FAIL]" in out


def test_ac_f6_fail_when_v1_golden_fails():
    out = render_canary_v1_v2_compare(
        _replace(_happy_evidence(), v1_payload_hash_golden_passed=False)
    )
    assert "AC-F6 [FAIL]" in out


def test_invalid_v1_runs_count_raises():
    ev = _happy_evidence()
    bad = _replace(ev, v1_runs=ev.v1_runs[:5])
    with pytest.raises(ValueError, match="v1_runs must have 6"):
        render_canary_v1_v2_compare(bad)


def test_invalid_v2_scope_raises():
    ev = _happy_evidence()
    bad_runs = [deepcopy(r) for r in ev.v2_runs]
    bad_runs[0]["run_scope"] = "production"
    with pytest.raises(ValueError, match="run_scope"):
        render_canary_v1_v2_compare(_replace(ev, v2_runs=bad_runs))


def test_invalid_window_id_set_raises():
    ev = _happy_evidence()
    bad_runs = [deepcopy(r) for r in ev.v2_runs]
    bad_runs[0]["params"]["window_id"] = "WF-99"
    with pytest.raises(ValueError, match="window_ids"):
        render_canary_v1_v2_compare(_replace(ev, v2_runs=bad_runs))


def test_v2_runs_must_share_batch_id():
    ev = _happy_evidence()
    bad_runs = [deepcopy(r) for r in ev.v2_runs]
    bad_runs[0]["params"]["batch_id"] = "different-batch"
    with pytest.raises(ValueError, match="batch_id"):
        render_canary_v1_v2_compare(_replace(ev, v2_runs=bad_runs))


def test_missing_cca_event_date_raises():
    ev = _happy_evidence()
    bad_cca = {d: True for d in CCA_EVENT_DATES if d != "2020-03-09"}
    with pytest.raises(ValueError, match="2020-03-09"):
        render_canary_v1_v2_compare(_replace(ev, v2_cca_event_states=bad_cca))


def test_footer_present_in_both_verdicts():
    out_ship = render_canary_v1_v2_compare(_happy_evidence())
    assert "What PR 2 will do iff this verdict is SHIP" in out_ship

    ev_stop = _replace(
        _happy_evidence(),
        v2_full_history_aucs={"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
    )
    out_stop = render_canary_v1_v2_compare(ev_stop)
    assert "What PR 2 will do iff this verdict is SHIP" in out_stop
    assert "Verdict: **STOP**" in out_stop


def test_band_distribution_table_present():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Band distribution" in out
    for b in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        assert b in out


def test_per_window_table_present_with_all_6_windows():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Per-window 60d AUC" in out
    for w in CANONICAL_WINDOWS:
        assert w in out
