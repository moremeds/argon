# VCG research — next steps after 2026-05-26 composite A/B

**Status**: backlog. Follow-up to `vcg-composite-validation-2026-05-26.md` (PR #81).

**Context**: the composite-proxy A/B returned a uniform FAIL across all 4 candidates, but the failure mode was test-underpowered (1–4 RO episodes per candidate over 50 years; SPX-only robustness denominator because NDX/RUT were absent from `vol_index_daily`), not candidate-bad. The HYG baseline scored the same 0% hit rate as every candidate — that's a measurement-instrument signal, not a verdict on credit proxies. This doc maps the work that turns the framework into a measurement instrument capable of actually distinguishing signals, then maps the deeper VCG questions that follow.

---

## 1. The honest read

What the PR's A/B test showed:
- 4 composite candidates do not beat single-HYG VCG on the implemented validation framework
- Day-to-day disagreement vs HYG: 0.05–0.07% (composites barely diverge from baseline)
- Total improvement days: 0.00 for every candidate × period combination

What it did *not* show:
- That credit-basket composites have no value (the framework had insufficient power to detect anything)
- That VCG has no alpha (VCG is a regime classifier, not a forward-return predictor — the framework tested it on a task it wasn't built for)

The asymmetric default-deny gate held, which means Hard Guarantee #5 worked as designed: no premature promotion under low statistical power.

## 2. Ranked next-step map

### #1 — Backfill NDX/RUT EOD into `vol_index_daily` (highest leverage)

**Why first.** Every other direction in this doc assumes the framework can distinguish signals. Right now it can't — the robustness gate denominator dropped from 9 cells (SPX/NDX/RUT × Fast/Medium/Major) to 3 cells (SPX only × Fast/Medium/Major), and that crippled the dominance gate. Worth doing even if the verdict stays FAIL, because then we'll know which: insufficient signal vs. insufficient candidates.

**Cost.** Small. The market-data warehouse already has NDX/RUT vol-complex EOD on R2 (per project memory `reference_market_warehouse_lake.md`). Per the 2026-05-25 R2-primary directive (`feedback_r2_primary_for_eod_backfill.md`), the read path is R2 → `vol_index_daily` via a one-shot backfill script.

**Acceptance**: `SELECT symbol, COUNT(*) FROM uw_scan.vol_index_daily GROUP BY symbol` returns ≥ 4000 bars each for NDX and RUT. Then `uv run python scripts/compare_vcg_lead_time.py` regenerates the report with NDX/RUT cells populated, lifting the robustness denominator from 3 cells to 9.

**Expected outcome**: either the verdict flips (real signal-distinguishing test on hand) or it stays FAIL with much higher confidence (you've genuinely shown composite proxies don't add value under the framework's question).

### #2 — Score VCG on its actual job: regime-classification accuracy

**Why.** VCG's documented purpose (per `regime/CLAUDE.md:26`) is to label *current state* (NORMAL / SUPPRESSED / EDR / RISK_OFF / PANIC / BOUNCE). The right metric is confusion-matrix accuracy vs. hand-labeled regimes, not forward drawdown lead-time. Right now we have no defensible number for VCG's actual accuracy.

**Cost.** ~1 week. Need a labeled-regime ground truth:
- NBER recession dating (gives high-confidence RECESSION labels)
- NY Fed credit-stress index quantile thresholds (gives credit-RISK_OFF labels)
- Peer-reviewed crisis dating papers (Reinhart-Rogoff, Schularick-Taylor) for cross-check
- Hand-curated VIX-spike events for PANIC labels

Then a `score_vcg_classification_accuracy.py` script: load VCG daily series, align to ground-truth labels, emit per-class precision/recall/F1.

**Unlocks.** A defensible accuracy number to replace the current "0% hit rate" anti-result. Becomes the baseline for any future VCG v2 calibration to beat.

### #3 — Measure the joint VCG + CRI signal

**Why.** `regime/CLAUDE.md:26` explicitly says *"Pair VCG with CRI or a leading vol signal for early-warning use"* — but we've never measured the pair empirically. The whole project policy on joint use rests on an unmeasured claim.

**Cost.** ~3 days. Simple A/B against an in-sample window:
- Compute daily `CRI_high & VCG_RISK_OFF` co-occurrence
- Distribution of forward 1d/5d/10d SPX returns conditional on the joint signal vs. conditional on each marginal
- If the joint distribution has a meaningfully shifted left tail vs. the marginals, the pairing is real; if not, it's policy-by-assumption

**Unlocks.** Either confirms the documented joint-use claim (and we can promote it from "docs say" to "data says") or surfaces that the pairing doesn't add lift — in which case the docs need updating.

### #4 — Add a slow-grind drawdown definition

**Why.** Current `DRAWDOWN_DEFS` all use `window_days ≤ 60`. The 2022 rates bear and the long phase of 2008 were 100+ trading days from peak to trough — they don't fit any current definition cleanly, and that's exactly the regime VCG was designed to flag (sustained credit-vol divergence, not a single-week crash).

**Cost.** ~1 day. Add `DrawdownDefinition(name="Grind", threshold=0.15, window_days=120)` to `DRAWDOWN_DEFS` in `scripts/compare_vcg_lead_time.py`. Re-run.

**Unlocks.** Tests VCG against the drawdown topology it was actually calibrated for. The Fast/Medium/Major definitions came from generic equity-drawdown literature, not from VCG's regime model.

### #5 — Promote the validation framework from VCG-specific to indicator-agnostic

**Why.** `cards/drawdown.py`, `cards/vcg_validation_metrics.py`, and the comparator are mostly indicator-agnostic but named VCG-specific. CRI has a pending revalidation per `cri-validation.ipynb`'s walk-forward gate that would benefit from the same framework.

**Cost.** ~2 days. Rename:
- `cards/vcg_validation_metrics.py` → `cards/regime_validation_metrics.py`
- `scripts/compare_vcg_lead_time.py` → `scripts/compare_regime_lead_time.py` with `--indicator {vcg,cri}` flag
- The `RESEARCH_COMPOSITE_VERSIONS` registry pattern from `cards/vcg_scoring.py` is the model — CRI gets its own equivalent

**Unlocks.** One framework, three indicators. Reuse instead of fork. Critical before #6 (VCG v2) because v2 candidates need the same plumbing.

### #6 — VCG v2 calibration spec

**Why.** Current v1 calibration is "as-ported from xenon (commit `d3cbc08`)" per `regime/CLAUDE.md:25`. The named-crash ±5d window already shows VCG was late on Lehman (SUPPRESSED days −5 through −1, BOUNCE day 0, RISK_OFF day +3). That's a calibration problem, not a proxy problem.

Candidates for v2:
- Regime-aware `VIX_FLOOR` (currently fixed at 30; should adapt to vol-of-vol)
- Continuous PANIC adjustment (currently binary `(1-π)·vcg`; should be a smooth function so VCG doesn't collapse to zero at the regime boundary)
- Separate β windows for HY vs IG (HY responds to credit stress at one timescale, IG at another)
- Possibly a leading-credit-spread component (current OLS is on credit returns only; adding the spread itself as a separate regressor may sharpen the signal)

**Cost.** Big. Own brainstorm + spec under `docs/superpowers/specs/` + plan + implementation. `regime/CLAUDE.md:25` explicitly requires this be its own spec, not a routine PR.

**Why this is #6, not #1**. Largest expected lift to VCG's descriptive accuracy, but also the riskiest — recalibrating a signal that's already in production. We need #2 finished first so we have a real before/after baseline. Otherwise we're recalibrating against vibes.

### #7 — Migration 060: `regime_backtest_runs.archived_at`

**Why.** Currently a verification smoke (id=16, JNK 2024-H1 from the PR #81 verification ladder) is sitting in production DB with no way to mark it as non-canonical short of `DELETE`. Soft-delete is the right move so we don't lose audit history.

**Cost.** Half a day. Add `archived_at TIMESTAMPTZ NULL` column + repository helper (`archive_run(run_id, reason)`). Update `list_research_runs` to exclude `WHERE archived_at IS NULL` by default with an `include_archived=False` flag.

**Unlocks.** Clean archival of smoke/exploration runs without losing them. Also lets us archive the 4 production VCG rows (ids 2, 3, 5) that are superseded by id=6 — currently all 4 are still active in the table, with `find_latest_run` picking by `composite_version + created_at DESC`.

## 3. Recommended sequencing

```
Phase A (right after merge):
  1. NDX/RUT EOD backfill into vol_index_daily
  → Re-run compare_vcg_lead_time.py; document whether verdict changes

Phase B (the actual VCG question):
  2. Regime-classification accuracy via labeled ground truth
  3. Joint VCG + CRI measurement
  4. Slow-grind drawdown definition (Grind = 15% over 120d)

Phase C (framework debt):
  5. Rename framework indicator-agnostic
  7. Migration 060 (archived_at)

Phase D (the big lift, last):
  6. VCG v2 calibration spec
```

## 4. The discipline this enforces

After a null A/B test, the temptation is to design more candidates. But null on an underpowered test is uninformative, not informative — and producing more "FAIL" verdicts without fixing the measurement instrument burns calendar time without producing knowledge.

NDX/RUT backfill (#1) is unsexy compared to a new VCG calibration (#6). But it's the change that gives every future calibration a fair trial. Same for the joint-signal measurement (#3): we've been operating on an unmeasured policy claim about VCG+CRI for the entire life of the regime stack. Measuring it is overdue.

If only one item from this list ships in the next month, make it #1. If two ship, make them #1 and #2.
