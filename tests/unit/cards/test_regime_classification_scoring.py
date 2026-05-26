from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.regime_classification_scoring import (
    build_confusion_matrix,
    cohens_kappa,
    macro_f1_over_eligible,
    normalize_vcg_label,
    per_class_prf,
    sanitize_for_json,
    weighted_f1_over_eligible,
)

CLASSES = ["NORMAL", "SUPPRESSED", "EDR", "RISK_OFF", "PANIC", "BOUNCE"]


# ---- Task 4.1: normalize + confusion matrix ----


def test_normalize_vcg_label_canonical_pass_through():
    for c in CLASSES:
        assert normalize_vcg_label(c) == c


def test_normalize_vcg_label_handles_common_variants():
    assert normalize_vcg_label("risk_off") == "RISK_OFF"
    assert normalize_vcg_label("normal") == "NORMAL"
    assert normalize_vcg_label("EDR ") == "EDR"
    assert normalize_vcg_label(" PANIC") == "PANIC"


def test_normalize_vcg_label_raises_on_unknown_with_remediation_hint():
    """v0.3 / CL-11: error must tell future maintainer where to extend the map."""
    with pytest.raises(ValueError, match="_VCG_LABEL_ALIASES"):
        normalize_vcg_label("RO_TIER_1")


def test_confusion_matrix_perfect_agreement_is_diagonal():
    truth = pd.Series(["NORMAL", "RISK_OFF", "EDR", "NORMAL"])
    pred = pd.Series(["NORMAL", "RISK_OFF", "EDR", "NORMAL"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)
    assert cm.loc["NORMAL", "NORMAL"] == 2
    assert cm.loc["RISK_OFF", "RISK_OFF"] == 1
    assert cm.loc["EDR", "EDR"] == 1


def test_confusion_matrix_raises_on_unknown_label():
    truth = pd.Series(["NORMAL", "RO_TIER_1"])
    pred = pd.Series(["NORMAL", "RISK_OFF"])
    with pytest.raises(ValueError, match="unknown"):
        build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)


def test_confusion_matrix_aligns_by_index_not_position():
    """v0.3 / CO-7: pure function MUST align by index, not by .values position."""
    truth = pd.Series(
        ["NORMAL", "RISK_OFF", "EDR"],
        index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
    )
    pred = pd.Series(
        ["EDR", "RISK_OFF", "NORMAL"],
        index=pd.to_datetime(["2020-01-03", "2020-01-02", "2020-01-01"]),
    )
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)
    assert cm.loc["NORMAL", "NORMAL"] == 1
    assert cm.loc["RISK_OFF", "RISK_OFF"] == 1
    assert cm.loc["EDR", "EDR"] == 1
    assert cm.values.sum() == 3


def test_confusion_matrix_partial_overlap_drops_unaligned_dates():
    truth = pd.Series(
        ["NORMAL", "RISK_OFF"],
        index=pd.to_datetime(["2020-01-01", "2020-01-02"]),
    )
    pred = pd.Series(
        ["NORMAL", "EDR"],
        index=pd.to_datetime(["2020-01-01", "2020-01-03"]),
    )
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)
    assert cm.values.sum() == 1
    assert cm.loc["NORMAL", "NORMAL"] == 1


# ---- Task 4.2: per-class P/R/F1 ----


