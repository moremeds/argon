"""Pure renderer: canary form_sweep_full runs -> markdown table.

Mirrors regime_backtest_report.py (CRI) and regime_vcg_backtest_report.py (VCG):
pure function, no I/O, no DB. The __main__ block at the bottom adds a CLI
entry point that DOES touch the DB (via a module-private loader).

This renderer's primary defense against misuse is the fixed
"What this run does NOT decide" footer — see spec
docs/superpowers/specs/2026-05-27-canary-form-sweep-full-design.md §4.3.
"""

from __future__ import annotations

import argparse
import sys
from io import StringIO

import psycopg

from uw_scan.config import Settings

CANONICAL_FORMS = ("linear", "convex", "concave", "sigmoid")


def render_canary_form_sweep_compare(runs: list[dict]) -> str:
    """Render a 4-form comparison table from form_sweep_full runs.

    `runs` is a list of regime_backtest_runs row dicts, each with
    params.phase='form_sweep_full'. Caller is responsible for filtering
    and loading; this function does not touch the DB.

    Sort order in output: linear, convex, concave, sigmoid (canonical,
    not by id).

    Raises ValueError if:
      - fewer than 4 rows provided
      - any form is missing or duplicated
      - rows do not all share the same batch_id and composite_version
      - any row is not params.phase='form_sweep_full' or run_scope='research'
    """
    if len(runs) != 4:
        raise ValueError(f"need exactly 4 rows, got {len(runs)}")

    by_form: dict[str, dict] = {}
    for r in runs:
        if r.get("run_scope") != "research":
            raise ValueError(
                f"form_sweep_full rows must be research scoped, got {r.get('run_scope')!r}"
            )
        if r["params"].get("phase") != "form_sweep_full":
            raise ValueError(
                f"expected params.phase=form_sweep_full, got {r['params'].get('phase')!r}"
            )
        form = r["params"]["score_form"]
        if form not in CANONICAL_FORMS:
            raise ValueError(f"unknown score_form: {form}")
        if form in by_form:
            raise ValueError(f"duplicate score_form: {form}")
        by_form[form] = r

    for form in CANONICAL_FORMS:
        if form not in by_form:
            raise ValueError(f"missing score_form: {form}")

    batch_ids = {r["params"]["batch_id"] for r in runs}
    if len(batch_ids) != 1:
        raise ValueError(f"all rows must share batch_id, got {batch_ids}")
    composite_versions = {str(r["composite_version"]) for r in runs}
    if len(composite_versions) != 1:
        raise ValueError(
            f"all rows must share composite_version, got {composite_versions}"
        )

    sample = by_form["linear"]
    out = StringIO()
    out.write("# Canary form-sweep — candidate discovery\n")
    out.write(
        f"Window: {sample['start_date'].isoformat()} → "
        f"{sample['end_date'].isoformat()} "
        f"({sample['summary']['n_days']:,} days)\n"
    )
    out.write(f"Composite version: {sample['composite_version']}\n")
    out.write(f"Batch id: {next(iter(batch_ids))}\n")
    out.write(f"Run ids: {', '.join(str(by_form[f]['id']) for f in CANONICAL_FORMS)}\n")
    out.write("\n")

    out.write(
        "| Form    | AUC 5d | AUC 20d | AUC 60d | NONE% | WATCH% | BUY% | "
        "STRONG_BUY% | BUY-band 60d AUC | Vol-only gap (60d) |\n"
    )
    out.write(
        "|---------|-------:|--------:|--------:|------:|-------:|-----:|"
        "------------:|-----------------:|-------------------:|\n"
    )
    for form in CANONICAL_FORMS:
        s = by_form[form]["summary"]
        n = s["n_days"]
        bd = s["band_distribution"]

        def pct(b: str, _n: int = n, _bd: dict = bd) -> float:
            return 100.0 * _bd[b] / _n if _n else 0.0

        def _fmt(v: float | None, width: int) -> str:
            """`{v:>W.3f}` but renders None as a right-justified 'nan'."""
            if v is None:
                return "nan".rjust(width)
            return f"{v:>{width}.3f}"

        wb = s["within_band_aucs"]["BUY"].get("up60d_10pct")
        buy_band_str = _fmt(wb, 16)
        gap = s["vol_only_gap"]["up60d_10pct"]
        if gap is None:
            gap_str = "nan".rjust(18)
        else:
            gap_str = (("+" if gap >= 0 else "") + f"{gap:.3f}").rjust(18)
        c = s["aucs"]["composite"]
        out.write(
            f"| {form:<7} | {_fmt(c['up5d_2pct'], 6)} | "
            f"{_fmt(c['up20d_5pct'], 7)} | "
            f"{_fmt(c['up60d_10pct'], 7)} | "
            f"{pct('NONE'):>5.1f} | {pct('WATCH'):>6.1f} | "
            f"{pct('BUY'):>4.1f} | {pct('STRONG_BUY'):>11.1f} | "
            f"{buy_band_str} | {gap_str} |\n"
        )
    out.write("\n")

    out.write("## Observations\n\n")
    linear_summary = by_form["linear"]["summary"]

    def forms_where(predicate) -> str:
        matched = [f for f in CANONICAL_FORMS if predicate(by_form[f]["summary"])]
        return ", ".join(matched) if matched else "none"

    rules = [
        (
            "WATCH% above 30% in",
            lambda s: 100.0 * s["band_distribution"]["WATCH"] / s["n_days"] > 30.0,
            "  (over-broad WATCH band)",
        ),
        (
            "BUY-band 60d AUC below 0.50 in",
            lambda s: (
                s["within_band_aucs"]["BUY"].get("up60d_10pct") is not None
                and s["within_band_aucs"]["BUY"]["up60d_10pct"] < 0.50
            ),
            "  (regression-to-mean signature)",
        ),
        (
            "Vol-only gap (60d) ≥ +0.02 in",
            lambda s: (
                s["vol_only_gap"]["up60d_10pct"] is not None
                and s["vol_only_gap"]["up60d_10pct"] >= 0.02
            ),
            "  (speed layer net-negative for rank)",
        ),
        (
            "BUY% at exactly 0 (band never fires) in",
            lambda s: s["band_distribution"]["BUY"] == 0,
            "",
        ),
        (
            "STRONG_BUY% at exactly 0 (band never fires) in",
            lambda s: s["band_distribution"]["STRONG_BUY"] == 0,
            "",
        ),
        (
            "Composite 60d AUC improves over linear by ≥ +0.02 in",
            lambda s: (
                s["score_form"] != "linear"
                and s["aucs"]["composite"]["up60d_10pct"] is not None
                and linear_summary["aucs"]["composite"]["up60d_10pct"] is not None
                and s["aucs"]["composite"]["up60d_10pct"]
                - linear_summary["aucs"]["composite"]["up60d_10pct"]
                >= 0.02
            ),
            "  (deserves v2-C planning)",
        ),
        (
            "WATCH% reduced by ≥ 5 percentage points vs linear "
            "AND 60d AUC does not fall by more than 0.01 in",
            lambda s: (
                s["score_form"] != "linear"
                and s["aucs"]["composite"]["up60d_10pct"] is not None
                and linear_summary["aucs"]["composite"]["up60d_10pct"] is not None
                and (
                    100.0
                    * linear_summary["band_distribution"]["WATCH"]
                    / linear_summary["n_days"]
                    - 100.0 * s["band_distribution"]["WATCH"] / s["n_days"]
                )
                >= 5.0
                and (
                    linear_summary["aucs"]["composite"]["up60d_10pct"]
                    - s["aucs"]["composite"]["up60d_10pct"]
                )
                <= 0.01
            ),
            "  (practical v2-C candidate)",
        ),
    ]
    for label, predicate, suffix in rules:
        out.write(f"- {label}: {forms_where(predicate)}{suffix}\n")
    out.write("\n")

    out.write("## What this run does NOT decide\n\n")
    out.write(
        "This is candidate-discovery output. No form is declared "
        '"winning". Any v2 calibration change must reserve a fresh '
        "holdout window for OOS validation.\n"
    )
    return out.getvalue()


