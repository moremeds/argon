"""Scoring + verdict + failure-mode classification for VCG regime accuracy.

All functions pure (no DB). Strict label normalization — unknown labels raise
ValueError rather than silently being dropped (spec section 12).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_VCG_LABEL_ALIASES = {
    "NORMAL": "NORMAL",
    "normal": "NORMAL",
    "Normal": "NORMAL",
    "SUPPRESSED": "SUPPRESSED",
    "suppressed": "SUPPRESSED",
    "Suppressed": "SUPPRESSED",
    "EDR": "EDR",
    "edr": "EDR",
    "RISK_OFF": "RISK_OFF",
    "risk_off": "RISK_OFF",
    "RISKOFF": "RISK_OFF",
    "risk-off": "RISK_OFF",
    "RO": "RISK_OFF",
    "PANIC": "PANIC",
    "panic": "PANIC",
    "Panic": "PANIC",
    "BOUNCE": "BOUNCE",
    "bounce": "BOUNCE",
    "Bounce": "BOUNCE",
    # VCG-specific yellow-light state (elevated VCG_adj above trigger but not
    # yet hitting RO/EDR/BOUNCE/PANIC). The Level-1 taxonomy has no exact
    # "elevated but not stressed" cell, so map WATCH -> NORMAL: classification
    # treats it as VCG asserting non-stress. Decision recorded in the
    # baseline report's executive summary.
    "WATCH": "NORMAL",
    "watch": "NORMAL",
    "Watch": "NORMAL",
}


def normalize_vcg_label(raw: str) -> str:
    """Canonicalize a VCG label string. Raises on unknown (v0.3 / CL-11)."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        raise ValueError(f"VCG label is null/NaN: {raw!r}")
    s = str(raw).strip()
    if s in _VCG_LABEL_ALIASES:
        return _VCG_LABEL_ALIASES[s]
    raise ValueError(
        f"unknown VCG label: {raw!r}. "
        f"If VCG emits new labels, extend _VCG_LABEL_ALIASES in "
        f"src/uw_scan/cards/regime_classification_scoring.py"
    )


def build_confusion_matrix(
    *, truth: pd.Series, pred: pd.Series, classes: list[str]
) -> pd.DataFrame:
    """Confusion matrix: rows = truth, cols = pred.

    v0.3 / CO-7: aligns by INDEX (pd.concat axis=1), not by .values position.
    Raises on unknown labels (no silent drops).
    """
    df = pd.concat(
        [
            truth.rename("truth"),
            pred.rename("pred"),
        ],
        axis=1,
    ).dropna()
    classes_set = set(classes)
    unknown_truth = set(df["truth"].unique()) - classes_set
    unknown_pred = set(df["pred"].unique()) - classes_set
    if unknown_truth or unknown_pred:
        raise ValueError(
            f"build_confusion_matrix: unknown labels — "
            f"truth={sorted(unknown_truth)} pred={sorted(unknown_pred)}"
        )
    cm = pd.DataFrame(0, index=classes, columns=classes, dtype=int)
    for _, row in df.iterrows():
        cm.loc[row["truth"], row["pred"]] += 1
    return cm


def per_class_prf(cm: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-class precision, recall, F1 from a confusion matrix.

    Semantics:
        n_truth == 0          -> F1 = NaN (class fundamentally absent)
        n_truth > 0, n_pred=0 -> F1 = 0.0 (real miss, not undefined)
        otherwise             -> standard P/R/F1
    """
    out: dict[str, dict[str, float]] = {}
    for c in cm.index:
        tp = float(cm.loc[c, c])
        fp = float(cm.loc[:, c].sum() - tp)
        fn = float(cm.loc[c, :].sum() - tp)
        n_truth = tp + fn
        n_pred = tp + fp

        if n_truth == 0:
            precision = float("nan")
            recall = float("nan")
            f1 = float("nan")
        elif n_pred == 0:
            precision = 0.0
            recall = 0.0
            f1 = 0.0
        else:
            precision = tp / n_pred
            recall = tp / n_truth
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )

        out[str(c)] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "n_truth": int(n_truth),
            "n_pred": int(n_pred),
        }
    return out


def macro_f1_over_eligible(
    per_class: dict[str, dict[str, float]], *, n_min_class_days: int
) -> dict:
    """Macro-F1 across classes with n_truth >= n_min_class_days and non-NaN F1."""
    eligible: list[str] = []
    ineligible: list[str] = []
    for c, m in per_class.items():
        if m["n_truth"] >= n_min_class_days and not np.isnan(m["f1"]):
            eligible.append(c)
        else:
            ineligible.append(c)
    if not eligible:
        return {
            "macro_f1": float("nan"),
            "eligible_classes": [],
            "ineligible_classes": ineligible,
        }
    macro = float(np.mean([per_class[c]["f1"] for c in eligible]))
    return {
        "macro_f1": macro,
        "eligible_classes": eligible,
        "ineligible_classes": ineligible,
    }


def weighted_f1_over_eligible(
    per_class: dict[str, dict[str, float]], *, eligible_classes: list[str]
) -> float:
    """F1 weighted by truth prevalence — over explicit class set (no guessing)."""
    total_n = sum(per_class[c]["n_truth"] for c in eligible_classes)
    if total_n == 0:
        return float("nan")
    weighted = sum(
        per_class[c]["f1"] * per_class[c]["n_truth"]
        for c in eligible_classes
        if not np.isnan(per_class[c]["f1"])
    )
    return float(weighted / total_n)


def cohens_kappa(cm: pd.DataFrame) -> float:
    """Cohen's kappa — chance-adjusted multi-class agreement."""
    n = float(cm.values.sum())
    if n == 0:
        return float("nan")
    p_o = float(np.diag(cm.values).sum()) / n
    row_marg = cm.sum(axis=1).values / n
    col_marg = cm.sum(axis=0).values / n
    p_e = float(np.sum(row_marg * col_marg))
    if abs(1.0 - p_e) < 1e-12:
        return float("nan")
    return (p_o - p_e) / (1.0 - p_e)


def sanitize_for_json(value):
    """Recursively replace NaN / +/- inf with None for JSONB compatibility (CO-2)."""
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_json(v) for v in value]
    return value


