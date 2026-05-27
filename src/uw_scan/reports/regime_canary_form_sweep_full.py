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

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

log = logging.getLogger(__name__)

CANONICAL_FORMS = ("linear", "convex", "concave", "sigmoid")


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


def run_form_sweep_full(conn, *, schema: str, deps: CanaryFormSweepDeps) -> None:
    """Full-history score-form sweep against canary_snapshots range.

    Candidate discovery only. DO NOT:
      - declare a winning form
      - write to canary-calibration-v1.json
      - set summary.is_winning_form=True
      - read or modify the OOS gate's LAST_KNOWN_AUC_* constants
    """
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.reports.regime_canary_backtest_report import (
        render_canary_form_sweep_compare,
    )
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    bt_repo = RegimeBacktestRepository(conn, schema=schema)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT MIN(data_date), MAX(data_date), COUNT(*) "
            f"FROM {schema}.canary_snapshots"
        )
        snap_min, snap_max, snap_count = cur.fetchone()
    if not snap_min:
        raise RuntimeError("canary_snapshots is empty — cannot run form-sweep-full")
    log.info(
        "form_sweep_full: snap range %s → %s (%d rows)",
        snap_min,
        snap_max,
        snap_count,
    )

    batch_id = str(uuid4())
    generated_at = datetime.now(timezone.utc).isoformat()

    # Phase 1: compute eval rows for all four forms in memory. NO DB writes.
    per_form: dict[str, dict] = {}
    for form in CANONICAL_FORMS:
        series = deps.compute_canary_series(
            conn,
            cal,
            form=form,
            start=snap_min,
            end=snap_max,
            schema=schema,
        )
        per_form[form] = {"eval_rows": series["eval_rows"]}

    # Phase 2: compute summaries in memory. Still NO DB writes.
    for form, payload in per_form.items():
        eval_rows = payload["eval_rows"]
        aucs = deps.aucs_for_rows(eval_rows)
        composite_scores = [r["score"] for r in eval_rows]
        auc_ci95: dict[str, list[float]] = {}
        for name, h, thr in deps.label_specs:
            labels = deps.entry_lagged_label(eval_rows, h, thr)
            lo, hi = deps.block_bootstrap_auc_ci(composite_scores, labels)
            auc_ci95[name] = [lo, hi]
        band_dist = deps.band_counts(eval_rows)
        within_band = _within_band_aucs(eval_rows, deps)
        vol_only_gap = {
            name: (
                aucs["vol_only"].get(name, float("nan"))
                - aucs["composite"].get(name, float("nan"))
            )
            for name, _, _ in deps.label_specs
        }
        payload.update(
            {
                "aucs": aucs,
                "auc_ci95": auc_ci95,
                "band_distribution": band_dist,
                "within_band_aucs": within_band,
                "vol_only_gap": vol_only_gap,
                "n_days": len(eval_rows),
            }
        )

    # Phase 3: persist. On ANY exception, rollback + delete-by-batch_id;
    # the original exception is preserved (Python's last-raise-wins would
    # otherwise mask the root cause with a cleanup-time error).
    try:
        for form, payload in per_form.items():
            eval_rows = payload["eval_rows"]
            if not eval_rows:
                raise RuntimeError(f"form_sweep_full: form={form} produced 0 eval rows")
            summary = deps.clean_nans(
                {
                    "is_winning_form": False,
                    "score_form": form,
                    "phase": "form_sweep_full",
                    "source": "form_sweep_full",
                    "batch_id": batch_id,
                    "generated_at": generated_at,
                    "n_days": payload["n_days"],
                    "aucs": payload["aucs"],
                    "auc_ci95": payload["auc_ci95"],
                    "band_distribution": payload["band_distribution"],
                    "within_band_aucs": payload["within_band_aucs"],
                    "vol_only_gap": payload["vol_only_gap"],
                }
            )
            params = {
                "score_form": form,
                "phase": "form_sweep_full",
                "batch_id": batch_id,
                "purpose": "candidate_discovery_not_validation",
                "min_aligned_bars": 350,
                "window_semantics": "warmup_requirement_not_eval_window",
            }
            run_id = bt_repo.insert_run(
                indicator="canary",
                composite_version=str(deps.composite_version),
                start_date=eval_rows[0]["date"],
                end_date=eval_rows[-1]["date"],
                window_days=350,
                n_days=payload["n_days"],
                params=params,
                summary=summary,
                run_scope="research",
            )
            bt_repo.bulk_insert_daily(
                run_id,
                [
                    {
                        "trade_date": r["date"],
                        "score": r["score"],
                        "level": r["band"],
                        "payload": {
                            "raw_score": r["score"],
                            "tactical": r["tactical"],
                            "structural": r["structural"],
                            "speed": r["speed"],
                            "warning_state": r["warning_state"],
                        },
                    }
                    for r in eval_rows
                ],
            )
            bt_repo.mark_run_completed(run_id)
    except Exception as original:
        # Real Postgres errors leave the transaction in InFailedSqlTransaction;
        # rollback() must run BEFORE the DELETE, or the delete itself errors.
        try:
            conn.rollback()
        except Exception as rollback_err:
            log.exception(
                "rollback failed during form_sweep_full cleanup: %s",
                rollback_err,
            )
        try:
            bt_repo.delete_runs_by_batch_id(batch_id)
        except Exception as cleanup_err:
            log.exception(
                "delete_runs_by_batch_id(%s) failed during cleanup: %s",
                batch_id,
                cleanup_err,
            )
        raise original

    # Phase 4: reload, validate, render.
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, params, summary, start_date, end_date, "
            f"       composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s "
            f"  AND run_scope = 'research' "
            f"  AND completed_at IS NOT NULL "
            f"ORDER BY params->>'score_form'",
            (batch_id,),
        )
        run_dicts = [
            {
                "id": r[0],
                "params": r[1],
                "summary": r[2],
                "start_date": r[3],
                "end_date": r[4],
                "composite_version": r[5],
                "run_scope": r[6],
            }
            for r in cur.fetchall()
        ]
    if len(run_dicts) != 4:
        raise RuntimeError(
            f"form_sweep_full: expected 4 persisted rows, got {len(run_dicts)}"
        )
    print(render_canary_form_sweep_compare(run_dicts))
