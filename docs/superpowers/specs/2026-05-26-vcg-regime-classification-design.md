# VCG Regime-Classification Accuracy — Design Spec

**Status**: v0.2 — patched after review
**Date**: 2026-05-26
**Branch**: `feat/regime-classification-accuracy`
**Supersedes scope**: Phase B1 of the revised roadmap in `docs/research/regime/vcg-next-steps-2026-05-26.md`
**Author note**: This spec is a synthesis of the 12 post-mortem patches against the PR #81 next-steps doc plus a second round of 7 must-fix + 5 should-fix label-contract patches. It does not invent new direction — it crystallizes what was already agreed in review.

---

## 1. Goal

Replace the "0% hit rate" anti-result from PR #81 with a defensible classification-accuracy number for VCG v1 — scored on its **documented job** (label the current regime state), not on a forward-return prediction task it was never designed for.

Output of this work:
- A persisted, immutable VCG v1 baseline classification report.
- A three-state verdict (PASS / FAIL / INCONCLUSIVE) under pre-declared thresholds.
- A failure-mode classification (`signal_sparsity` / `panic_suppression` / `label_mismatch` / `benchmark_coverage` / `adequate_v1`) that becomes the **hard prerequisite** for any future VCG v2 calibration spec.

## 2. Context — why classification, not lead-time

`docs/research/regime/CLAUDE.md` already states this rule:

> VCG is **descriptive**, not predictive. The named-crash ±5d window in `vcg-methodology.md` §6.3 shows VCG was late on Lehman (SUPPRESSED days −5 through −1, BOUNCE day 0, RISK_OFF day +3). Pair VCG with CRI or a leading vol signal for early-warning use.

PR #81 tested VCG on forward drawdown lead-time and (predictably) returned 0% hit rate. The HYG baseline scored the same 0% — that is a **measurement-instrument signal**, not a verdict on the indicator. The right test for a descriptive classifier is confusion-matrix accuracy against pre-declared regime labels.

### 2.1 Construct-validity framing — read this before anything else

VCG v1 derives from VIX / VVIX / credit-proxy relationships. The Level-1 ground-truth labels in §6 also derive from VIX / VVIX / credit-stress percentiles. **This is not a coincidence — and not an error**, but it must be framed honestly:

> **This classification score measures descriptive agreement with an externally defined market-state taxonomy. It is not an alpha test, a return-prediction test, or a trading-signal validation. Because VCG and the Level-1 taxonomy both use volatility/credit information, the report MUST frame the result as construct validity, not independent predictive evidence.**

The final executive summary of every report this spec produces MUST quote that paragraph verbatim. Removing it during refactoring is a contract violation.

## 3. Revised roadmap (incorporated patches)

This spec implements **Phase B1**. The full revised sequencing — patched per the post-mortem review — is reproduced here so out-of-scope and prerequisite boundaries are unambiguous:

```
Phase A — Make the measurement table clean and benchmark-complete
  A1. Migration 060 archived_at column on regime_backtest_runs        (was #7, promoted to Phase A as hygiene)
  A2. NDX/RUT EOD backfill into vol_index_daily                       (was #1)
  A3. Re-run composite comparator with SPX/NDX/RUT
  A4. Amend PR #81 validation report with "post-backfill verdict"

Phase B — Measure VCG on its actual job
  B1. VCG regime-classification accuracy report   ← THIS SPEC        (was #2)
  B2. VCG + CRI joint-signal report                                   (was #3)
  B3. Add Grind_15_120 as topology probe, not promotion gate          (was #4)

Phase C — Generalize framework
  C1. Rename validation metrics to indicator-agnostic modules         (was #5)
  C2. Add CRI validation harness

Phase D — Only then start VCG v2
  D1. Brainstorm VCG v2 failure modes (gated by B1+B2 outputs)
  D2. Write VCG v2 calibration spec
  D3. Implement v2 as research candidate only
  D4. Promote only after v1-vs-v2 report
```

## 4. Prerequisites

### 4.1 Hard prerequisite (blocks implementation)
- **A1 (Migration 060 — `archived_at` on `regime_backtest_runs`)** — required so smoke runs produced during development can be archived without `DELETE`, keeping audit history clean.