def test_per_class_prf_simple_case():
    truth = pd.Series(["A", "A", "B", "B", "A"])
    pred = pd.Series(["A", "B", "B", "B", "A"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    out = per_class_prf(cm)
    assert out["A"]["precision"] == pytest.approx(1.0)
    assert out["A"]["recall"] == pytest.approx(2 / 3)
    assert out["A"]["f1"] == pytest.approx(0.8, abs=1e-6)


def test_per_class_prf_f1_zero_when_truth_exists_but_pred_empty():
    """Class with n_truth > 0 but n_pred = 0 must yield F1 = 0, NOT NaN."""
    truth = pd.Series(["A", "A", "B", "B"])
    pred = pd.Series(["A", "A", "A", "A"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    out = per_class_prf(cm)
    assert out["B"]["n_truth"] == 2
    assert out["B"]["n_pred"] == 0
    assert out["B"]["precision"] == pytest.approx(0.0)
    assert out["B"]["recall"] == pytest.approx(0.0)
    assert out["B"]["f1"] == pytest.approx(0.0)


def test_per_class_prf_nan_only_when_truth_is_zero():
    truth = pd.Series(["A", "B"])
    pred = pd.Series(["A", "B"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B", "C"])
    out = per_class_prf(cm)
    assert np.isnan(out["C"]["f1"])


# ---- Task 4.3: macro / weighted F1 + kappa ----


def test_macro_f1_skips_inconclusive_classes():
    per_class = {
        "A": {
            "f1": 0.6,
            "n_truth": 100,
            "n_pred": 80,
            "precision": 0.75,
            "recall": 0.6,
        },
        "B": {
            "f1": 0.8,
            "n_truth": 50,
            "n_pred": 40,
            "precision": 1.0,
            "recall": 0.8,
        },
        "C": {
            "f1": float("nan"),
            "n_truth": 5,
            "n_pred": 0,
            "precision": float("nan"),
            "recall": float("nan"),
        },
    }
    result = macro_f1_over_eligible(per_class, n_min_class_days=30)
    assert result["macro_f1"] == pytest.approx(0.7)
    assert sorted(result["eligible_classes"]) == ["A", "B"]
    assert result["ineligible_classes"] == ["C"]


def test_weighted_f1_requires_explicit_eligible_classes():
    """v0.3 / patch section 10: caller passes eligible_classes; do not guess."""
    per_class = {
        "A": {
            "f1": 0.6,
            "n_truth": 100,
            "n_pred": 80,
            "precision": 0.75,
            "recall": 0.6,
        },
        "B": {
            "f1": 0.8,
            "n_truth": 50,
            "n_pred": 40,
            "precision": 1.0,
            "recall": 0.8,
        },
        "C": {
            "f1": 0.0,
            "n_truth": 5,
            "n_pred": 0,
            "precision": 0.0,
            "recall": 0.0,
        },
    }
    wf1 = weighted_f1_over_eligible(per_class, eligible_classes=["A", "B"])
    assert wf1 == pytest.approx(100 / 150)


def test_cohens_kappa_perfect_agreement_is_one():
    truth = pd.Series(["A", "A", "B", "B"])
    pred = pd.Series(["A", "A", "B", "B"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    assert cohens_kappa(cm) == pytest.approx(1.0)


def test_cohens_kappa_random_chance_is_zero():
    truth = pd.Series(["A"] * 100 + ["B"] * 100)
    pred = pd.Series(["A"] * 50 + ["B"] * 50 + ["A"] * 50 + ["B"] * 50)
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    assert abs(cohens_kappa(cm)) < 0.01


# ---- Task 4.4: JSON sanitizer ----


def test_sanitize_for_json_replaces_nan_with_none():
    """v0.3 / CO-2: PostgreSQL JSONB doesn't accept NaN/inf tokens."""
    payload = {
        "f1": float("nan"),
        "precision": float("inf"),
        "nested": {"recall": -float("inf"), "ok": 0.5},
        "list": [float("nan"), 1.0, float("nan")],
        "string": "PANIC",
        "int": 42,
    }
    cleaned = sanitize_for_json(payload)
    assert cleaned["f1"] is None
    assert cleaned["precision"] is None
    assert cleaned["nested"]["recall"] is None
    assert cleaned["nested"]["ok"] == 0.5
    assert cleaned["list"] == [None, 1.0, None]
    assert cleaned["string"] == "PANIC"
    assert cleaned["int"] == 42


# ---- Task 5.1: three-state verdict ----


from uw_scan.cards.regime_classification_scoring import (  # noqa: E402
    classify_failure_mode,
    compute_verdict,
)

CORE = ["NORMAL", "SUPPRESSED", "EDR", "RISK_OFF"]


def _pc(f1, n_truth, n_pred=None):
    return {
        "f1": f1,
        "n_truth": n_truth,
        "n_pred": n_pred if n_pred is not None else n_truth,
        "precision": float("nan"),
        "recall": float("nan"),
    }


def test_verdict_inconclusive_when_any_core_class_under_min():
    per_class = {
        "NORMAL": _pc(0.7, 500),
        "SUPPRESSED": _pc(0.6, 100),
        "EDR": _pc(0.5, 20),  # < 30 -> inconclusive
        "RISK_OFF": _pc(0.5, 50),
        "PANIC": _pc(0.0, 5),
        "BOUNCE": _pc(0.0, 5),
    }
    v = compute_verdict(
        per_class,
        core_classes=CORE,
        n_min_class_days=30,
        k_min_core_eligible=4,
        macro_f1_pass=0.50,
    )
    assert v["overall"] == "INCONCLUSIVE"
    assert "EDR" in v["inconclusive_core_classes"]


def test_verdict_pass_when_all_core_eligible_and_macro_above_threshold():
    per_class = {
        "NORMAL": _pc(0.7, 500),
        "SUPPRESSED": _pc(0.6, 100),
        "EDR": _pc(0.5, 50),
        "RISK_OFF": _pc(0.5, 50),
        "PANIC": _pc(float("nan"), 5),
        "BOUNCE": _pc(float("nan"), 5),
    }
    v = compute_verdict(
        per_class,
        core_classes=CORE,
        n_min_class_days=30,
        k_min_core_eligible=4,
        macro_f1_pass=0.50,
    )
    assert v["overall"] == "PASS"


def test_verdict_fail_when_macro_below_threshold():
    per_class = {
        "NORMAL": _pc(0.4, 500),
        "SUPPRESSED": _pc(0.3, 100),
        "EDR": _pc(0.3, 50),
        "RISK_OFF": _pc(0.3, 50),
        "PANIC": _pc(float("nan"), 5),
        "BOUNCE": _pc(float("nan"), 5),
    }
    v = compute_verdict(
        per_class,
        core_classes=CORE,
        n_min_class_days=30,
        k_min_core_eligible=4,
        macro_f1_pass=0.50,
    )
    assert v["overall"] == "FAIL"


def test_rare_class_under_power_does_not_invalidate_headline():
    per_class = {
        "NORMAL": _pc(0.7, 500),
        "SUPPRESSED": _pc(0.6, 100),
        "EDR": _pc(0.5, 50),
        "RISK_OFF": _pc(0.5, 50),
        "PANIC": _pc(float("nan"), 5),
        "BOUNCE": _pc(float("nan"), 5),
    }
    v = compute_verdict(
        per_class,
        core_classes=CORE,
        n_min_class_days=30,
        k_min_core_eligible=4,
        macro_f1_pass=0.50,
    )
    assert v["overall"] == "PASS"
    assert "PANIC" in v["rare_inconclusive"]
    assert "BOUNCE" in v["rare_inconclusive"]


# ---- Task 5.2: failure-mode classifier ----


FAILURE_THRESHOLDS = {
    "PANIC_SUPPRESSION_RATIO": 0.2,
    "SPARSITY_RATIO": 0.25,
    "MISMATCH_CONCENTRATION": 0.6,
    "BENCH_RANGE": 0.15,
    "N_MIN_CLASS_DAYS": 30,
    "MACRO_F1_PASS": 0.5,
}


def test_failure_mode_adequate_v1_when_pass():
    verdict = {"overall": "PASS", "macro_f1": 0.7}
    per_class = {
        "PANIC": _pc(0.5, 50, n_pred=45),
        "NORMAL": _pc(0.7, 500, n_pred=500),
        "EDR": _pc(0.6, 100, n_pred=90),
        "RISK_OFF": _pc(0.6, 100, n_pred=95),
    }
    out = classify_failure_mode(
        verdict,
        per_class,
        cm=pd.DataFrame(),
        thresholds=FAILURE_THRESHOLDS,
        per_universe_macro_f1=None,
    )
    assert out["primary"] == "adequate_v1"


def test_failure_mode_panic_suppression():
    verdict = {"overall": "FAIL", "macro_f1": 0.3}
    per_class = {
        "PANIC": _pc(0.0, 50, n_pred=2),
        "NORMAL": _pc(0.4, 500, n_pred=500),
        "EDR": _pc(0.3, 100, n_pred=90),
        "RISK_OFF": _pc(0.3, 100, n_pred=95),
    }
    out = classify_failure_mode(
        verdict,
        per_class,
        cm=pd.DataFrame(),
        thresholds=FAILURE_THRESHOLDS,
        per_universe_macro_f1=None,
    )
    assert out["primary"] == "panic_suppression"


def test_failure_mode_underpowered_test_for_inconclusive():
    """v0.3 / CL-2: INCONCLUSIVE must emit a meaningful primary mode."""
    verdict = {
        "overall": "INCONCLUSIVE",
        "macro_f1": None,
        "reason": "core_class_under_min",
    }
    per_class = {
        "NORMAL": _pc(0.5, 500, n_pred=400),
        "SUPPRESSED": _pc(0.5, 100, n_pred=80),
        "EDR": _pc(float("nan"), 10),  # under N_MIN
        "RISK_OFF": _pc(0.5, 50, n_pred=45),
    }
    out = classify_failure_mode(
        verdict,
        per_class,
        cm=pd.DataFrame(),
        thresholds=FAILURE_THRESHOLDS,
        per_universe_macro_f1=None,
    )
    assert out["primary"] == "underpowered_test"


def test_failure_mode_label_mismatch_not_triggered_on_empty_cm():
    """v0.3 / CO-8: label_mismatch must NOT trigger on empty cm."""
    verdict = {"overall": "FAIL", "macro_f1": 0.4}
    per_class = {
        "PANIC": _pc(0.5, 50, n_pred=45),
        "NORMAL": _pc(0.4, 500, n_pred=480),
        "EDR": _pc(0.4, 100, n_pred=95),
        "RISK_OFF": _pc(0.4, 100, n_pred=98),
    }
    out = classify_failure_mode(
        verdict,
        per_class,
        cm=pd.DataFrame(),
        thresholds=FAILURE_THRESHOLDS,
        per_universe_macro_f1=None,
    )
    assert "label_mismatch" not in out["secondary_modes"]
    assert out["primary"] != "label_mismatch"


def test_failure_mode_benchmark_coverage_not_evaluable_when_no_universe_data():
    verdict = {"overall": "FAIL", "macro_f1": 0.4}
    per_class = {
        "PANIC": _pc(0.5, 50, n_pred=45),
        "NORMAL": _pc(0.4, 500, n_pred=480),
        "EDR": _pc(0.4, 100, n_pred=95),
        "RISK_OFF": _pc(0.4, 100, n_pred=98),
    }
    out = classify_failure_mode(
        verdict,
        per_class,
        cm=pd.DataFrame(),
        thresholds=FAILURE_THRESHOLDS,
        per_universe_macro_f1=None,
    )
    assert "benchmark_coverage" in out["not_evaluable"]
