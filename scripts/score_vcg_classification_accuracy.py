"""Score VCG v1 on regime-classification accuracy against Level-1 ground truth.

Phase B1 entry point. v0.3 incorporates 24 tribunal fixes.

Modes:
    default                        - score, persist, render (idempotent reuse)
    --force-new-run                - bypass idempotent reuse
    --render-run-id <N>            - replay-render via persisted report_md
    --dry-run                      - score without persistence
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from psycopg import connect

from uw_scan.cards.regime_classification_labels import (
    CANONICAL_CLASSES,
    derive_level1_frame,
)
from uw_scan.cards.regime_classification_scoring import (
    build_confusion_matrix,
    classify_failure_mode,
    cohens_kappa,
    compute_verdict,
    normalize_vcg_label,
    per_class_prf,
    sanitize_for_json,
    weighted_f1_over_eligible,
)
from uw_scan.reports.regime_classification_report import render_report
from uw_scan.storage.regime_classification_repository import (
    ClassificationRunAlreadyExists,
    RegimeClassificationRepository,
)

LABEL_DIR_DEFAULT = Path("docs/research/regime/ground-truth-labels")
CLASSES = list(CANONICAL_CLASSES)
CORE = ["NORMAL", "SUPPRESSED", "EDR", "RISK_OFF"]


def _resolve_dsn() -> str:
    """Prefer UW_SCAN_DB_URL env override; fall back to project Settings."""
    env = os.environ.get("UW_SCAN_DB_URL")
    if env:
        return env
    from uw_scan.config import Settings

    return Settings.from_env().db_dsn()


@dataclass(frozen=True)
class LabelContract:
    thresholds: dict[str, Any]
    crises: list[dict[str, Any]]
    vcg_source: dict[str, Any]
    label_version: int


def load_label_contract(label_dir: Path = LABEL_DIR_DEFAULT) -> LabelContract:
    """Load 4 frozen YAML files."""
    with (label_dir / "level1-thresholds.yaml").open() as f:
        thresholds = yaml.safe_load(f)
    with (label_dir / "named-crises.yaml").open() as f:
        crises = yaml.safe_load(f)["crises"]
    with (label_dir / "vcg-source.yaml").open() as f:
        vcg_source = yaml.safe_load(f)["vcg_source"]
    with (label_dir / "label-version.yaml").open() as f:
        version_meta = yaml.safe_load(f)
    label_version = int(version_meta["version"])
    if int(thresholds["label_version"]) != label_version:
        raise ValueError(
            f"label_version mismatch: thresholds={thresholds['label_version']} "
            f"vs version_meta={label_version}"
        )
    return LabelContract(
        thresholds=thresholds,
        crises=crises,
        vcg_source=vcg_source,
        label_version=label_version,
    )


def _normalize_date_index(s):
    """v0.3 / CL-9: normalize date index consistently."""
    s = s.copy()
    s.index = pd.to_datetime(s.index).normalize()
    return s


def load_input_series(
    conn,
    *,
    eval_start: date,
    warmup_days: int = 400,
    as_of_cutoff: datetime | None = None,
) -> dict[str, pd.Series]:
    """v0.3 fixes:
    - CO-1: DISTINCT ON (series_id, obs_date) ORDER BY as_of DESC
    - CL-7: explicit non-None assertions on required series
    - CL-9: normalized date index across all returned series
    - patch section 13: 400-day warmup lookback
    """
    data_start = eval_start - timedelta(days=warmup_days)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, symbol, close FROM uw_scan.vol_index_daily "
            "WHERE symbol IN ('VIX','VVIX','SPX') AND trade_date >= %s "
            "ORDER BY trade_date",
            (data_start,),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["trade_date", "symbol", "close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    pivot = df.pivot(index="trade_date", columns="symbol", values="close")

    if as_of_cutoff is not None:
        macro_sql = """
            SELECT DISTINCT ON (series_id, obs_date)
                obs_date, series_id, value
            FROM uw_scan.macro_series_daily
            WHERE series_id IN ('NFCI','ANFCI','USREC')
              AND obs_date >= %s
              AND as_of <= %s
            ORDER BY series_id, obs_date, as_of DESC
        """
        macro_params = (data_start, as_of_cutoff)
    else:
        macro_sql = """
            SELECT DISTINCT ON (series_id, obs_date)
                obs_date, series_id, value
            FROM uw_scan.macro_series_daily
            WHERE series_id IN ('NFCI','ANFCI','USREC')
              AND obs_date >= %s
            ORDER BY series_id, obs_date, as_of DESC
        """
        macro_params = (data_start,)

    with conn.cursor() as cur:
        cur.execute(macro_sql, macro_params)
        macro_rows = cur.fetchall()
    macro = pd.DataFrame(macro_rows, columns=["obs_date", "series_id", "value"])
    macro["obs_date"] = pd.to_datetime(macro["obs_date"]).dt.normalize()
    macro_pivot = macro.pivot(index="obs_date", columns="series_id", values="value")
    macro_aligned = macro_pivot.reindex(pivot.index, method="ffill")

    out = {
        "VIX": pivot.get("VIX"),
        "VVIX": pivot.get("VVIX"),
        "SPX": pivot.get("SPX"),
        "NFCI": macro_aligned.get("NFCI"),
        "ANFCI": macro_aligned.get("ANFCI"),
        "USREC": macro_aligned.get("USREC"),
    }

    required = ["VIX", "VVIX", "SPX", "NFCI"]
    for k in required:
        if out[k] is None or out[k].empty:
            raise ValueError(
                f"Required series {k!r} is missing or empty. "
                f"For VIX/VVIX/SPX check vol_index_daily; "
                f"for NFCI check macro_series_daily ingestion (Phase 0.5 prereq)."
            )

    for k in list(out):
        if out[k] is not None:
            # DB returns Decimal; np.log / rolling math need float64.
            out[k] = _normalize_date_index(out[k].astype(float))
    return out


def load_vcg_daily(conn, *, run_id: int) -> pd.Series:
    """v0.3:
    - CL-4: verify_integrity=True
    - CL-9: explicit _normalize_date_index call
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, level FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s ORDER BY trade_date",
            (run_id,),
        )
        rows = cur.fetchall()
    if not rows:
        raise ValueError(f"VCG source run_id={run_id} has no daily rows")
    df = pd.DataFrame(rows, columns=["trade_date", "level"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    df["level"] = df["level"].apply(normalize_vcg_label)
    s = df.set_index("trade_date", verify_integrity=True)["level"]
    return _normalize_date_index(s)


def derive_truth_frame(series, *, thresholds):
    """Pure: returns DataFrame with truth_label, components, NFCI_value."""
    return derive_level1_frame(
        vix=series["VIX"],
        vvix=series["VVIX"],
        spx=series["SPX"],
        credit_stress=series["NFCI"],
        thresholds=thresholds,
    )


def score_against_vcg(
    *,
    vcg_labels: pd.Series,
    truth_frame: pd.DataFrame,
    period_buckets: list[dict],
    eval_start_ts: pd.Timestamp,
    eval_end_ts: pd.Timestamp | None,
):
    """v0.3 / CO-10: honor eval_end_ts when not None."""
    aligned = pd.concat(
        [
            vcg_labels.rename("vcg"),
            truth_frame["truth_label"].rename("truth"),
        ],
        axis=1,
    ).dropna()
    aligned = aligned[aligned.index >= eval_start_ts]
    if eval_end_ts is not None:
        aligned = aligned[aligned.index <= eval_end_ts]

    cm_overall = build_confusion_matrix(
        truth=aligned["truth"], pred=aligned["vcg"], classes=CLASSES
    )
    per_class = per_class_prf(cm_overall)
    k = cohens_kappa(cm_overall)

    cm_by_period: dict[str, pd.DataFrame] = {}
    for bucket in period_buckets:
        start = pd.Timestamp(bucket["start"]).normalize()
        end = (
            pd.Timestamp(bucket["end"]).normalize()
            if bucket["end"] != "auto"
            else aligned.index.max()
        )
        subset = aligned[(aligned.index >= start) & (aligned.index <= end)]
        if not subset.empty:
            cm_by_period[bucket["name"]] = build_confusion_matrix(
                truth=subset["truth"], pred=subset["vcg"], classes=CLASSES
            )

    return {
        "cm_overall": cm_overall,
        "cm_by_period": cm_by_period,
        "per_class": per_class,
        "kappa": k,
        "aligned": aligned,
    }


def compute_named_crisis_overlay(*, vcg_labels, truth_frame, crises):
    """Pure: per-crisis label distributions."""
    out: list[dict] = []
    aligned = pd.concat(
        [
            vcg_labels.rename("vcg"),
            truth_frame["truth_label"].rename("truth"),
        ],
        axis=1,
    ).dropna()
    for crisis in crises:
        start = pd.Timestamp(crisis["start_date"]).normalize()
        end = pd.Timestamp(crisis["end_date"]).normalize()
        subset = aligned[(aligned.index >= start) & (aligned.index <= end)]
        if subset.empty:
            continue
        vcg_dist = subset["vcg"].value_counts().to_dict()
        truth_dist = subset["truth"].value_counts().to_dict()
        out.append(
            {
                "name": crisis["name"],
                "start": str(start.date()),
                "end": str(end.date()),
                "n_days": int(len(subset)),
                "vcg_distribution": {k: int(v) for k, v in vcg_dist.items()},
                "truth_distribution": {k: int(v) for k, v in truth_dist.items()},
            }
        )
    return out


def _float_or_none(x) -> float | None:
    """v0.3 / CL-10: explicit pd.isna instead of `or None`."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def persist_and_render(
    conn,
    *,
    contract,
    scoring,
    verdict,
    failure_mode,
    weighted_f1_val,
    named_crisis_overlay,
    eval_start,
    eval_end,
    truth_frame,
    out_path,
    data_vintages,
):
    """v0.3:
    - CL-8: atomic via repository's transaction wrapper
    - CR-1: persists rendered report_md in summary for byte-identical replay
    - CO-2: sanitize_for_json applied to summary
    - CL-3: payload includes NFCI_value per day
    - CL-10: components use pd.isna-based _float_or_none
    """
    rcr = RegimeClassificationRepository(conn)

    daily_rows = []
    for idx, row in scoring["aligned"].iterrows():
        components_row = truth_frame.loc[idx]
        instant = components_row.get("instant_label")
        instant_str = None if pd.isna(instant) else str(instant)
        daily_rows.append(
            {
                "trade_date": idx.date(),
                "vcg_label": row["vcg"],
                "truth_label": row["truth"],
                "match": row["vcg"] == row["truth"],
                "label_components": {
                    "vix_pct": _float_or_none(components_row.get("vix_pct")),
                    "vvix_pct": _float_or_none(components_row.get("vvix_pct")),
                    "rv_pct": _float_or_none(components_row.get("rv_pct")),
                    "credit_pct": _float_or_none(components_row.get("credit_pct")),
                    "dd": _float_or_none(components_row.get("dd")),
                    "NFCI_value": _float_or_none(components_row.get("NFCI_value")),
                    "instant_label": instant_str,
                },
                "label_version": contract.label_version,
            }
        )

    # Two-phase insert in one transaction:
    #   1. insert_run (gets run_id) with placeholder summary
    #   2. render report with real run_id
    #   3. update summary to include report_md (CR-1)
    #   4. bulk_insert_daily
    #   5. mark_completed
    with conn.transaction():
        run_id = rcr.insert_classification_run(
            vcg_source_run_id=int(contract.vcg_source["run_id"]),
            composite_version=str(contract.vcg_source["composite_version"]),
            eval_start=eval_start,
            eval_end=eval_end,
            label_version=contract.label_version,
            n_days=len(scoring["aligned"]),
            summary={"extras": {"classification": {"placeholder": True}}},
        )

        report = render_report(
            run_id=run_id,
            label_version=contract.label_version,
            eval_start=str(eval_start),
            eval_end=str(eval_end),
            n_days=len(scoring["aligned"]),
            verdict=verdict,
            failure_mode=failure_mode,
            per_class=scoring["per_class"],
            cm_overall=scoring["cm_overall"],
            cm_by_period=scoring["cm_by_period"],
            weighted_f1=weighted_f1_val,
            kappa=scoring["kappa"],
            named_crisis_overlay=named_crisis_overlay,
            vcg_source=contract.vcg_source,
            data_vintages=data_vintages,
        )

        full_summary = {
            "extras": {
                "classification": sanitize_for_json(
                    {
                        "verdict": verdict,
                        "failure_mode": failure_mode,
                        "weighted_f1": weighted_f1_val,
                        "kappa": scoring["kappa"],
                        "per_class": scoring["per_class"],
                        "report_md": report,
                    }
                )
            }
        }
        rcr.update_run_summary(run_id, full_summary)
        rcr.bulk_insert_daily_classifications(run_id, daily_rows)
        rcr.mark_run_completed(run_id)

    out_path.write_text(report)
    return run_id


def render_replay(conn, *, run_id: int, out_path: Path) -> int:
    """v0.3 / CR-1: read persisted markdown verbatim — byte-identical."""
    rcr = RegimeClassificationRepository(conn)
    data = rcr.load_run_for_render(run_id)
    extras = (data["summary"] or {}).get("extras", {}).get("classification", {})
    report_md = extras.get("report_md")
    if report_md:
        out_path.write_text(report_md)
        return run_id
    raise ValueError(
        f"run_id={run_id} has no persisted report_md; pre-v0.3 run cannot be "
        f"byte-replayed. Re-run with --force-new-run."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-new-run", action="store_true")
    parser.add_argument("--render-run-id", type=int, default=None)
    parser.add_argument("--label-dir", type=Path, default=LABEL_DIR_DEFAULT)
    parser.add_argument(
        "--out",
        default="docs/research/regime/vcg-classification-baseline-2026-05-26.md",
    )
    args = parser.parse_args(argv)

    dsn = _resolve_dsn()

    if args.render_run_id is not None:
        with connect(dsn) as conn:
            run_id = render_replay(
                conn, run_id=args.render_run_id, out_path=Path(args.out)
            )
        print(f"Re-rendered run_id={run_id}; report at {args.out}")
        return 0

    contract = load_label_contract(args.label_dir)
    eval_start = date.fromisoformat(contract.thresholds["eval_start"])
    eval_start_ts = pd.Timestamp(eval_start).normalize()

    eval_end_raw = contract.thresholds.get("eval_end", "auto")
    eval_end_ts = (
        None if eval_end_raw == "auto" else pd.Timestamp(eval_end_raw).normalize()
    )

    data_vintages = [
        {
            "component": "VIX",
            "vintage": "real-time",
            "lag": "0 days",
            "interpretation": "tradable signal",
        },
        {
            "component": "VVIX",
            "vintage": "real-time",
            "lag": "0 days",
            "interpretation": "tradable signal",
        },
        {
            "component": "SPX",
            "vintage": "real-time",
            "lag": "0 days",
            "interpretation": "tradable signal",
        },
        {
            "component": "NFCI",
            "vintage": "as_of latest",
            "lag": "3-5 days release lag",
            "interpretation": "post-hoc; non-tradable signal",
        },
    ]

    with connect(dsn) as conn:
        if not args.force_new_run:
            rcr = RegimeClassificationRepository(conn)
            existing = rcr.find_completed_classification_run(
                vcg_source_run_id=int(contract.vcg_source["run_id"]),
                label_version=contract.label_version,
            )
            if existing is not None:
                print(f"Existing run id={existing}; re-rendering.")
                render_replay(conn, run_id=existing, out_path=Path(args.out))
                return 0

        series = load_input_series(conn, eval_start=eval_start)
        vcg_labels = load_vcg_daily(conn, run_id=int(contract.vcg_source["run_id"]))
        truth_frame = derive_truth_frame(series, thresholds=contract.thresholds)
        scoring = score_against_vcg(
            vcg_labels=vcg_labels,
            truth_frame=truth_frame,
            period_buckets=contract.thresholds["period_buckets"],
            eval_start_ts=eval_start_ts,
            eval_end_ts=eval_end_ts,
        )
        verdict = compute_verdict(
            scoring["per_class"],
            core_classes=CORE,
            n_min_class_days=contract.thresholds["N_MIN_CLASS_DAYS"],
            k_min_core_eligible=contract.thresholds["K_MIN_CORE_ELIGIBLE"],
            macro_f1_pass=contract.thresholds["MACRO_F1_PASS"],
        )
        failure_mode = classify_failure_mode(
            verdict,
            scoring["per_class"],
            cm=scoring["cm_overall"],
            thresholds=contract.thresholds,
            per_universe_macro_f1=None,
        )
        eligible_for_weighting = verdict.get("all_eligible_classes") or verdict.get(
            "eligible_core_classes", []
        )
        weighted_f1_val = weighted_f1_over_eligible(
            scoring["per_class"], eligible_classes=eligible_for_weighting
        )
        named_overlay = compute_named_crisis_overlay(
            vcg_labels=vcg_labels,
            truth_frame=truth_frame,
            crises=contract.crises,
        )

        if args.dry_run:
            macro_f1 = verdict.get("macro_f1")
            macro_f1_str = f"{macro_f1:.4f}" if macro_f1 is not None else "None"
            print(
                f"DRY RUN — verdict: {verdict['overall']}, "
                f"mode: {failure_mode['primary']}, "
                f"macro_f1: {macro_f1_str}, "
                f"kappa: {scoring['kappa']:.4f}"
            )
            return 0

        eval_end_resolved = (
            eval_end_ts.date() if eval_end_ts else scoring["aligned"].index.max().date()
        )

        try:
            run_id = persist_and_render(
                conn,
                contract=contract,
                scoring=scoring,
                verdict=verdict,
                failure_mode=failure_mode,
                weighted_f1_val=weighted_f1_val,
                named_crisis_overlay=named_overlay,
                eval_start=eval_start,
                eval_end=eval_end_resolved,
                truth_frame=truth_frame,
                out_path=Path(args.out),
                data_vintages=data_vintages,
            )
        except ClassificationRunAlreadyExists as exc:
            print(f"Concurrent run detected: {exc}")
            return 1

        print(f"Persisted classification run_id={run_id}; report at {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
