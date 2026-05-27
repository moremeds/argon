"""Unit tests for render_canary_form_sweep_compare."""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.reports.regime_canary_backtest_report import (
    render_canary_form_sweep_compare,
)


def _mk_run(
    *,
    run_id: int,
    form: str,
    batch_id: str = "batch-1",
    composite_60d: float = 0.620,
    vol_60d: float = 0.640,
    watch_pct: float = 39.3,
    buy_band_60d: float = 0.348,
    buy_pct: float = 5.5,
    strong_buy_pct: float = 0.0,
) -> dict:
    """Minimal row shape consumed by the renderer."""
    n_days = 3843
    return {
        "id": run_id,
        "run_scope": "research",
        "start_date": date(2011, 2, 8),
        "end_date": date(2026, 5, 21),
        "composite_version": "1",
        "params": {
            "score_form": form,
            "phase": "form_sweep_full",
            "batch_id": batch_id,
        },
        "summary": {
            "is_winning_form": False,
            "score_form": form,
            "batch_id": batch_id,
            "n_days": n_days,
            "aucs": {
                "composite": {
                    "up5d_2pct": 0.620,
                    "up20d_5pct": 0.627,
                    "up60d_10pct": composite_60d,
                },
                "vol_only": {
                    "up5d_2pct": 0.626,
                    "up20d_5pct": 0.639,
                    "up60d_10pct": vol_60d,
                },
                "speed_only": {
                    "up5d_2pct": 0.470,
                    "up20d_5pct": 0.465,
                    "up60d_10pct": 0.430,
                },
            },
            "band_distribution": {
                "NONE": int(
                    n_days
                    * (1 - watch_pct / 100 - buy_pct / 100 - strong_buy_pct / 100)
                ),
                "WATCH": int(n_days * watch_pct / 100),
                "BUY": int(n_days * buy_pct / 100),
                "STRONG_BUY": int(n_days * strong_buy_pct / 100),
            },
            "within_band_aucs": {
                "NONE": {"up5d_2pct": 0.581, "up20d_5pct": 0.601, "up60d_10pct": 0.586},
                "WATCH": {
                    "up5d_2pct": 0.559,
                    "up20d_5pct": 0.633,
                    "up60d_10pct": 0.609,
                },
                "BUY": {
                    "up5d_2pct": 0.447,
                    "up20d_5pct": 0.431,
                    "up60d_10pct": buy_band_60d,
                },
                "STRONG_BUY": {
                    "up5d_2pct": None,
                    "up20d_5pct": None,
                    "up60d_10pct": None,
                },
            },
            "vol_only_gap": {
                "up5d_2pct": 0.006,
                "up20d_5pct": 0.012,
                "up60d_10pct": vol_60d - composite_60d,
            },
        },
    }


def _full_set(batch_id: str = "batch-1") -> list[dict]:
    return [
        _mk_run(run_id=27, form="linear", batch_id=batch_id),
        _mk_run(run_id=28, form="convex", batch_id=batch_id),
        _mk_run(run_id=29, form="concave", batch_id=batch_id),
        _mk_run(run_id=30, form="sigmoid", batch_id=batch_id),
    ]


def test_canonical_form_ordering():
    """Output rows always: linear → convex → concave → sigmoid, regardless of input order."""
    runs = [
        _mk_run(run_id=i, form=f)
        for i, f in enumerate(("sigmoid", "concave", "linear", "convex"), start=100)
    ]
    out = render_canary_form_sweep_compare(runs)
    li = out.index("| linear ")
    cv = out.index("| convex ")
    cc = out.index("| concave")
    sg = out.index("| sigmoid")
    assert li < cv < cc < sg, (
        f"unexpected order: linear={li} convex={cv} concave={cc} sigmoid={sg}"
    )


def test_missing_form_raises():
    """3 rows (sigmoid missing) — length check fires first with 'got 3'."""
    runs = _full_set()[:3]  # missing sigmoid
    with pytest.raises(ValueError, match=r"got 3"):
        render_canary_form_sweep_compare(runs)


def test_duplicate_form_raises():
    runs = _full_set()
    runs[1] = _mk_run(run_id=99, form="linear")  # 2 linears now
    with pytest.raises(ValueError, match="linear|duplicate"):
        render_canary_form_sweep_compare(runs)


def test_fewer_than_4_rows_raises():
    with pytest.raises(ValueError, match="4"):
        render_canary_form_sweep_compare(_full_set()[:2])


def test_mismatched_batch_id_raises():
    runs = _full_set("batch-1")
    runs[2] = _mk_run(run_id=99, form="concave", batch_id="batch-2")
    with pytest.raises(ValueError, match="batch_id"):
        render_canary_form_sweep_compare(runs)


def test_non_research_scope_raises():
    runs = _full_set()
    runs[0]["run_scope"] = "production"
    with pytest.raises(ValueError, match="research"):
        render_canary_form_sweep_compare(runs)


def test_footer_present():
    out = render_canary_form_sweep_compare(_full_set())
    assert "What this run does NOT decide" in out
    assert "candidate-discovery" in out.lower() or "candidate discovery" in out.lower()


def test_observation_watch_overfire():
    """WATCH% > 30 in linear (default fixture has 39.3) — should appear in observations."""
    out = render_canary_form_sweep_compare(_full_set())
    lines = [line for line in out.splitlines() if "WATCH% above 30%" in line]
    assert lines, "expected WATCH% above 30% observation line"
    assert "linear" in lines[0]


