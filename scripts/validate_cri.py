"""CRI validation harness — push the four questions:
   1. Define target: 5% drawdown in next 20d (primary), VIX>30 in next 10d (secondary)
   2. Naive baseline: VIX > trailing 252d p80
   3. Walk-forward: 2006-2015 in-sample for threshold tuning, 2016-2026 OOS
   4. Compare CRI v1 (current) vs CRI v2 (planned) vs baseline
"""
from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

LAKE = Path.home() / "market-warehouse/data-lake/bronze/asset_class=volatility"

# ── Component scorers ─────────────────────────────────────────────────────
def clip(x, lo, hi):
    return max(lo, min(hi, x))

def score_vix(vix, vix_5d_roc):
    if np.isnan(vix) or np.isnan(vix_5d_roc):
        return 0.0
    lvl = clip((vix - 15.0) / 25.0 * 15.0, 0, 15)
    roc = clip(max(vix_5d_roc, 0.0) / 60.0 * 10.0, 0, 10)
    return lvl + roc

def score_vvix_v1(vvix, vvix_vix_ratio):
    """Current production calibration."""
    if np.isnan(vvix) or np.isnan(vvix_vix_ratio):
        return 0.0
    lvl = clip((vvix - 90.0) / 50.0 * 17.0, 0, 17)
    ratio = clip((vvix_vix_ratio - 5.0) / 3.0 * 8.0, 0, 8)
    return lvl + ratio

def score_vvix_v2(vvix, vvix_vix_ratio, vvix_5d_roc):
    """Planned calibration: lower floor + RoC sub-score."""
    if np.isnan(vvix) or np.isnan(vvix_vix_ratio):
        return 0.0
    if np.isnan(vvix_5d_roc):
        vvix_5d_roc = 0.0
    lvl = clip((vvix - 85.0) / 45.0 * 12.0, 0, 12)
    ratio = clip((vvix_vix_ratio - 5.0) / 3.0 * 7.0, 0, 7)
    roc = clip(max(vvix_5d_roc, 0.0) / 25.0 * 6.0, 0, 6)
    return lvl + ratio + roc

def score_corr(corr, corr_5d_change):
    if np.isnan(corr):
        return 0.0
    if np.isnan(corr_5d_change):
        corr_5d_change = 0.0
    lvl = clip((corr - 25.0) / 45.0 * 17.0, 0, 17)
    spike = clip(max(corr_5d_change, 0.0) / 20.0 * 8.0, 0, 8)
    return lvl + spike

def score_trend(spx_dist_pct):
    if np.isnan(spx_dist_pct) or spx_dist_pct >= 0:
        return 0.0
    return clip(abs(spx_dist_pct) / 10.0 * 25.0, 0, 25)


# ── Build feature panel from lake ─────────────────────────────────────────
def load(sym: str, col: str = "close") -> pd.Series:
    df = pd.read_parquet(LAKE / f"symbol={sym}" / "1d.parquet")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    s = df.set_index("trade_date")[col].astype(float)
    s.name = sym
    return s

print("Loading lake...")
vix = load("VIX")
vvix = load("VVIX")
cor1m = load("COR1M")
spx = load("SPX")

panel = pd.concat([vix, vvix, cor1m, spx], axis=1).dropna()
panel.columns = ["VIX", "VVIX", "COR1M", "SPX"]
print(f"Aligned: n={len(panel)}, range={panel.index.min().date()} -> {panel.index.max().date()}")

# Derived features
panel["VIX_5d_roc"] = (panel["VIX"] / panel["VIX"].shift(5) - 1) * 100
panel["VVIX_5d_roc"] = (panel["VVIX"] / panel["VVIX"].shift(5) - 1) * 100
panel["COR1M_5d_chg"] = panel["COR1M"] - panel["COR1M"].shift(5)
panel["VVIX_VIX_ratio"] = panel["VVIX"] / panel["VIX"]
panel["SPX_100d_MA"] = panel["SPX"].rolling(100).mean()
panel["SPX_dist_pct"] = (panel["SPX"] / panel["SPX_100d_MA"] - 1) * 100

