"""Canary v1-vs-v2 evidence assembly + comparison renderer + standalone CLI.

Three layers:
  1. _assemble_flip_gate_evidence(conn, *, schema) — DB queries (impure).
     Reads v1 walk-forward production runs, v2 walk-forward research runs
     (sharing a batch_id), v2 robustness run, v1/v2 snapshot-based band
     distributions and CCA event states. Computes v1 + v2 full-history
     AUCs via _compute_canary_series so the row dicts contain the `spx`
     field _aucs_for_rows needs (canary_snapshots rows do not).

  2. render_canary_v1_v2_compare(ev) -> str — pure function on
     FlipGateEvidence. Evaluates AC-F1..F6 and emits a markdown report
     with SHIP/STOP verdict + locked PR-2 footer.

  3. main() — standalone CLI for re-rendering an already-persisted bundle.

The thin dispatcher in `scripts/backtest_canary.py` calls
assemble_and_render_canary_v1_v2_compare() and prints the result.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date as _date
from io import StringIO
from pathlib import Path

import psycopg

from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
V1_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v1.json"
V2_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"

CANONICAL_WINDOWS = ("WF-1", "WF-2", "WF-3", "WF-4", "WF-5", "WF-6")
CCA_EVENT_DATES = ("2011-08-08", "2015-08-24", "2018-02-05", "2020-03-09")

AC_F1_60D_BAR = 0.634
AC_F2_20D_BAR = 0.622
AC_F2_5D_BAR = 0.615
AC_F4_PER_WINDOW_TOLERANCE = -0.02
AC_F5_WATCH_PCT_BAR = 44.3


@dataclass(frozen=True)
class FlipGateEvidence:
    """Pre-assembled bundle that lets the renderer evaluate every AC-Fn locally."""

    v1_runs: list[dict]
    v2_runs: list[dict]
    v2_robustness_run: dict
    v1_full_history_aucs: dict[str, float]
    v2_full_history_aucs: dict[str, float]
    v1_band_distribution: dict[str, float]
    v2_band_distribution: dict[str, float]
    v2_cca_event_states: dict[str, bool]
    oos_gate_passed: bool
    v1_payload_hash_golden_passed: bool


def _validate_evidence(ev: FlipGateEvidence) -> None:
    """Raise ValueError if any structural invariant is violated."""
    if len(ev.v1_runs) != 6:
        raise ValueError(f"v1_runs must have 6 runs, got {len(ev.v1_runs)}")
    if len(ev.v2_runs) != 6:
        raise ValueError(f"v2_runs must have 6 runs, got {len(ev.v2_runs)}")
    for r in ev.v1_runs:
        if str(r.get("composite_version")) != "1":
            raise ValueError(
                f"v1_runs composite_version={r.get('composite_version')!r}"
            )
        if r.get("run_scope") != "production":
            raise ValueError(f"v1_runs run_scope={r.get('run_scope')!r}")
    for r in ev.v2_runs:
        if str(r.get("composite_version")) != "2":
            raise ValueError(
                f"v2_runs composite_version={r.get('composite_version')!r}"
            )
        if r.get("run_scope") != "research":
            raise ValueError(f"v2_runs run_scope={r.get('run_scope')!r}")
    v2_batch_ids = {r["params"].get("batch_id") for r in ev.v2_runs}
    if len(v2_batch_ids) != 1:
        raise ValueError(f"v2_runs must share batch_id, got {v2_batch_ids}")
    if v2_batch_ids == {None}:
        raise ValueError("v2_runs batch_id must not be None")
    v1_window_ids = {r["params"].get("window_id") for r in ev.v1_runs}
    v2_window_ids = {r["params"].get("window_id") for r in ev.v2_runs}
    if v1_window_ids != set(CANONICAL_WINDOWS):
        raise ValueError(f"v1_runs window_ids != WF-1..WF-6, got {v1_window_ids}")
    if v2_window_ids != set(CANONICAL_WINDOWS):
        raise ValueError(f"v2_runs window_ids != WF-1..WF-6, got {v2_window_ids}")
    if str(ev.v2_robustness_run.get("composite_version")) != "2":
        raise ValueError("v2_robustness_run composite_version must be 2")
    if ev.v2_robustness_run.get("run_scope") != "research":
        raise ValueError("v2_robustness_run run_scope must be research")
    for d in CCA_EVENT_DATES:
        if d not in ev.v2_cca_event_states:
            raise ValueError(f"v2_cca_event_states missing {d}")


def _eval_ac_f1(ev: FlipGateEvidence) -> tuple[bool, str]:
    auc = ev.v2_full_history_aucs.get("up60d_10pct")
    v1_ref = ev.v1_full_history_aucs.get("up60d_10pct")
    if auc is None or v1_ref is None:
        return False, "AC-F1: v2 60d AUC unavailable"
    passed = auc >= AC_F1_60D_BAR
    delta = auc - v1_ref
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F1 [{verdict}]: v2 60d AUC = {auc:.4f} "
        f"(bar >= {AC_F1_60D_BAR}; v1 ref {v1_ref:.4f}, delta {delta:+.4f})"
    )


def _eval_ac_f2(ev: FlipGateEvidence) -> tuple[bool, str]:
    auc_20 = ev.v2_full_history_aucs.get("up20d_5pct")
    auc_5 = ev.v2_full_history_aucs.get("up5d_2pct")
    if auc_20 is None or auc_5 is None:
        return False, "AC-F2: v2 short-horizon AUCs unavailable"
    p20 = auc_20 >= AC_F2_20D_BAR
    p5 = auc_5 >= AC_F2_5D_BAR
    passed = p20 and p5
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F2 [{verdict}]: v2 20d AUC = {auc_20:.4f} "
        f"(bar >= {AC_F2_20D_BAR}, {'PASS' if p20 else 'FAIL'}), "
        f"v2 5d AUC = {auc_5:.4f} "
        f"(bar >= {AC_F2_5D_BAR}, {'PASS' if p5 else 'FAIL'})"
    )


def _eval_ac_f3(ev: FlipGateEvidence) -> tuple[bool, str]:
    missed = [d for d, fired in ev.v2_cca_event_states.items() if not fired]
    passed = len(missed) == 0
    verdict = "PASS" if passed else "FAIL"
    detail = f"missed: {missed}" if missed else "all 4 CCA dates fired"
    return passed, f"AC-F3 [{verdict}]: speed.confirmed_canary_active — {detail}"


def _eval_ac_f4(ev: FlipGateEvidence) -> tuple[bool, str]:
    v1_by_wid = {r["params"]["window_id"]: r for r in ev.v1_runs}
    v2_by_wid = {r["params"]["window_id"]: r for r in ev.v2_runs}
    failures = []
    for wid in CANONICAL_WINDOWS:
        v1_auc = v1_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        v2_auc = v2_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        if v1_auc is None or v2_auc is None:
            failures.append(f"{wid}: AUC missing")
            continue
        delta = v2_auc - v1_auc
        if delta < AC_F4_PER_WINDOW_TOLERANCE:
            failures.append(
                f"{wid}: v2={v2_auc:.4f} v1={v1_auc:.4f} delta={delta:+.4f}"
            )
    passed = not failures
    verdict = "PASS" if passed else "FAIL"
    detail = "all 6 windows within tolerance" if passed else f"failed: {failures}"
    return passed, (
        f"AC-F4 [{verdict}]: per-window 60d AUC delta "
        f">= {AC_F4_PER_WINDOW_TOLERANCE} — {detail}"
    )


def _eval_ac_f5(ev: FlipGateEvidence) -> tuple[bool, str]:
    watch = ev.v2_band_distribution.get("WATCH")
    if watch is None:
        return False, "AC-F5: v2 WATCH% unavailable"
    passed = watch <= AC_F5_WATCH_PCT_BAR
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F5 [{verdict}]: v2 WATCH% = {watch:.1f}% (bar <= {AC_F5_WATCH_PCT_BAR}%)"
    )


def _eval_ac_f6(ev: FlipGateEvidence) -> tuple[bool, str]:
    passed = ev.oos_gate_passed and ev.v1_payload_hash_golden_passed
    verdict = "PASS" if passed else "FAIL"
    parts = [
        "oos_gate=" + ("PASS" if ev.oos_gate_passed else "FAIL"),
        "v1_golden=" + ("PASS" if ev.v1_payload_hash_golden_passed else "FAIL"),
    ]
    return passed, f"AC-F6 [{verdict}]: v1 unchanged — {', '.join(parts)}"


def render_canary_v1_v2_compare(ev: FlipGateEvidence) -> str:
    """Render v1-vs-v2 side-by-side comparison + AC-F1..F6 evaluation."""
    _validate_evidence(ev)

    out = StringIO()
    out.write("# Canary v2-A — v1 vs v2 Comparison (PR 1 evidence package)\n\n")

    v2_batch_id = next(iter({r["params"]["batch_id"] for r in ev.v2_runs}))
    out.write(f"v2 batch_id: `{v2_batch_id}`\n")
    out.write(f"v2 robustness run id: {ev.v2_robustness_run.get('id')}\n\n")

    out.write("## Full-history AUCs (composite over all snapshots)\n\n")
    out.write("| Horizon          | v1 (production) | v2 (research)   |    Δ     |\n")
    out.write("|------------------|----------------:|----------------:|---------:|\n")
    for horizon in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        v1 = ev.v1_full_history_aucs.get(horizon)
        v2 = ev.v2_full_history_aucs.get(horizon)
        if v1 is None or v2 is None:
            out.write(
                f"| {horizon:<16} | n/a             | n/a             | n/a      |\n"
            )
        else:
            d = v2 - v1
            out.write(f"| {horizon:<16} | {v1:>14.4f}  | {v2:>14.4f}  | {d:>+8.4f} |\n")
    out.write("\n")

    out.write("## Band distribution (full-history snapshots)\n\n")
    out.write("| Band       |  v1 % |  v2 % |\n")
    out.write("|------------|------:|------:|\n")
    for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        v1 = ev.v1_band_distribution.get(band, 0.0)
        v2 = ev.v2_band_distribution.get(band, 0.0)
        out.write(f"| {band:<10} | {v1:>4.1f} | {v2:>4.1f} |\n")
    out.write("\n")

    out.write("## Per-window 60d AUC (walk-forward)\n\n")
    out.write("| Window | v1 60d AUC | v2 60d AUC |    Δ    |\n")
    out.write("|--------|-----------:|-----------:|--------:|\n")
    v1_by_wid = {r["params"]["window_id"]: r for r in ev.v1_runs}
    v2_by_wid = {r["params"]["window_id"]: r for r in ev.v2_runs}
    for wid in CANONICAL_WINDOWS:
        v1 = v1_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        v2 = v2_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        if v1 is None or v2 is None:
            out.write(f"| {wid}   | n/a        | n/a        | n/a     |\n")
        else:
            d = v2 - v1
            out.write(f"| {wid}   | {v1:>9.4f}  | {v2:>9.4f}  | {d:>+7.4f} |\n")
    out.write("\n")

    out.write("## AC-F1..F6 Evaluation\n\n")
    results = [
        _eval_ac_f1(ev),
        _eval_ac_f2(ev),
        _eval_ac_f3(ev),
        _eval_ac_f4(ev),
        _eval_ac_f5(ev),
        _eval_ac_f6(ev),
    ]
    for _, line in results:
        out.write(f"- {line}\n")
    out.write("\n")

    all_pass = all(p for p, _ in results)
    verdict = "SHIP" if all_pass else "STOP"
    out.write(f"## Verdict: **{verdict}**\n\n")
    if all_pass:
        out.write(
            "All 6 AC-Fn gates passed. PR 2 may flip "
            "`COMPOSITE_VERSION = 1 -> 2` in `canary_calibration.py:11`. "
            "See spec §10 for the PR 2 task list.\n\n"
        )
    else:
        out.write(
            "One or more AC-Fn gates failed. **PR 2 is NOT authorized.** "
            "Record the verdict in `docs/research/regime/canary-5yr-executive-summary.md` "
            "§13, file a follow-up issue, and pivot to v2-C (issue #90).\n\n"
        )

    out.write("## What PR 2 will do iff this verdict is SHIP\n\n")
    out.write(
        "PR 2 is a small (~80-150 LOC) commit that:\n"
        "1. Bumps `COMPOSITE_VERSION = 2` in `canary_calibration.py:11`.\n"
        "2. Regens `web/lib/types.ts` from updated OpenAPI schema.\n"
        "3. Replaces `LAST_KNOWN_AUC_v1_*` with `LAST_KNOWN_AUC_v2_*`.\n"
        "4. Updates `canary-methodology.md` to document the v2 formula.\n"
        "5. Adds a deprecation note in `canary-calibration-v1.json`.\n"
        "6. Updates `CanarySubTab.tsx` + `CanaryValidationPanel.tsx` to "
        "surface `vol_resolution_score` + `speed_state` + `warning_cap` separately.\n"
    )
    return out.getvalue()


# --------------- DB assembly (impure) ---------------


def _full_history_aucs_via_compute_canary_series(
    conn,
    *,
    cal,
    schema: str,
) -> dict[str, float]:
    """Compute composite AUC over the full history using _compute_canary_series.

    Snapshot rows do not carry the spx forward-return inputs that
    _aucs_for_rows -> _entry_lagged_label needs. _compute_canary_series's
    eval_rows DO, so this is the correct apples-to-apples path.
    """
    # `scripts/` is not a Python package and is only on sys.path when pytest
    # adds repo root (pythonpath = ["src", "."] in pyproject.toml). When an
    # operator runs `uv run python scripts/backtest_canary.py --v1-v2-compare`
    # from a cwd other than the repo root, the import below would fail with
    # ModuleNotFoundError. Add REPO_ROOT to sys.path defensively.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.backtest_canary import _aucs_for_rows, _compute_canary_series

    series = _compute_canary_series(
        conn,
        cal,
        form=cal.score_form,
        start=_date(2011, 2, 8),
        end=_date.today(),
        schema=schema,
    )
    return _aucs_for_rows(series["eval_rows"])["composite"]


def _band_distribution_for_version(
    conn,
    *,
    schema: str,
    version: int,
) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT band, COUNT(*) FROM {schema}.canary_snapshots "
            f"WHERE composite_version=%s GROUP BY band",
            (version,),
        )
        counts = dict(cur.fetchall())
    total = sum(counts.values())
    if total == 0:
        return {b: 0.0 for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")}
    return {
        b: 100.0 * counts.get(b, 0) / total
        for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    }


def _run_subprocess_test(test_path: str) -> bool:
    """Run pytest on a single test file. Returns True on returncode 0.

    Inherits parent environment (PATH preserved so `uv` is found on macOS,
    which keeps uv at ~/.cargo/bin/uv outside /usr/bin:/bin).
    """
    proc = subprocess.run(
        ["uv", "run", "pytest", test_path, "-q", "--no-header"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return proc.returncode == 0


def _assemble_flip_gate_evidence(
    conn, *, schema: str, batch_id: str | None = None
) -> FlipGateEvidence:
    """Build a FlipGateEvidence from DB. Heavy — run only in --v1-v2-compare.

    If `batch_id` is provided, the report compares against that exact v2 batch
    (still requiring all 6 walk-forward windows + 1 robustness row to be
    present). If None, the latest complete v2 batch is selected.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked AS (
              SELECT id, composite_version, run_scope, params, summary,
                     ROW_NUMBER() OVER (
                       PARTITION BY params->>'window_id'
                       ORDER BY completed_at DESC
                     ) AS rn
              FROM {schema}.regime_backtest_runs
              WHERE indicator='canary' AND run_scope='production'
                AND composite_version='1'
                AND params->>'phase'='walk_forward'
                AND completed_at IS NOT NULL
            )
            SELECT id, composite_version, run_scope, params, summary
            FROM ranked WHERE rn=1 ORDER BY params->>'window_id'
            """
        )
        v1_runs = [
            {
                "id": r[0],
                "composite_version": r[1],
                "run_scope": r[2],
                "params": r[3],
                "summary": r[4],
            }
            for r in cur.fetchall()
        ]
        if len(v1_runs) != 6:
            raise RuntimeError(
                f"v1 walk-forward query returned {len(v1_runs)} rows, expected 6. "
                f"Has PR #83's persistence completed?"
            )

        if batch_id is not None:
            # Operator-supplied batch_id: verify it exists with all 6 windows
            # complete. Fail loud with the supplied id in the message so the
            # operator can diagnose (typo? wrong scope? missing window?).
            cur.execute(
                f"""
                SELECT ARRAY_AGG(params->>'window_id' ORDER BY params->>'window_id')
                FROM {schema}.regime_backtest_runs
                WHERE indicator='canary' AND run_scope='research'
                  AND composite_version='2'
                  AND params->>'phase'='walk_forward'
                  AND params->>'batch_id'=%s
                  AND completed_at IS NOT NULL
                """,
                (batch_id,),
            )
            wids_row = cur.fetchone()
            wids = wids_row[0] if wids_row else None
            if wids != ["WF-1", "WF-2", "WF-3", "WF-4", "WF-5", "WF-6"]:
                raise RuntimeError(
                    f"requested batch_id={batch_id!r} does not have 6 complete "
                    f"v2 walk-forward windows (got: {wids}). Run "
                    f"`uv run python scripts/backtest_canary.py --walk-forward "
                    f"--composite-version 2` to produce a new batch, or omit "
                    f"--batch-id to use the latest complete batch."
                )
            v2_batch_id = batch_id
        else:
            cur.execute(
                f"""
                WITH batches AS (
                  SELECT params->>'batch_id' AS batch_id,
                         MAX(completed_at) AS latest,
                         ARRAY_AGG(params->>'window_id' ORDER BY params->>'window_id') AS wids
                  FROM {schema}.regime_backtest_runs
                  WHERE indicator='canary' AND run_scope='research'
                    AND composite_version='2'
                    AND params->>'phase'='walk_forward'
                    AND completed_at IS NOT NULL
                  GROUP BY params->>'batch_id'
                )
                SELECT batch_id FROM batches
                WHERE wids = ARRAY['WF-1','WF-2','WF-3','WF-4','WF-5','WF-6']
                ORDER BY latest DESC LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(
                    "no complete v2 walk-forward batch found. Run "
                    "`uv run python scripts/backtest_canary.py --walk-forward "
                    "--composite-version 2` first."
                )
            v2_batch_id = row[0]

        cur.execute(
            f"SELECT id, composite_version, run_scope, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='walk_forward' "
            f"  AND params->>'batch_id'=%s AND completed_at IS NOT NULL "
            f"ORDER BY params->>'window_id'",
            (v2_batch_id,),
        )
        v2_runs = [
            {
                "id": r[0],
                "composite_version": r[1],
                "run_scope": r[2],
                "params": r[3],
                "summary": r[4],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            f"SELECT id, composite_version, run_scope, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='robustness' "
            f"  AND params->>'batch_id'=%s AND completed_at IS NOT NULL "
            f"ORDER BY completed_at DESC LIMIT 1",
            (v2_batch_id,),
        )
        rb = cur.fetchone()
        if rb is None:
            raise RuntimeError(
                f"no v2 robustness run for batch_id={v2_batch_id}. Run "
                f"`uv run python scripts/backtest_canary.py --robustness "
                f"--composite-version 2 --batch-id {v2_batch_id}`."
            )
        v2_robustness_run = {
            "id": rb[0],
            "composite_version": rb[1],
            "run_scope": rb[2],
            "params": rb[3],
            "summary": rb[4],
        }

        cur.execute(
            f"SELECT data_date::text, payload->'speed'->>'confirmed_canary_active' "
            f"FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 AND data_date = ANY(%s)",
            ([_date.fromisoformat(d) for d in CCA_EVENT_DATES],),
        )
        v2_cca_event_states = {d: (str(v).lower() == "true") for d, v in cur.fetchall()}
        for d in CCA_EVENT_DATES:
            v2_cca_event_states.setdefault(d, False)

    v1_cal = load_calibration(path=V1_CAL_PATH)
    v2_cal = load_calibration(path=V2_CAL_PATH)
    v1_full_history_aucs = _full_history_aucs_via_compute_canary_series(
        conn,
        cal=v1_cal,
        schema=schema,
    )
    v2_full_history_aucs = _full_history_aucs_via_compute_canary_series(
        conn,
        cal=v2_cal,
        schema=schema,
    )

    v1_band_distribution = _band_distribution_for_version(
        conn, schema=schema, version=1
    )
    v2_band_distribution = _band_distribution_for_version(
        conn, schema=schema, version=2
    )

    oos_gate_passed = _run_subprocess_test(
        "tests/integration/regime/test_canary_oos_gate.py"
    )
    v1_payload_hash_golden_passed = _run_subprocess_test(
        "tests/unit/test_canary_v1_payload_hash_golden.py"
    )

    return FlipGateEvidence(
        v1_runs=v1_runs,
        v2_runs=v2_runs,
        v2_robustness_run=v2_robustness_run,
        v1_full_history_aucs=v1_full_history_aucs,
        v2_full_history_aucs=v2_full_history_aucs,
        v1_band_distribution=v1_band_distribution,
        v2_band_distribution=v2_band_distribution,
        v2_cca_event_states=v2_cca_event_states,
        oos_gate_passed=oos_gate_passed,
        v1_payload_hash_golden_passed=v1_payload_hash_golden_passed,
    )


def assemble_and_render_canary_v1_v2_compare(
    conn, *, schema: str, batch_id: str | None = None
) -> str:
    """Convenience: assemble evidence + render to markdown.

    If batch_id is provided, compares that exact v2 batch (otherwise the latest
    complete v2 batch).
    """
    ev = _assemble_flip_gate_evidence(conn, schema=schema, batch_id=batch_id)
    return render_canary_v1_v2_compare(ev)


def main() -> int:
    """Standalone CLI: re-render the latest v1+v2 evidence bundle from DB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help="Compare against this exact v2 walk-forward batch_id (must have "
        "all 6 windows + 1 robustness row complete). Defaults to the latest "
        "complete v2 batch.",
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        print(
            assemble_and_render_canary_v1_v2_compare(
                conn, schema=settings.db_schema, batch_id=args.batch_id
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
