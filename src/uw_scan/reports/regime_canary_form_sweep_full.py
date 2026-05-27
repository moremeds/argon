"""Canary form-sweep-full: candidate discovery over all 4 score forms.

This module owns the focused implementation of `--form-sweep-full`. The
script `scripts/backtest_canary.py` exposes only a thin wrapper that
delegates here through the `CanaryFormSweepDeps` container, so the
script stays under its 1,000-line split threshold.

Candidate discovery only — no winning form is declared, no calibration
file is written, no production surface is touched. See
docs/superpowers/specs/2026-05-27-canary-form-sweep-full-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CanaryFormSweepDeps:
    """Dependency container — receives the script's helpers without
    introducing a back-import from the package into the script."""

    compute_canary_series: Callable[..., dict]
    aucs_for_rows: Callable[[list[dict]], dict[str, dict[str, float]]]
    band_counts: Callable[[list[dict]], dict[str, int]]
    block_bootstrap_auc_ci: Callable[..., tuple[float, float]]
    clean_nans: Callable[[Any], Any]
    entry_lagged_label: Callable[[list[dict], int, float], list]
    auc: Callable[[list[float], list], float]
    label_specs: list[tuple[str, int, float]]
    composite_version: int


def _within_band_aucs(
    rows: list[dict], deps: CanaryFormSweepDeps
) -> dict[str, dict[str, float]]:
    """AUC of composite score vs forward labels, restricted to each band.

    Labels are computed ONCE over the full row series (so the last 60 days
    don't drop out of every band-subset), then filtered by band membership.
    Returns NaN for bands with <2 distinct labels in the subset.

    This preserves the "compute labels once, filter by index" invariant
    from cmd_robustness — see _auc_for_indices around line 979.
    """
    out: dict[str, dict[str, float]] = {
        b: {} for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    }
    if not rows:
        return out
    composite_scores = [r["score"] for r in rows]
    for name, h, thr in deps.label_specs:
        labels_full = deps.entry_lagged_label(rows, h, thr)
        for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
            idxs = [i for i, r in enumerate(rows) if r["band"] == band]
            band_scores = [composite_scores[i] for i in idxs]
            band_labels = [labels_full[i] for i in idxs]
            out[band][name] = deps.auc(band_scores, band_labels)
    return out