# ── Compute scores ────────────────────────────────────────────────────────
print("Scoring every day under v1 (current) and v2 (planned)...")
def cri_v1(row):
    return (score_vix(row["VIX"], row["VIX_5d_roc"])
            + score_vvix_v1(row["VVIX"], row["VVIX_VIX_ratio"])
            + score_corr(row["COR1M"], row["COR1M_5d_chg"])
            + score_trend(row["SPX_dist_pct"]))

def cri_v2(row):
    return (score_vix(row["VIX"], row["VIX_5d_roc"])
            + score_vvix_v2(row["VVIX"], row["VVIX_VIX_ratio"], row["VVIX_5d_roc"])
            + score_corr(row["COR1M"], row["COR1M_5d_chg"])
            + score_trend(row["SPX_dist_pct"]))

panel["CRI_v1"] = panel.apply(cri_v1, axis=1)
panel["CRI_v2"] = panel.apply(cri_v2, axis=1)

# Naive baseline: rolling 252-trading-day p80 of VIX
panel["VIX_p80_252d"] = panel["VIX"].rolling(252).quantile(0.80)
panel["baseline_score"] = panel["VIX"]  # raw VIX as predictor (for AUC), threshold = p80

# ── Labels ────────────────────────────────────────────────────────────────
# Target A: SPX drops >=5% from today's close within next 20 trading days
fwd_min = panel["SPX"].rolling(20).min().shift(-20)
panel["label_dd5"] = ((fwd_min / panel["SPX"]) - 1 <= -0.05).astype(int)

# Target B: VIX >= 30 in next 10 trading days
fwd_max_vix = panel["VIX"].rolling(10).max().shift(-10)
panel["label_vix30"] = (fwd_max_vix >= 30.0).astype(int)

# Target C: bigger drawdown — 10% in 60 days
fwd_min_60 = panel["SPX"].rolling(60).min().shift(-60)
panel["label_dd10"] = ((fwd_min_60 / panel["SPX"]) - 1 <= -0.10).astype(int)

# Drop tail rows where labels can't be computed
labels_panel = panel.dropna(subset=["label_dd5", "label_vix30", "label_dd10",
                                     "CRI_v1", "CRI_v2", "VIX_p80_252d"])
print(f"After dropping warmup + tail: n={len(labels_panel)}, "
      f"range={labels_panel.index.min().date()} -> {labels_panel.index.max().date()}")

print("\nBASE RATES:")
print(f"  5% drawdown in next 20d:  {labels_panel['label_dd5'].mean():.1%}")
print(f"  VIX >= 30 in next 10d:    {labels_panel['label_vix30'].mean():.1%}")
print(f"  10% drawdown in next 60d: {labels_panel['label_dd10'].mean():.1%}")


# ── Metrics ───────────────────────────────────────────────────────────────
def roc_auc(y_true, scores):
    """Mann-Whitney U / probability that a random positive scores higher than a random negative."""
    y = np.asarray(y_true)
    s = np.asarray(scores)
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # Efficient O(n log n) via rank
    ranks = pd.Series(s).rank().values
    pos_ranks = ranks[y == 1]
    auc = (pos_ranks.sum() - len(pos)*(len(pos)+1)/2) / (len(pos) * len(neg))
    return float(auc)

def metrics_at_threshold(y_true, scores, threshold):
    y = np.asarray(y_true).astype(bool)
    pred = np.asarray(scores) >= threshold
    tp = (pred & y).sum()
    fp = (pred & ~y).sum()
    fn = (~pred & y).sum()
    tn = (~pred & ~y).sum()
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2*precision*recall/(precision+recall) if (precision and recall and not np.isnan(precision) and not np.isnan(recall)) else float("nan")
    alarm_rate = pred.mean()
    return {"precision": precision, "recall": recall, "f1": f1, "alarm_rate": alarm_rate,
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)}

def baseline_threshold_per_row(panel_subset):
    """Naive baseline: alarm if VIX >= trailing 252d p80 — per-row threshold."""
    return (panel_subset["VIX"] >= panel_subset["VIX_p80_252d"]).astype(int)