CORE_CLASSES = ("NORMAL", "SUPPRESSED", "EDR", "RISK_OFF")


def compute_verdict(
    per_class: dict[str, dict[str, float]],
    *,
    core_classes: list[str],
    n_min_class_days: int,
    k_min_core_eligible: int,
    macro_f1_pass: float,
) -> dict:
    """Three-state verdict per spec section 8 (eligible/core-class model)."""
    inconclusive_core: list[str] = []
    eligible_core: list[str] = []
    rare_inconclusive: list[str] = []

    for c, m in per_class.items():
        is_eligible = m["n_truth"] >= n_min_class_days and not np.isnan(m["f1"])
        if c in core_classes:
            if is_eligible:
                eligible_core.append(c)
            else:
                inconclusive_core.append(c)
        else:
            if not is_eligible:
                rare_inconclusive.append(c)

    if inconclusive_core or len(eligible_core) < k_min_core_eligible:
        return {
            "overall": "INCONCLUSIVE",
            "reason": (
                "core_class_under_min"
                if inconclusive_core
                else "fewer_than_k_core_eligible"
            ),
            "inconclusive_core_classes": inconclusive_core,
            "eligible_core_classes": eligible_core,
            "rare_inconclusive": rare_inconclusive,
            "macro_f1": None,
        }

    all_eligible = list(eligible_core)
    for c in per_class:
        if c not in core_classes and c not in rare_inconclusive:
            all_eligible.append(c)
    macro = float(np.mean([per_class[c]["f1"] for c in all_eligible]))

    return {
        "overall": "PASS" if macro >= macro_f1_pass else "FAIL",
        "reason": None,
        "inconclusive_core_classes": inconclusive_core,
        "eligible_core_classes": eligible_core,
        "rare_inconclusive": rare_inconclusive,
        "macro_f1": macro,
        "all_eligible_classes": all_eligible,
    }


def classify_failure_mode(
    verdict: dict,
    per_class: dict[str, dict[str, float]],
    *,
    cm: pd.DataFrame,
    thresholds: dict,
    per_universe_macro_f1: dict | None,
) -> dict:
    """v0.3 failure-mode classifier per spec section 9.

    Modes (precedence order):
        panic_suppression > signal_sparsity > underpowered_test >
        label_mismatch > benchmark_coverage > adequate_v1

    v0.3 additions:
    - underpowered_test (CL-2): INCONCLUSIVE -> meaningful mode
    - label_mismatch (CO-8): guarded against empty cm / zero disagreement
    - benchmark_coverage (CL-1): always not_evaluable until per-universe
      scoring lands in follow-up PR
    """
    triggered: list[str] = []
    not_evaluable: list[str] = []

    panic_suppression_ratio = thresholds["PANIC_SUPPRESSION_RATIO"]
    sparsity_ratio = thresholds["SPARSITY_RATIO"]
    bench_range = thresholds["BENCH_RANGE"]
    n_min = thresholds["N_MIN_CLASS_DAYS"]
    mismatch_conc = thresholds["MISMATCH_CONCENTRATION"]

    panic = per_class.get("PANIC")
    if panic is not None and panic["n_truth"] >= n_min:
        if panic["n_pred"] < panic_suppression_ratio * panic["n_truth"]:
            triggered.append("panic_suppression")

    for c in CORE_CLASSES:
        m = per_class.get(c)
        if m is None or m["n_truth"] < n_min:
            continue
        if m["n_pred"] < sparsity_ratio * m["n_truth"]:
            triggered.append("signal_sparsity")
            break

    if verdict["overall"] == "INCONCLUSIVE":
        triggered.append("underpowered_test")

    if (
        verdict["overall"] == "FAIL"
        and "signal_sparsity" not in triggered
        and not cm.empty
    ):
        all_dense = all(
            per_class[c]["n_pred"] >= sparsity_ratio * per_class[c]["n_truth"]
            for c in CORE_CLASSES
            if per_class.get(c) and per_class[c]["n_truth"] >= n_min
        )
        if all_dense:
            off_diag: list[tuple[float, str, str]] = []
            for i in cm.index:
                for j in cm.columns:
                    if i != j:
                        off_diag.append((float(cm.loc[i, j]), str(i), str(j)))
            off_diag.sort(reverse=True)
            total = sum(v for v, _, _ in off_diag)
            if total > 0:
                top2 = sum(v for v, _, _ in off_diag[:2])
                if top2 / total >= mismatch_conc:
                    triggered.append("label_mismatch")

    if per_universe_macro_f1 is None:
        not_evaluable.append("benchmark_coverage")
    elif len(per_universe_macro_f1) >= 2:
        values = list(per_universe_macro_f1.values())
        if max(values) - min(values) > bench_range:
            triggered.append("benchmark_coverage")

    precedence = [
        "panic_suppression",
        "signal_sparsity",
        "underpowered_test",
        "label_mismatch",
        "benchmark_coverage",
    ]
    primary = next((m for m in precedence if m in triggered), None)
    if primary is None and verdict["overall"] == "PASS":
        primary = "adequate_v1"
    if primary is None:
        primary = "unknown"
    secondary = [m for m in triggered if m != primary]

    return {
        "primary": primary,
        "secondary_modes": secondary,
        "not_evaluable": not_evaluable,
    }