def test_observation_buy_band_inversion():
    """BUY-band 60d AUC < 0.50 in linear (default 0.348) — should appear."""
    out = render_canary_form_sweep_compare(_full_set())
    lines = [line for line in out.splitlines() if "BUY-band 60d AUC below 0.50" in line]
    assert lines
    assert "linear" in lines[0]


def test_observation_composite_improves_over_linear():
    """If convex 60d AUC > linear 60d by >=0.02, it should be listed."""
    runs = [
        _mk_run(run_id=27, form="linear", composite_60d=0.620),
        _mk_run(run_id=28, form="convex", composite_60d=0.650),  # +0.030
        _mk_run(run_id=29, form="concave", composite_60d=0.610),
        _mk_run(run_id=30, form="sigmoid", composite_60d=0.620),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [
        line
        for line in out.splitlines()
        if "Composite 60d AUC improves over linear" in line
    ]
    assert lines
    assert "convex" in lines[0]
    assert "concave" not in lines[0]


def test_observation_watch_reduce_without_auc_loss():
    """If sigmoid has WATCH%-5pp AND 60d AUC within 0.01 of linear, list it."""
    runs = [
        _mk_run(run_id=27, form="linear", watch_pct=39.3, composite_60d=0.620),
        _mk_run(run_id=28, form="convex", watch_pct=39.0, composite_60d=0.620),
        _mk_run(run_id=29, form="concave", watch_pct=39.5, composite_60d=0.620),
        _mk_run(run_id=30, form="sigmoid", watch_pct=33.0, composite_60d=0.615),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [line for line in out.splitlines() if "WATCH% reduced by" in line]
    assert lines
    assert "sigmoid" in lines[0]


def test_observation_vol_only_gap():
    """Vol-only gap ≥ +0.02 (= vol_only_60d - composite_60d ≥ 0.02): listed."""
    runs = [
        _mk_run(run_id=27, form="linear", composite_60d=0.620, vol_60d=0.625),
        _mk_run(run_id=28, form="convex", composite_60d=0.620, vol_60d=0.650),
        _mk_run(run_id=29, form="concave", composite_60d=0.620, vol_60d=0.625),
        _mk_run(run_id=30, form="sigmoid", composite_60d=0.620, vol_60d=0.625),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [
        line for line in out.splitlines() if "Vol-only gap (60d) ≥ +0.02 in" in line
    ]
    assert lines, "expected vol-only gap observation line"
    assert "convex" in lines[0]
    assert "linear" not in lines[0]
    assert "concave" not in lines[0]
    assert "sigmoid" not in lines[0]


def test_observation_buy_pct_zero():
    """BUY% at exactly 0 (band never fires): listed."""
    runs = [
        _mk_run(run_id=27, form="linear", buy_pct=5.5),
        _mk_run(run_id=28, form="convex", buy_pct=0.0),
        _mk_run(run_id=29, form="concave", buy_pct=0.0),
        _mk_run(run_id=30, form="sigmoid", buy_pct=2.0),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [
        line
        for line in out.splitlines()
        if "BUY% at exactly 0 (band never fires) in" in line
    ]
    assert lines, "expected BUY%=0 observation line"
    assert "convex" in lines[0]
    assert "concave" in lines[0]
    assert "linear" not in lines[0]
    assert "sigmoid" not in lines[0]


def test_observation_strong_buy_pct_zero():
    """STRONG_BUY% at exactly 0: listed."""
    out = render_canary_form_sweep_compare(_full_set())
    lines = [
        line
        for line in out.splitlines()
        if "STRONG_BUY% at exactly 0 (band never fires) in" in line
    ]
    assert lines, "expected STRONG_BUY%=0 observation line"
    for form in ("linear", "convex", "concave", "sigmoid"):
        assert form in lines[0], f"{form} missing from STRONG_BUY%=0 line"


def test_observation_none_when_no_form_matches():
    """Rule that has zero matches must print `none`."""
    runs = [
        _mk_run(
            run_id=27,
            form="linear",
            watch_pct=25.0,
            buy_band_60d=0.60,
            composite_60d=0.620,
            vol_60d=0.620,
            buy_pct=5.0,
            strong_buy_pct=3.0,
        ),
        _mk_run(
            run_id=28,
            form="convex",
            watch_pct=24.0,
            buy_band_60d=0.60,
            composite_60d=0.620,
            vol_60d=0.620,
            buy_pct=5.0,
            strong_buy_pct=3.0,
        ),
        _mk_run(
            run_id=29,
            form="concave",
            watch_pct=23.0,
            buy_band_60d=0.60,
            composite_60d=0.620,
            vol_60d=0.620,
            buy_pct=5.0,
            strong_buy_pct=3.0,
        ),
        _mk_run(
            run_id=30,
            form="sigmoid",
            watch_pct=22.0,
            buy_band_60d=0.60,
            composite_60d=0.620,
            vol_60d=0.620,
            buy_pct=5.0,
            strong_buy_pct=3.0,
        ),
    ]
    out = render_canary_form_sweep_compare(runs)
    for label in (
        "WATCH% above 30% in",
        "BUY-band 60d AUC below 0.50 in",
        "Vol-only gap (60d) ≥ +0.02 in",
        "BUY% at exactly 0 (band never fires) in",
        "STRONG_BUY% at exactly 0 (band never fires) in",
    ):
        matching = [line for line in out.splitlines() if label in line]
        assert matching, f"missing observation line for: {label}"
        assert "none" in matching[0], (
            f"rule '{label}' should report 'none' when no form matches, "
            f"got: {matching[0]!r}"
        )