# ----------------------------------------------------------------------
# CLI entry point — DOES touch DB. Module-private loader pulls 4 rows.
# ----------------------------------------------------------------------


def _load_latest_complete_batch(conn, schema: str) -> list[dict]:
    """Load 4 rows from the most-recent complete form_sweep_full batch.

    "Complete" = exactly 4 rows AND covers all four CANONICAL_FORMS.
    Incomplete batches are skipped.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked_batches AS (
              SELECT params->>'batch_id' AS batch_id,
                     MAX(created_at) AS latest,
                     COUNT(*) AS n_rows,
                     array_agg(params->>'score_form' ORDER BY params->>'score_form')
                       AS forms
              FROM {schema}.regime_backtest_runs
              WHERE indicator = 'canary'
                AND run_scope = 'research'
                AND completed_at IS NOT NULL
                AND params->>'phase' = 'form_sweep_full'
              GROUP BY params->>'batch_id'
            )
            SELECT batch_id FROM ranked_batches
            WHERE n_rows = 4
              AND forms = ARRAY['concave','convex','linear','sigmoid']
            ORDER BY latest DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("no complete form_sweep_full batch found")
        batch_id = row[0]
        cur.execute(
            f"SELECT id, params, summary, start_date, end_date, composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s "
            f"AND indicator = 'canary' "
            f"AND run_scope = 'research' "
            f"AND completed_at IS NOT NULL "
            f"AND params->>'phase' = 'form_sweep_full' "
            f"ORDER BY params->>'score_form'",
            (batch_id,),
        )
        return [
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


def _load_specific_runs(conn, schema: str, run_ids: list[int]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, params, summary, start_date, end_date, composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE id = ANY(%s) "
            f"AND indicator = 'canary' "
            f"AND run_scope = 'research' "
            f"AND completed_at IS NOT NULL "
            f"AND params->>'phase' = 'form_sweep_full' "
            f"ORDER BY params->>'score_form'",
            (run_ids,),
        )
        return [
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        default="form_sweep_compare",
        choices=("form_sweep_compare",),
        help="rendering mode (currently only form_sweep_compare)",
    )
    p.add_argument(
        "--runs",
        default=None,
        help="comma-separated run ids; if omitted, load latest complete batch",
    )
    args = p.parse_args()

    settings = Settings.from_env()
    schema = settings.db_schema

    with psycopg.connect(settings.db_dsn()) as conn:
        if args.runs:
            run_ids = [int(s) for s in args.runs.split(",")]
            runs = _load_specific_runs(conn, schema, run_ids)
        else:
            runs = _load_latest_complete_batch(conn, schema)
    print(render_canary_form_sweep_compare(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
