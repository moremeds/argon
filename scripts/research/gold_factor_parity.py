"""Parity of argon's gold factor engine (uw_scan.macro.gold_factor) with the signal-lab study.

    uv run python scripts/research/gold_factor_parity.py \
        --study ~/projects/signal-lab/.worktrees/research-gold-yield-usd-triad \
        [--xenon /tmp/xenon-argon-verify]

Two checks, written to docs/research/2026-10-10-gold-factor-parity.json:
  inputs:    the study's raw IB 1-day midpoint closes + FRED files -> argon `changes` vs the
             study's grid_ext y/r/d/s (rows to the frozen end 2026-10-07)
  estimator: grid_ext y/r/d/s -> argon `compute` vs the study's coefficient and daily-parts
             tables (01_coef_A_daily, 03b_unexplained_daily)
  xenon:     (with --xenon DIR) the same estimator run on closes pulled through xenon
             POST /historical/bars, one <LEG>.json bar list per price leg, in place of the
             study's IB files; outputs compared column by column to the frozen end
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from uw_scan.macro import gold_factor as gf

RUN = "research/runs/2026-10-09-gold-regime-direction"
SHEET = "research/forward/gold-regime-direction/statesheet"
FROZEN_END = pd.Timestamp("2026-10-07")
OUT = Path("docs/research/2026-10-10-gold-factor-parity.json")


def maxdiff(a: pd.Series, b: pd.Series) -> float:
    a, b = a.align(b, join="inner")
    m = np.isfinite(a.to_numpy(float)) | np.isfinite(b.to_numpy(float))
    return float(np.nanmax(np.abs(a.to_numpy(float)[m] - b.to_numpy(float)[m])))


def load_levels(study: Path) -> pd.DataFrame:
    ib, fred = study / RUN / "data/d1/data/ib", study / RUN / "data/lead/fred"
    cols = {
        leg: pd.read_csv(ib / f"ib_{leg.lower()}_1d_midpoint.csv", parse_dates=["date"]).set_index("date")["close"]
        for leg in gf.PRICE_LEGS
    }
    for sid in ("DFII10", "DGS10"):
        cols[sid] = pd.read_csv(fred / f"{sid}.csv", parse_dates=["date"]).set_index("date")["value"].astype(float)
    return pd.DataFrame(cols)


def xenon_check(study: Path, xdir: Path) -> dict:
    """Swap the study's IB closes for xenon's, rerun everything, diff the two outputs."""
    lv = load_levels(study)
    xen, legs = lv.copy(), {}
    for leg in gf.PRICE_LEGS:
        bars = pd.DataFrame(json.loads((xdir / f"{leg}.json").read_text()))
        s = bars.assign(date=pd.to_datetime(bars.date)).drop_duplicates("date", keep="last").set_index("date")["close"]
        a, b = lv[leg].loc[:FROZEN_END].dropna().align(s, join="inner")
        legs[leg] = {
            "first": str(s.index[0].date()),
            "overlap": len(a),
            "mismatch_dates": [str(d.date()) for d in a.index[(b / a - 1).abs() > 1e-6]],
            "study_only_dates": [str(d.date()) for d in lv[leg].loc[:FROZEN_END].dropna().index.difference(s.index)],
        }
        xen[leg] = s

    def run(levels: pd.DataFrame) -> pd.DataFrame:
        chg = gf.changes(levels.loc[levels.dropna().index[0] : FROZEN_END])
        return gf.compute(chg[["y", "r", "d", "s"]])

    mine, theirs = run(lv), run(xen)
    num = [c for c in mine.columns if mine[c].dtype.kind == "f"]
    return {
        "legs": legs,
        "rows": [len(mine), len(theirs)],
        "same_dates": bool(mine.index.equals(theirs.index)),
        "max_abs_diff": max(maxdiff(mine[c], theirs[c]) for c in num),
        "label_mismatches": int(sum((mine[c].fillna("U") != theirs[c].fillna("U")).sum() for c in ("raw_label", "published_label"))),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", type=Path, required=True)
    ap.add_argument("--xenon", type=Path, help="dir of <LEG>.json xenon bar lists")
    args = ap.parse_args()
    study = args.study.expanduser()
    ext = pd.read_parquet(study / RUN / "panel/data/grid_ext.parquet")
    c01 = pd.read_parquet(study / SHEET / "01_coef_A_daily.parquet")
    c3b = pd.read_parquet(study / SHEET / "03b_unexplained_daily.parquet")

    # inputs: the study builds its window from the first complete date to the frozen end
    lv = load_levels(study)
    first = lv.dropna().index[0]
    mine = gf.changes(lv.loc[first:FROZEN_END])
    inputs = {
        "rows_argon": len(mine),
        "rows_study": len(ext),
        "same_dates": bool(mine.index.equals(ext.index)),
        **{f"max_abs_{c}": maxdiff(mine[c], ext[c]) for c in ("y", "r", "d", "s")},
    }

    out = gf.compute(ext[["y", "r", "d", "s"]])
    pairs = {c: c for c in ("a", "b_r", "b_d", "b_s", "b_r_lo95", "b_r_hi95", "b_d_lo95", "b_d_hi95", "b_s_lo95", "b_s_hi95")}
    pairs["e"] = "explained_share"
    est = {f"01.{k}": maxdiff(out[v], c01[k]) for k, v in pairs.items()}
    for k, v in {
        "gold_change": "gold_change",
        "own_trailing_drift": "own_trailing_drift",
        "real_yield_part": "real_yield_part",
        "dollar_part": "dollar_part",
        "haven_part": "haven_part",
        "U_1": "unexplained_1",
        "U_5": "unexplained_5",
        "U_21": "unexplained_21",
    }.items():
        est[f"03b.{k}"] = maxdiff(out[v], c3b[k])
    pub = out["published_label"].map(gf.STUDY_NAME).reindex(c01.index)
    raw = out["raw_label"].map(gf.STUDY_NAME).reindex(c01.index)
    est["01.published_name_mismatches"] = int((pub.fillna("UNDEF") != c01["published_name"]).sum())
    est["01.raw_name_mismatches"] = int((raw.fillna("UNDEF") != c01["raw_name"]).sum())
    e = out.loc[:"2021-12-31", "explained_share"].dropna()
    est["thresholds_recomputed"] = np.percentile(e, [33, 67]).tolist()
    est["thresholds_constant"] = [gf.E_LO, gf.E_HI]

    commit = subprocess.run(
        ["git", "-C", str(study), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    res = {"study": str(study), "study_commit": commit, "frozen_end": str(FROZEN_END.date()), "inputs": inputs, "estimator": est}
    if args.xenon:
        res["xenon"] = {"dir": str(args.xenon), **xenon_check(study, args.xenon)}
    elif OUT.exists():  # keep a previous xenon block when rerunning without the bars
        prev = json.loads(OUT.read_text()).get("xenon")
        if prev:
            res["xenon"] = prev
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