# ── Walk-forward split ────────────────────────────────────────────────────
SPLIT_DATE = pd.Timestamp("2016-01-01")
in_sample = labels_panel[labels_panel.index < SPLIT_DATE]
oos = labels_panel[labels_panel.index >= SPLIT_DATE]
print(f"\nIN-SAMPLE: n={len(in_sample)} ({in_sample.index.min().date()} -> {in_sample.index.max().date()})")
print(f"OUT-OF-SAMPLE: n={len(oos)} ({oos.index.min().date()} -> {oos.index.max().date()})")

# Tune CRI thresholds on in-sample to match the baseline's alarm rate
# (so we compare at equal alarm budgets, not at arbitrary points)
baseline_alarm_rate_is = baseline_threshold_per_row(in_sample).mean()
print(f"\nBaseline (VIX >= trailing-252d p80) alarms on {baseline_alarm_rate_is:.1%} of in-sample days")

# Find CRI thresholds that match that alarm rate
def find_threshold_for_alarm_rate(scores, target_rate):
    return np.quantile(scores, 1 - target_rate)

thr_v1 = find_threshold_for_alarm_rate(in_sample["CRI_v1"].values, baseline_alarm_rate_is)
thr_v2 = find_threshold_for_alarm_rate(in_sample["CRI_v2"].values, baseline_alarm_rate_is)
print(f"  Matched threshold for CRI v1: {thr_v1:.2f}")
print(f"  Matched threshold for CRI v2: {thr_v2:.2f}")


# ── Evaluate ──────────────────────────────────────────────────────────────
def evaluate(df, label_col, label_name):
    print(f"\n{'='*70}\nTARGET: {label_name}   (base rate {df[label_col].mean():.1%})\n{'='*70}")
    print(f"{'Predictor':<35}  {'AUC':>6}  {'Prec':>6}  {'Recall':>7}  {'F1':>6}  {'Alarm':>6}")
    # Baseline (per-row threshold, no tuning needed)
    baseline_pred = baseline_threshold_per_row(df)
    base_metrics = {
        "precision": (baseline_pred[df[label_col]==1].sum() / max(baseline_pred.sum(), 1)),
        "recall": (baseline_pred[df[label_col]==1].sum() / max(df[label_col].sum(), 1)),
        "alarm_rate": baseline_pred.mean(),
    }
    base_metrics["f1"] = (2*base_metrics["precision"]*base_metrics["recall"] /
                          (base_metrics["precision"]+base_metrics["recall"])
                          if base_metrics["precision"]+base_metrics["recall"] else float("nan"))
    base_auc = roc_auc(df[label_col], df["VIX"])
    print(f"{'baseline (VIX>=trailing p80)':<35}  {base_auc:>6.3f}  {base_metrics['precision']:>6.1%}  "
          f"{base_metrics['recall']:>7.1%}  {base_metrics['f1']:>6.1%}  {base_metrics['alarm_rate']:>6.1%}")
    # CRI v1 at matched alarm rate
    v1_m = metrics_at_threshold(df[label_col], df["CRI_v1"], thr_v1)
    v1_auc = roc_auc(df[label_col], df["CRI_v1"])
    print(f"{f'CRI v1 (thr={thr_v1:.1f})':<35}  {v1_auc:>6.3f}  {v1_m['precision']:>6.1%}  "
          f"{v1_m['recall']:>7.1%}  {v1_m['f1']:>6.1%}  {v1_m['alarm_rate']:>6.1%}")
    # CRI v2 at matched alarm rate
    v2_m = metrics_at_threshold(df[label_col], df["CRI_v2"], thr_v2)
    v2_auc = roc_auc(df[label_col], df["CRI_v2"])
    print(f"{f'CRI v2 (thr={thr_v2:.1f})':<35}  {v2_auc:>6.3f}  {v2_m['precision']:>6.1%}  "
          f"{v2_m['recall']:>7.1%}  {v2_m['f1']:>6.1%}  {v2_m['alarm_rate']:>6.1%}")
    return {"v1_auc": v1_auc, "v2_auc": v2_auc, "base_auc": base_auc}


# In-sample (sanity check — should be best)
print("\n" + "█"*70 + "\nIN-SAMPLE (2006-2015) — used to set thresholds\n" + "█"*70)
for target, name in [("label_dd5", "SPX -5% in next 20d"),
                     ("label_vix30", "VIX >= 30 in next 10d"),
                     ("label_dd10", "SPX -10% in next 60d")]:
    evaluate(in_sample, target, name)