### 4.2 Conditional prerequisite (does not block; affects one failure mode)
- **A2 (NDX/RUT EOD backfill into `vol_index_daily`)** — required **only** to evaluate the `benchmark_coverage` failure mode in §9. If NDX/RUT are absent, the report MUST mark `benchmark_coverage = not_evaluable` (a distinct state from "did not match") and proceed with SPX-only accuracy as the headline.

### 4.3 No prerequisite for spec / plan review
Drafting + spec review + implementation-plan review of this work do not block on Phase A. **Code implementation** starts after A1 lands.

## 5. Out of scope

Explicitly **not** in this spec — these belong to later phases per §3:
- Joint VCG + CRI signal measurement (Phase B2)
- Slow-grind drawdown definition (Phase B3)
- Framework rename to indicator-agnostic (Phase C1/C2)
- Any change to VCG v1 calibration constants (Phase D)
- Any production-scanner code path change (research-only — default-deny gate per Hard Guarantee #2 from PR #81)

## 6. Ground-truth label framework

The single largest risk in this work is producing subjective daily labels that can be tuned post-hoc to match VCG's output. To rule that out, labels are split into two strictly-separated layers with hard rules, and **the source of truth for every threshold is a frozen YAML file**, not this spec and not the implementation plan.

### 6.1 Hard rules on labels (pre-declared, non-negotiable)

1. **YAML is the immutable replay source**: All threshold values, source-series IDs, and mapping rules are committed in YAML files under `docs/research/regime/ground-truth-labels/` **before** any scoring code runs. This spec describes methodology. The implementation plan describes implementation steps. **Neither is the source of truth for threshold values** — the YAML is. The label contract version is bumped on every edit; old versions remain in git history for replay.
2. **Mechanically derived**: Wherever possible, labels come from deterministic functions of objective market data (price, vol indices, FRED series). No discretionary daily classification.
3. **Hand-curation only for event windows**: When human judgment IS needed (e.g., naming the Lehman week or the Aug-2015 China devaluation episode), it is restricted to declaring **window start/end dates** for named events. The per-day label inside the window is still derived mechanically. Named-crisis windows carry an explicit `use_for_headline: false` flag — they are sanity overlays, not headline inputs.
4. **Causality respected**: Any label that uses lagged data (e.g., NBER recession dating with its 6-18 month publication lag) is marked as **post-hoc** in the report. Post-hoc labels are usable as sanity checks; they are NOT usable for trading-style evaluation.

### 6.2 Level 1 — objective market-state labels (primary scoring target)

Mechanically derived from market data available on day T (no lookahead):

| Label component | Source | Series |
|---|---|---|
| VIX percentile (252d rolling) | `vol_index_daily` | symbol=VIX |
| VVIX percentile (252d rolling) | `vol_index_daily` | symbol=VVIX |
| Realized vol percentile (252d rolling of 21d close-to-close) | `vol_index_daily` | symbol=SPX |
| SPX trailing drawdown (peak over 252d) | `vol_index_daily` | symbol=SPX |
| Credit-stress percentile (252d rolling) | FRED via `sources/fred.py` | **Primary: `NFCI` (Chicago Fed National Financial Conditions Index). Sensitivity-only: `ANFCI`.** |

**Credit-stress series — choice locked at spec time, not plan time**:

- **Primary: `NFCI`** (FRED series id `NFCI`). Captures the raw financial-conditions stress signal. Chosen over STLFSI because STLFSI was discontinued in 2022 and the methodology break is not worth absorbing for a long-history backtest.
- **Sensitivity-only: `ANFCI`** (the residualized variant — Chicago Fed NFCI adjusted for macroeconomic conditions). May appear in the report's sensitivity section. Cannot change the headline verdict.

**Frequency / alignment / missing-data rules** (pinned in `level1-thresholds.yaml`):

- NFCI is published weekly (Wednesday close, reflecting prior week's data). Aligned to trading days by **forward-filling the latest available observation** through to the next release.
- Missing data: if any single Level-1 component is missing for a given day, that day is excluded from scoring (not silently imputed).
- Release-lag: NFCI is post-hoc by typically 3-5 calendar days. The report frames any credit-stress-dependent classification as **non-tradable signal**. The classification verdict is still valid as descriptive agreement; it just cannot be interpreted as a trading signal.
- Vintage / revisions: NFCI is revised after release. The label contract pins which vintage was used (latest-available-as-of-`run_at_date`). Replays from prior vintages produce different labels — that's expected and explicit.

### 6.3 Level 2 — historical crisis overlay labels (sanity-check only)

Used for cross-validation, NOT for the primary accuracy score. Every Level-2 label carries `use_for_headline: false` in YAML.

- **NBER recession dating** — FRED series `USREC`. Marks RECESSION background regime. Post-hoc.
- **Named-crisis windows** — committed as YAML at `docs/research/regime/ground-truth-labels/named-crises.yaml`. Each entry: `name`, `start_date`, `end_date`, `provenance` (paper / Fed statement / news archive citation), `use_for_headline: false`.
- **Hand-curated VIX-spike events** — windows only (start/end dates), not per-day labels. Same YAML.

### 6.4 Label-to-VCG-class mapping (methodology — values in YAML)

VCG produces 6 classes. Level 1 alone does not naturally produce all 6 — the mapping is therefore declared explicitly in methodology terms here. **All threshold variables (P_SUPP, P_RO, P_PANIC, DD_EDR, N_BOUNCE) are pinned in `level1-thresholds.yaml`**, not in this spec and not in the implementation plan:

| VCG class | Ground-truth condition (Level 1, methodology) |
|---|---|
| NORMAL | All Level-1 percentiles in [25, 75] AND drawdown < 5% |
| SUPPRESSED | VIX pct < P_SUPP AND realized-vol pct < P_SUPP AND credit-stress pct < P_SUPP |
| EDR (Equity Drawdown Regime) | SPX 1-month drawdown ≥ DD_EDR |
| RISK_OFF | credit-stress pct ≥ P_RO OR (VIX pct ≥ P_RO AND VVIX pct ≥ P_RO) |
| PANIC | VIX pct ≥ P_PANIC AND realized-vol pct ≥ P_PANIC |
| BOUNCE | See state-machine definition below |

### 6.5 BOUNCE state-machine (locked here, not deferred to plan)

BOUNCE is the only Level-1 class whose definition depends on transition history rather than instantaneous percentiles. To avoid the "BOUNCE never has samples because EDR keeps suppressing it" pathology, the state-machine semantics are locked here:

```
Trigger condition:
  BOUNCE window opens on day T+1 if day T was labeled PANIC or RISK_OFF
  AND day T+1 is no longer labeled PANIC or RISK_OFF (transition out).

Duration:
  BOUNCE persists for N_BOUNCE trading days after the trigger.

Reactivation:
  If PANIC or RISK_OFF reactivates during the BOUNCE window,
  the window terminates immediately and the new label takes precedence.
  When the new stress episode ends, a new BOUNCE window opens at +1.

Coexistence with EDR:
  EDR can be active during a BOUNCE window. Class precedence (below) decides
  which is reported as the headline label for that day.
```

### 6.6 Class precedence (locked here, not deferred)

When multiple conditions match for the same day:

```
PANIC > RISK_OFF > BOUNCE > EDR > SUPPRESSED > NORMAL
```

Rationale: BOUNCE was moved above EDR (the post-mortem patch §5 explicitly flagged this). Without it, BOUNCE samples vanish whenever a stress episode ends but drawdown remains > DD_EDR — which is essentially every realistic post-stress recovery. With BOUNCE above EDR, the BOUNCE class has a meaningful sample population to score against.

## 7. Scoring methodology

For each day in the eval window, compare VCG v1's label (from `regime_backtest_daily`) against the Level-1 ground-truth label. Emit:

1. **Per-class precision / recall / F1**, with sample counts.
2. **Macro-F1** computed **over eligible classes only** (see §8 for eligibility).
3. **Weighted-F1** weighted by ground-truth class prevalence.
4. **Cohen's κ** (chance-adjusted agreement). Reported as a secondary diagnostic — **not the headline verdict gate**. Macro-F1 is the gate; κ is shown alongside so readers can sanity-check macro-F1 against an imbalance-robust measure.
5. **Confusion matrix overall** + **per-period** (pre-2020 / 2020-COVID / 2021-2022-rates / 2023-2026-AI — same buckets as PR #81's comparator for cross-reference).
6. **Level-2 sanity overlay**: for each named crisis window in §6.3, report VCG label distribution inside the window vs. baseline. Not part of the headline verdict (every Level-2 entry has `use_for_headline: false`).

### 7.1 Required executive-summary content

Every report renderer output MUST begin with §2.1's construct-validity paragraph verbatim. The verdict, failure mode, macro-F1, and Cohen's κ appear immediately after. The construct-validity framing is structurally first because it is the most likely thing to be misread if the report is read in isolation.

### 7.2 Eval window

Full canonical VCG v1 history (2007-01-03 → present). **No train/test split is claimed**. This is a fixed-taxonomy descriptive agreement report — there is no forward-prediction semantics, so no holdout window is required or meaningful. The report MUST state this explicitly in the methodology section so a future reader does not ask "where's the holdout?"

## 8. Three-state verdict — PASS / FAIL / INCONCLUSIVE (eligible/core-class model)

The post-mortem (patch §11 and review §6) flagged two issues with binary FAIL:
1. Underpowered tests get misread as candidate-bad.
2. A naively strict "any class INCONCLUSIVE → overall INCONCLUSIVE" rule means rare classes (PANIC, BOUNCE) make every report inconclusive.

The eligible/core-class model resolves both:

```
Core classes:   NORMAL, SUPPRESSED, EDR, RISK_OFF   (always present in any meaningful history)
Rare classes:   PANIC, BOUNCE                       (legitimately rare)

For each class c:
  n_truth(c) = number of ground-truth days labeled c
  if n_truth(c) < N_MIN_CLASS_DAYS:
    class_state(c) = INCONCLUSIVE
    (still reported per-class; just doesn't count toward the headline)
  else:
    class_state(c) = COMPUTED (F1 is meaningful)

Headline macro-F1 = mean of F1 over eligible (COMPUTED) classes only.
Report class coverage separately: which classes contributed to the headline.

Overall verdict:
  if any CORE class is INCONCLUSIVE:
    overall_verdict = INCONCLUSIVE
    report names which core class(es) lacked data
  elif fewer than K_MIN_CORE_ELIGIBLE core classes are eligible:
    overall_verdict = INCONCLUSIVE
  elif macro_F1 >= MACRO_F1_PASS:
    overall_verdict = PASS
  else:
    overall_verdict = FAIL

Rare-class state is ALWAYS reported per-class but never independently invalidates
the headline. PANIC / BOUNCE under-power triggers panic_suppression mode in §9
when applicable, but doesn't invalidate accuracy on the rest of the taxonomy.
```

Threshold variables (`N_MIN_CLASS_DAYS`, `K_MIN_CORE_ELIGIBLE`, `MACRO_F1_PASS`) are pinned in `level1-thresholds.yaml` **before any scoring code runs**.

## 9. Failure-mode classification (gating output for Phase D)

Per patch §8, VCG v2 work cannot start without a failure-mode classification of v1. This spec's report MUST emit one **primary** mode and a list of **secondary** modes, with quantitative trigger conditions (not human interpretation):

```yaml
panic_suppression:
  trigger:
    n_truth(PANIC) >= N_MIN_CLASS_DAYS
    AND n_pred(PANIC) < PANIC_SUPPRESSION_RATIO * n_truth(PANIC)
  meaning: "Indicator never fires PANIC despite ground-truth PANIC days."

signal_sparsity:
  trigger:
    for any core class c (NORMAL, SUPPRESSED, EDR, RISK_OFF):
      n_pred(c) < SPARSITY_RATIO * n_truth(c)
  meaning: "Indicator under-fires one or more core classes."

label_mismatch:
  trigger:
    macro_F1 < MACRO_F1_PASS
    AND no class fires below SPARSITY_RATIO of its ground-truth count
    AND confusion concentrated in the top-2 off-diagonal pairs of the
        confusion matrix (those 2 pairs account for >= MISMATCH_CONCENTRATION
        fraction of total disagreement)
  meaning: "Calibration drift on specific boundaries, not class-structure failure."

benchmark_coverage:
  trigger:
    Phase A2 NDX/RUT data available
    AND per-universe macro_F1 range (max - min over {SPX, NDX, RUT}) > BENCH_RANGE
  evaluation:
    If Phase A2 backfill is NOT available, this mode is `not_evaluable`,
    NOT `not_triggered`. The two states must be distinguishable in the report.
  meaning: "Indicator works in one universe but not another."

adequate_v1:
  trigger:
    overall_verdict == PASS
    AND no other failure mode triggers
  meaning: "v2 work not warranted."
```

**Precedence (single primary mode emitted)**:

```
1. panic_suppression  (most specific — PANIC class)
2. signal_sparsity    (general — any core class)
3. label_mismatch     (calibration drift)
4. benchmark_coverage (universe-dependent — requires post-A4 to evaluate)
5. adequate_v1        (verdict PASS only)
```

All triggered modes are listed as `secondary_modes`. Quantitative trigger ratios (`PANIC_SUPPRESSION_RATIO`, `SPARSITY_RATIO`, `MISMATCH_CONCENTRATION`, `BENCH_RANGE`) live in `level1-thresholds.yaml`. PASS implies primary `adequate_v1` with no secondaries.

## 10. Persistence

### 10.1 Where the report lives (locked: Option A — payload-only)

**Locked decision: reuse `regime_backtest_runs` + `regime_backtest_daily` with classification payload in JSONB**. The post-mortem review §7 explicitly rejected adding new daily columns:

> Classification label is research payload, not core daily-table schema. No new columns. All classification-specific daily fields live in payload.

Concrete shape:

- `regime_backtest_runs`: `run_scope='research'`, `composite_method='classification_accuracy'`. The full classification metrics (per-class F1, macro-F1, κ, confusion matrix, verdict, primary mode, secondary modes) serialize into `summary.extras.classification`.
- `regime_backtest_daily.payload` JSONB carries:
  - `vcg_label` — VCG's label for the day
  - `truth_label` — Level-1 ground-truth label
  - `match` — boolean
  - `label_components` — VIX_pct / VVIX_pct / RV_pct / DD / credit_stress_pct (for replay debugging)
  - `label_version` — value from `label-version.yaml`

**No new daily columns. No new migrations for this work** beyond A1 (the archived_at column, which is a Phase A prereq).

### 10.2 Repository module
**MUST NOT extend `repository.py`** (per CLAUDE.md "Never extend repository.py" rule citing the 5000-line precedent). New module: `src/uw_scan/storage/regime_classification_repository.py`. The shim in `repository.py` only re-exports for compatibility.

### 10.3 Immutability
Once a classification run completes (`mark_run_completed`), its rows are immutable. Updating thresholds = a new run row, not a mutation. Migration 060 (`archived_at`, Phase A1) is the soft-delete escape hatch for smoke runs.

### 10.4 Ground-truth labels — frozen YAML contract

Committed at `docs/research/regime/ground-truth-labels/`:

| File | Contents |
|---|---|
| `level1-thresholds.yaml` | Frozen Level-1 threshold values: `P_SUPP`, `P_RO`, `P_PANIC`, `DD_EDR`, `N_BOUNCE`, `N_MIN_CLASS_DAYS`, `K_MIN_CORE_ELIGIBLE`, `MACRO_F1_PASS`, `PANIC_SUPPRESSION_RATIO`, `SPARSITY_RATIO`, `MISMATCH_CONCENTRATION`, `BENCH_RANGE`. Also FRED series IDs. |
| `named-crises.yaml` | Level-2 event windows with provenance. Every entry: `use_for_headline: false`. |
| `vcg-source.yaml` | Pinned VCG source run reference: `run_id`, `composite_version`, `credit_proxy`, `run_scope`. Never resolved at runtime via `find_latest_run` — replay must reference the exact pinned run. |
| `label-version.yaml` | `version: 1`, change-control rule (bump version on any edit; old version remains for replay). |

## 11. Inputs

| Input | Source | Status |
|---|---|---|
| VCG daily labels | `regime_backtest_daily` for the canonical VCG v1 run **pinned in `vcg-source.yaml`** | Available |
| VIX / VVIX daily | `vol_index_daily` | Available |
| SPX prices (drawdown + realized vol) | `vol_index_daily` symbol=SPX | Available |
| NDX / RUT prices | `vol_index_daily` symbol=NDX, RUT | **Conditional — required ONLY for benchmark_coverage failure-mode evaluation. Absence → `benchmark_coverage = not_evaluable`, not a blocker.** |
| NBER recession dating | FRED series `USREC` via `sources/fred.py` | Available (verify integration in implementation plan) |
| NFCI credit-stress index | FRED series `NFCI` via `sources/fred.py` | Available (verify integration in implementation plan) |
| ANFCI (sensitivity) | FRED series `ANFCI` via `sources/fred.py` | Available (sensitivity overlay only) |
| Named-crisis windows | New YAML under `docs/research/regime/ground-truth-labels/` | To be authored as part of this work |

## 12. Acceptance criteria

Drawn from patch §12 + review §7-12 refinements:

- [ ] **YAML label contract committed before any scoring code is written or run.** `level1-thresholds.yaml`, `named-crises.yaml`, `vcg-source.yaml`, `label-version.yaml` exist in the worktree before any `score_*.py` script runs.
- [ ] All labels deterministic and reproducible from the committed YAML + the input series. No random sampling. No per-day hand classification.
- [ ] Output includes per-class precision / recall / F1 with sample counts.
- [ ] Output includes confusion matrix overall AND by period (4 period buckets matching PR #81's comparator).
- [ ] Output includes macro-F1, weighted-F1, Cohen's κ. Macro-F1 is the verdict gate; κ is reported alongside but does not gate.
- [ ] Three-state verdict (PASS / FAIL / INCONCLUSIVE) implemented per §8 with eligible/core-class model. Rare classes (PANIC/BOUNCE) do not by themselves invalidate the headline.
- [ ] If verdict is INCONCLUSIVE, report explicitly names which core class(es) lacked data and how many days they had.
- [ ] Failure-mode classification emitted per §9 with **quantitative** trigger conditions (no human interpretation). Primary mode + secondary modes both reported.
- [ ] `benchmark_coverage` is `not_evaluable` (distinct from `not_triggered`) when Phase A2 backfill is absent.
- [ ] §2.1 construct-validity paragraph appears verbatim in the executive summary of every report.
- [ ] Eval window is full VCG v1 history; report states "no train/test split — descriptive agreement only" explicitly.
- [ ] VCG v1 baseline persisted as an immutable run; replay yields byte-identical report bytes (deterministic markdown rendering, no embedded wall-clock timestamps in the report body).
- [ ] No production scanner change. Research-only `run_scope`. Default API filters exclude `run_scope='research'` from the production endpoint (same Hard Guarantee #2 that PR #81 established).
- [ ] No extension of `src/uw_scan/storage/repository.py`. New persistence in its own module.
- [ ] No new daily-table columns on `regime_backtest_daily`. All classification per-day data goes in `payload` JSONB.
- [ ] AST/source-text guard: classification scoring loop performs zero DB queries inside the per-day loop (same spec §15 lock-in pattern as `compare_vcg_lead_time.py`).
- [ ] VCG source is pinned via `vcg-source.yaml`, NOT via `find_latest_run`. The pin is a YAML-committed run_id.

## 13. Hard prerequisites this spec creates for downstream work

Per patch §8, **VCG v2 spec (Phase D) cannot start until** all four are true:

1. ✅ VCG v1 classification report exists — produced by this spec
2. ⬜ VCG + CRI joint report exists — produced by Phase B2 (separate spec)
3. ⬜ SPX/NDX/RUT benchmark coverage report exists — produced by Phase A4 amendment
4. ⬜ v1 failure mode classified as one of: `signal_sparsity` / `panic_suppression` / `label_mismatch` / `benchmark_coverage` — produced by §9 of this spec

Per patch §7, **Framework rename to indicator-agnostic (Phase C) requires**:
1. VCG lead-time comparator run with SPX/NDX/RUT — Phase A3
2. VCG classification scoring has a first report — **this spec**
3. CRI has one concrete validation target selected — separate (out of this spec's scope)

## 14. Open questions (deferred to the implementation plan — NOT to YAML, NOT to spec)

These are *implementation-mechanical* questions, not threshold values. Threshold values all live in YAML per §6.1.

1. **YAML schema details** — exact key names, nested structure, comment conventions. Plan picks.
2. **Eval window start date** — full history starts 2007-01-03 (VCG v1 canonical run start). Plan confirms the exact end-date convention (latest closed trading day vs. fixed cutoff for replay determinism).
3. **Period bucket boundaries** — adopt PR #81's 4 buckets verbatim (pre-2020 / 2020-COVID / 2021-2022-rates / 2023-2026-AI) OR refine. Recommendation: adopt as-is for cross-reference clarity unless plan author identifies a strong reason.
4. **First-pass `named-crises.yaml` content** — author the initial list of named windows (Lehman 2008-09-15 → 2009-03-09, Eurozone 2011-08-01 → 2012-09-06, China devaluation Aug-2015, Q4-2018 vol regime, COVID 2020-02-19 → 2020-03-23, 2022 rates bear, 2023 SVB week). Provenance for each.

(Open questions #1, #2 from v0.1 — persistence shape, credit-stress series — are now LOCKED in §10.1 and §6.2 respectively.)

## 15. Non-goals — explicitly NOT this spec

To prevent scope creep:

- ❌ Re-running the lead-time comparator (Phase A3)
- ❌ Joint VCG + CRI signal measurement (Phase B2)
- ❌ Adding new drawdown definitions (Phase B3)
- ❌ Renaming `cards/vcg_validation_metrics.py` → `cards/regime_validation_metrics.py` (Phase C1)
- ❌ Touching VCG v1 calibration constants in `src/uw_scan/cards/vcg_scoring.py` (Phase D)
- ❌ Any change to `web/app/regime/page.tsx` UI — this is a research artifact, not a user-facing feature
- ❌ Any change to `api/routers/regime.py` — research run readers go through a separate router if surfaced at all
- ❌ New daily-table columns on `regime_backtest_daily` — payload JSONB only

## 16. Disciplinary check — does this spec match the post-mortem (both rounds)?

### Round 1 patches (PR #81 post-mortem)
| Patch | Captured in spec? |
|---|---|
| §1 — measurement vs candidate framing | §2 |
| §2 — agreed priority logic | §3 |
| §3 — NDX/RUT cannot alone fix signal sparsity | §4, §9 |
| §4 — Level 1 + Level 2 label split | §6 |
| §5 — VCG+CRI joint signal must measure left tail | Out of scope (Phase B2) — §15 |
| §6 — slow-grind definitions as topology probe family | Out of scope (Phase B3) — §15 |
| §7 — framework rename prerequisites | §13 |
| §8 — VCG v2 hard prerequisites | §13 |
| §9 — `#7 archived_at` promoted to Phase A | §3, §4 |
| §10 — revised Phase A-D sequencing | §3 |
| §11 — INCONCLUSIVE three-state verdict | §8 |
| §12 — strict per-step acceptance criteria | §12 |

### Round 2 patches (v0.1 review)
| Patch | Captured in spec? |
|---|---|
| Must-fix 1 — A2 NDX/RUT downgrade to conditional | §4.2, §11 |
| Must-fix 2 — Thresholds → frozen YAML, not implementation plan | §6.1, §6.4, §10.4, §14 |
| Must-fix 3 — Construct-validity / circularity disclaimer | §2.1, §7.1, §12 |
| Must-fix 4 — Credit-stress series pinned NOW | §6.2 (NFCI primary, ANFCI sensitivity) |
| Must-fix 5 — BOUNCE state machine + revised precedence | §6.5, §6.6 |
| Must-fix 6 — Eligible/core-class INCONCLUSIVE model | §8 |
| Must-fix 7 — Persistence payload-only, no new daily columns | §10.1, §15 |
| Should-fix 8 — vcg_source pinned via YAML | §10.4 (`vcg-source.yaml`), §11, §12 |
| Should-fix 9 — Cohen's κ reported alongside, not gate | §7, §12 |
| Should-fix 10 — Quantitative failure-mode trigger conditions | §9 |
| Should-fix 11 — Named-crisis use_for_headline:false | §6.1, §6.3, §10.4 |
| Should-fix 12 — Eval window non-predictive marker | §7.2, §12 |

All round-1 and round-2 patches captured.

---

## Next step

After spec commit, invoke the **writing-plans** skill to produce `docs/superpowers/plans/2026-05-26-vcg-regime-classification-accuracy.md` — the bite-sized TDD plan with exact file paths, code, and tests.

**Plan-writing pre-conditions** (must be true before plan execution begins):
1. This spec is committed on `feat/regime-classification-accuracy`.
2. Phase A1 (Migration 060 `archived_at`) is merged to main — **separate PR, separate plan**.
3. Phase A2 (NDX/RUT backfill) is recommended but NOT blocking — if absent, plan produces a report with `benchmark_coverage = not_evaluable`.
