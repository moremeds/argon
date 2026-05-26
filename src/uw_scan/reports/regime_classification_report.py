"""Deterministic Markdown renderer for VCG regime-classification reports.

Same inputs -> byte-identical output. No wall-clock timestamps in body.
"""

from __future__ import annotations

import pandas as pd

CONSTRUCT_VALIDITY = (
    "This classification score measures descriptive agreement with an "
    "externally defined market-state taxonomy. It is not an alpha test, a "
    "return-prediction test, or a trading-signal validation. Because VCG and "
    "the Level-1 taxonomy both use volatility/credit information, the report "
    "MUST frame the result as construct validity, not independent predictive "
    "evidence."
)


def _confusion_matrix_to_markdown(cm: pd.DataFrame) -> str:
    """Render a confusion-matrix DataFrame as a Markdown table.

    Hand-rolled to avoid the optional pandas `tabulate` dependency. The
    output is byte-stable for byte-identical replay.
    """
    cols = [""] + [str(c) for c in cm.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] + ["---:" for _ in cm.columns]) + " |"
    rows = [header, sep]
    for idx in cm.index:
        cells = [str(idx)] + [str(int(cm.loc[idx, c])) for c in cm.columns]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def render_report(
    *,
    run_id: int,
    label_version: int,
    eval_start: str,
    eval_end: str,
    n_days: int,
    verdict: dict,
    failure_mode: dict,
    per_class: dict[str, dict[str, float]],
    cm_overall: pd.DataFrame,
    cm_by_period: dict[str, pd.DataFrame],
    weighted_f1: float,
    kappa: float,
    named_crisis_overlay: list[dict],
    vcg_source: dict,
    data_vintages: list[dict] | None = None,
) -> str:
    """Render the classification baseline report as deterministic Markdown."""
    lines: list[str] = []
    lines.append(f"# VCG v1 Regime-Classification Baseline — run_id={run_id}")
    lines.append("")
    lines.append("## Executive summary — construct validity framing")
    lines.append("")
    lines.append(f"> {CONSTRUCT_VALIDITY}")
    lines.append("")
    lines.append(f"**Verdict:** {verdict['overall']}")
    if verdict.get("macro_f1") is not None:
        lines.append(f"**Macro-F1 (eligible classes):** {verdict['macro_f1']:.4f}")
    lines.append(f"**Cohen's kappa:** {kappa:.4f}")
    lines.append(f"**Weighted-F1:** {weighted_f1:.4f}")
    lines.append(f"**Primary failure mode:** `{failure_mode['primary']}`")
    if failure_mode["secondary_modes"]:
        lines.append(
            f"**Secondary modes:** `{', '.join(failure_mode['secondary_modes'])}`"
        )
    if failure_mode["not_evaluable"]:
        lines.append(
            f"**Not-evaluable modes:** `{', '.join(failure_mode['not_evaluable'])}`"
        )
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(f"- Eval window: {eval_start} -> {eval_end} ({n_days} trading days)")
    lines.append(f"- Label contract version: {label_version}")
    lines.append(
        f"- VCG source: run_id={vcg_source['run_id']}, "
        f"composite_version={vcg_source['composite_version']}, "
        f"credit_proxy={vcg_source.get('credit_proxy', '')}"
    )
    lines.append("- No train/test split is claimed. Descriptive agreement only.")
    lines.append("")

    # v0.3 / CL-6: Data vintages disclosure
    if data_vintages:
        lines.append("### Data vintages")
        lines.append("")
        lines.append("| Component | Vintage | Lag | Interpretation |")
        lines.append("|---|---|---|---|")
        for v in data_vintages:
            lines.append(
                f"| {v['component']} | {v['vintage']} | {v['lag']} | "
                f"{v['interpretation']} |"
            )
        lines.append("")

    lines.append("## Verdict details")
    lines.append("")
    lines.append(f"- Reason: `{verdict.get('reason') or 'n/a'}`")
    lines.append(
        f"- Eligible core classes: `{verdict.get('eligible_core_classes', [])}`"
    )
    lines.append(
        f"- Inconclusive core classes: `{verdict.get('inconclusive_core_classes', [])}`"
    )
    lines.append(
        f"- Rare classes inconclusive: `{verdict.get('rare_inconclusive', [])}`"
    )
    lines.append("")

    if per_class:
        lines.append("## Per-class metrics")
        lines.append("")
        lines.append("| Class | n_truth | n_pred | precision | recall | F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for c in sorted(per_class):
            m = per_class[c]
            precision = m["precision"]
            recall = m["recall"]
            f1 = m["f1"]
            p_str = "nan" if pd.isna(precision) else f"{precision:.4f}"
            r_str = "nan" if pd.isna(recall) else f"{recall:.4f}"
            f1_str = "nan" if pd.isna(f1) else f"{f1:.4f}"
            lines.append(
                f"| {c} | {m['n_truth']} | {m['n_pred']} | "
                f"{p_str} | {r_str} | {f1_str} |"
            )
        lines.append("")

    if not cm_overall.empty:
        lines.append("## Confusion matrix (overall)")
        lines.append("")
        lines.append("Rows = ground-truth, columns = VCG prediction.")
        lines.append("")
        lines.append(_confusion_matrix_to_markdown(cm_overall))
        lines.append("")

    if cm_by_period:
        lines.append("## Confusion matrix by period")
        lines.append("")
        for period in sorted(cm_by_period):
            lines.append(f"### {period}")
            lines.append("")
            lines.append(_confusion_matrix_to_markdown(cm_by_period[period]))
            lines.append("")

    if named_crisis_overlay:
        lines.append("## Named-crisis sanity overlay (use_for_headline: false)")
        lines.append("")
        lines.append(
            "| Crisis | Window | n_days | VCG distribution | Truth distribution |"
        )
        lines.append("|---|---|---:|---|---|")
        for entry in named_crisis_overlay:
            vcg_dist = ", ".join(
                f"{k}={v}" for k, v in sorted(entry["vcg_distribution"].items())
            )
            truth_dist = ", ".join(
                f"{k}={v}" for k, v in sorted(entry["truth_distribution"].items())
            )
            lines.append(
                f"| {entry['name']} | {entry['start']}->{entry['end']} | "
                f"{entry['n_days']} | {vcg_dist} | {truth_dist} |"
            )
        lines.append("")

    lines.append("---")
    lines.append(
        "Reproducibility: replay via `--render-run-id <N>` reads persisted "
        "markdown bytes from summary.extras.classification.report_md "
        "(v0.3 / CR-1)."
    )
    return "\n".join(lines) + "\n"