# OUT-OF-SAMPLE (the only one that matters)
print("\n" + "█"*70 + "\nOUT-OF-SAMPLE (2016-2026) — the honest test\n" + "█"*70)
oos_results = {}
for target, name in [("label_dd5", "SPX -5% in next 20d"),
                     ("label_vix30", "VIX >= 30 in next 10d"),
                     ("label_dd10", "SPX -10% in next 60d")]:
    oos_results[target] = evaluate(oos, target, name)


# ── Component-by-component decomposition (OOS only) ───────────────────────
print("\n" + "█"*70 + "\nCOMPONENT AUCs (OOS, target = SPX -5% in 20d)\n" + "█"*70)
oos["c_vix"]  = oos.apply(lambda r: score_vix(r["VIX"], r["VIX_5d_roc"]), axis=1)
oos["c_vvix_v1"] = oos.apply(lambda r: score_vvix_v1(r["VVIX"], r["VVIX_VIX_ratio"]), axis=1)
oos["c_vvix_v2"] = oos.apply(lambda r: score_vvix_v2(r["VVIX"], r["VVIX_VIX_ratio"], r["VVIX_5d_roc"]), axis=1)
oos["c_corr"] = oos.apply(lambda r: score_corr(r["COR1M"], r["COR1M_5d_chg"]), axis=1)
oos["c_trend"] = oos.apply(lambda r: score_trend(r["SPX_dist_pct"]), axis=1)

for name, col in [("VIX raw level", "VIX"),
                  ("VIX component", "c_vix"),
                  ("VVIX raw", "VVIX"),
                  ("VVIX v1 component", "c_vvix_v1"),
                  ("VVIX v2 component", "c_vvix_v2"),
                  ("COR1M raw", "COR1M"),
                  ("COR1M component", "c_corr"),
                  ("SPX dist from MA (-)", "SPX_dist_pct"),
                  ("Trend Break component", "c_trend"),
                  ("CRI v1 composite", "CRI_v1"),
                  ("CRI v2 composite", "CRI_v2")]:
    if col == "SPX_dist_pct":
        # Flip sign so "more negative = more bullish for crash"
        auc = roc_auc(oos["label_dd5"], -oos[col])
    else:
        auc = roc_auc(oos["label_dd5"], oos[col])
    print(f"  {name:<25} AUC={auc:.3f}")


# ── Lead-time analysis: do alarms fire BEFORE the event? ──────────────────
print("\n" + "█"*70 + "\nLEAD-TIME on 5 known stress windows (OOS only)\n" + "█"*70)
# Trough dates of named drawdowns within the OOS window
events = [
    ("2018-02-05", "Volmageddon"),
    ("2018-12-24", "Q4 2018 trough"),
    ("2020-03-23", "COVID trough"),
    ("2022-06-13", "rate-hike trough"),
    ("2024-08-05", "yen-carry unwind"),
]
print(f"{'Event':<22}  {'Date':<12}  {'days_v1_first_alarm':>22}  {'days_v2_first_alarm':>22}  {'days_baseline':>16}")
for date, name in events:
    target_date = pd.Timestamp(date)
    if target_date not in oos.index:
        # Find nearest trading day
        target_date = oos.index[oos.index.searchsorted(target_date)]
    # Look at the 60 trading days BEFORE the event
    window = oos.loc[:target_date].tail(61)
    if len(window) < 5:
        continue
    # When did v1 first cross thr_v1?
    v1_alarms = window[window["CRI_v1"] >= thr_v1]
    v1_lead = (target_date - v1_alarms.index[0]).days if len(v1_alarms) else None
    # v2
    v2_alarms = window[window["CRI_v2"] >= thr_v2]
    v2_lead = (target_date - v2_alarms.index[0]).days if len(v2_alarms) else None
    # baseline
    b_alarms = window[window["VIX"] >= window["VIX_p80_252d"]]
    b_lead = (target_date - b_alarms.index[0]).days if len(b_alarms) else None
    print(f"{name:<22}  {target_date.date()}  {str(v1_lead)+' cal d':>22}  "
          f"{str(v2_lead)+' cal d':>22}  {str(b_lead)+' cal d':>16}")

print("\nDONE.")
