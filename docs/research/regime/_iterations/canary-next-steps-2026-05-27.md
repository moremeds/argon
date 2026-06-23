# 5% Canary — Next Steps After v1 Merge (PR #83)

**Date**: 2026-05-27
**Status**: roadmap / decision memo. Follow-up to `canary-5yr-executive-summary.md` (PR #83, merged via `9657dea`).
**Composite version (in production)**: `1` (`score_form=linear`, frozen calibration in `canary-calibration-v1.json`)
**Data on hand**: `uw_scan.canary_snapshots` — 3,843 rows, 2011-02-08 → 2026-05-21 (verified)
**Run ids in `regime_backtest_runs`**: `18` (final OOS), `19–24` (walk-forward WF-1..WF-6), `25` (extra robustness — candidate for archival), `26` (canonical robustness)

---

## TL;DR

- v1 shipped honest about what it is: a **vol-resolution predictor with speed-as-context**. The 15-year backfill + walk-forward validated that framing (5/6 windows pass 60d AUC ≥ 0.58, vol-only ≥ composite at every horizon × every subset). PR #83 is in production at `composite_version=1`.
- Four v2 candidates surfaced in v1 §10 (v2-A through v2-D). They split cleanly into **two cheap measurement steps** that should run before any score-machinery change, and **two design-stage candidates** that require a real spec.
- **The user's standing intuition** — *"WATCH overfires, BUY isn't strong enough when fear is max'd"* — maps to **v2-C** (WATCH band overfire) and **v2-D** (capitulation scorer). The first is measurable today; the second needs a literature pass.
- **Recommended phase-A action**: re-run `--form-sweep` against the full 2011-2026 dataset (cheap; can falsify or re-confirm the `linear` pick that was originally chosen against only 2015-2019). This is the single highest-information action for the dollar.
- **Recommended phase-B action**: file v2-A / v2-B / v2-C / v2-D as GitHub issues so the design conversations have a home, then decide whether to invest in v2-D's literature pass or v2-A's architecture change first.
- **Calibration discipline**: do **not** retune calibration thresholds against the same 15-year dataset the walk-forward was validated against. That would invalidate the validation. Any v2 calibration must reserve a holdout window.

---

## 1. Where we are post-merge

| Artifact | State | Notes |
|---|---|---|
| `canary_snapshots` (full dataset) | 3,843 rows, 2011-02-08 → 2026-05-21 | `MIN_ALIGNED_BARS=350` warm-up gate against VIX3M (2009-09-18 first bar) is binding |
| `canary-calibration-v1.json` | `composite_version=1`, `score_form=linear`, v0.1 priors | Train window 2007-2014 per methodology §3; **never re-calibrated against the 2011 backfill** |
| Walk-forward verdict | 5/6 windows pass 60d ≥ 0.58 | WF-2 (2017-18 Volmageddon) the lone failure at 0.569 |
| Robustness verdict | Composite 0.620 / 0.627 / 0.619; vol-only beats by 0.01-0.04 | Excluding 2020-Q4 lifts 60d to 0.665 |
| Within-band rank | NONE / WATCH carry signal (AUC 0.58-0.63); BUY band internally anti-predictive (0.35-0.45) | Regression-to-mean within BUY |
| API contract | `composite_version=1` baked into snapshot rows + validation panel | Any breaking change requires a `COMPOSITE_VERSION` bump and re-backfill |
| OOS gate (`tests/integration/regime/test_canary_oos_gate.py`) | Locked to v1 `LAST_KNOWN_AUC_*` constants | Recalibration changes >0.02 AUC require updating these per `docs/research/regime/CLAUDE.md:25` |

The "we just merged a 15-year validation" position is the strongest the indicator has ever been in. The right thing to protect is the validation, not the calibration constants.

---

## 2. The honest read of the v2 questions

Three of the four v2 candidates (A, B, C) are about **band / score arithmetic**, which is cheap to test. v2-D is about **adding a new scorer**, which is design work. The cheap items should not be gated on the expensive one.

The vol-only-beats-composite finding (v2-A) is the most counter-intuitive — it says the speed layer is *mildly net negative* for rank prediction across 15 years, despite being central to the design hypothesis. Either:
- The speed layer truly adds nothing to rank, and v2-A is right (drop it from the composite, keep it as state/veto only), OR
- The speed layer adds rank in regimes the AUC averaging hides (e.g. it's predictive during CCA-active days but those days are too few to move the mean across 3,843 rows)

Item v2-A is in the **"test before you change"** bucket. Items v2-B and v2-C are in the **"measure on the full dataset, then decide"** bucket. Item v2-D is the only one in the **"new design needed"** bucket.

---

## 3. Ranked next-step map

### #1 — Re-run `--form-sweep` against the full 2011-2026 dataset (highest leverage)

**Why first.** The current `score_form=linear` was picked by `cmd_form_sweep` at `scripts/backtest_canary.py:408` running against `VALID_START=2015-01-01..VALID_END=2019-12-31` (`scripts/backtest_canary.py:43-44`) — five years of relatively benign vol regime. We now have ~3× more data including Euro crisis 2011, China 2015, Volmageddon, COVID, 2022 Fed pivot, 2026 dip. A re-sweep on the full dataset tests whether `linear` is still the winner, or whether `convex` / `concave` / `sigmoid` would compress middle scores into NONE (which is what v2-C's "WATCH overfires" hypothesis needs).

**Cost.** ~1 hour. The mechanism already exists. The change is a one-line widening of the sweep window (or a `--full-history` flag) in `cmd_form_sweep` to use the snapshot table's full range instead of `VALID_*`. Persists 4 rows to `regime_backtest_runs` (one per form) with `params.phase='form_sweep_full'`.

**Acceptance.**
- Each of the 4 forms returns 5d/20d/60d AUC against the full 3,843-row dataset.
- A row is committed to `regime_backtest_runs` per form (4 rows total) with `params.phase='form_sweep_full'`.
- Band distribution drift is reported (% NONE / WATCH / BUY / STRONG_BUY per form).

**Expected outcomes.**
- *(a)* `linear` still wins — v2-C "WATCH overfires" requires a separate fix, not a form change.
- *(b)* A different form wins by ≥0.02 AUC on 2+ horizons — v2-C has its solution and we have a candidate for v2 with empirical backing.
- *(c)* Forms tie — the score-form choice is regime-insensitive and the WATCH overfire must be addressed via threshold change, not arithmetic.

This action is the smallest possible step that materially changes what we know about the system. Do this before any of #2-#6 below.

### #2 — File v2-A / v2-B / v2-C / v2-D as GitHub issues

**Why.** Right now the v2 candidates exist only in §10 of `canary-5yr-executive-summary.md`. Without issues, there is no place to attach further evidence (e.g. the output of #1), comment threads, or links to related PRs. Issues become the persistent home for these design conversations.

**Cost.** 30 minutes. Each issue includes:
- Hypothesis (from §10)
- Current evidence (AUC numbers, run ids)
- Falsification criteria (what would make us drop the candidate)
- Effort estimate (S / M / L)
- Whether it requires a `COMPOSITE_VERSION` bump

**Unlocks.** Allows the v2 conversation to happen async / with collaborators / over weeks without losing context. Also makes it easy to link any future PR to the originating hypothesis.

### #3 — Decide on v2-A (drop speed from composite) using the full-dataset re-sweep result

**Why.** v2-A is the architecture change with the strongest empirical case — vol-only beats composite at every horizon × every subset by 0.01-0.04 AUC. But "drop speed from score, surface state separately" is a breaking API change (the `score` field changes semantics), so the cost is real.

**Cost.** Medium. Steps:
- New API field `vol_resolution_score` alongside `score`, dual-publishing during the transition
- `COMPOSITE_VERSION` bump to 2 (per methodology §1, the spec says a non-backward-compatible composite must bump)
- Full backfill rerun with `--overwrite` (~10 min)
- Methodology doc update
- OOS gate `LAST_KNOWN_AUC_*` constants updated to the v2 values
- Validation panel UI updates to show the two scores side-by-side

**Gate before doing this.** The full-dataset form-sweep (#1) must complete first. If a non-`linear` form closes most of the vol-vs-composite gap, v2-A loses urgency.

**Falsification.** If `vol_only_auc - composite_auc < 0.01` across all horizons in the new form-sweep, v2-A is not worth the API break. Keep speed in the composite and just promote `vol_resolution_score` to a sibling field.

### #4 — Decide on v2-B (STRONG_BUY threshold too high)

**Why.** Zero STRONG_BUY hits across 15 years including GFC-era stress (Euro crisis 2011 → max score not observed there because the warm-up gate excludes pre-2011-02-08; but Volmageddon, COVID 2020, 2022, 2026 all available — max in dataset is 66.36 on 2020-11-12). Either the threshold (75) is correct for once-in-a-generation events and 15 years is not long enough, or it's miscalibrated.

**Cost.** Small. Band thresholds are post-score classifications (per `canary_scoring.derive_band`) — changing them does **not** require a `COMPOSITE_VERSION` bump under the spec's invariant. Three candidate thresholds:
- Lower STRONG_BUY to 60 — would fire ~12 days in 15 years (the 2020-11-12 cluster plus any score>60 days)
- Lower STRONG_BUY to 55 — would fire ~50 days, overlapping the BUY band's high end
- Eliminate STRONG_BUY entirely — collapse to NONE/WATCH/BUY three-band model

**Falsification.** The within-band AUC table (v1 §9) showed BUY band is internally anti-predictive (0.35-0.45). If we extend the same analysis to a hypothetical "STRONG_BUY ≥ 60" band, internal AUC is likely also anti-predictive — in which case the threshold change is cosmetic, not informative.

**Recommendation.** Defer until v2-C is resolved. STRONG_BUY's existence as a band is part of the user-facing contract; changing it shouldn't be done before the score arithmetic itself is settled.

### #5 — Decide on v2-C (WATCH band overfiring; within-BUY anti-predictive)

**Why.** WATCH is 31-39% of all days vs. design intent of ~25%. Within-BUY anti-predictivity is a regression-to-mean signature. The user's stated intuition — *"WATCH state is a bit too many"* — aligns with this.

**Cost depends on root cause** (which #1 will help diagnose):
- *If the form-sweep picks `convex` / `sigmoid`*: change the form, refit thresholds. Score-machinery-level change. Requires `COMPOSITE_VERSION` bump.
- *If the form-sweep stays `linear`*: tighten WATCH threshold from 25 upward (e.g. to 30). Band-only change, no version bump. But this just moves days from WATCH to NONE — doesn't fix the within-BUY anti-predictivity.
- *If the within-BUY problem is structural*: the score may need an entirely different post-BUY-entry treatment (e.g. cap the score at 50 once it enters BUY and use a separate "BUY intensity" signal for further rank).

**Falsification.** Run #1 first. The output determines which sub-path is live.

### #6 — Brainstorm v2-D (capitulation scorer)

**Why.** The user's intuition that the score should peak during max fear (capitulation), not during recovery (current design), is real. v1's 2025-03 CCA peaked at score 33.4 while SPX drew down ~10% — that does feel wrong intuitively, but it's actually consistent with the indicator's *named purpose* (the canary scores "favorability for buying the dip *after stress resolves*", per methodology §1). Thrasher's original design fires *at the dip*, not during the bleeding.

So v2-D is not a bug-fix — it's a **scope-expansion** question: should the indicator publish both a "dip-buy favorability" score (current) and a "capitulation intensity" score (new), or should they be a single composite?

**Cost.** Large. This is a literature pass + design spec, not a code change. Needs:
- Literature review on capitulation indicators (Whaley's "fear gauge" framing, Bekaert/Hoerova "uncertainty vs risk" decomposition, Cboe SKEW)
- Decision on whether capitulation is a 6th scorer in the existing composite or its own indicator
- If it's its own indicator: where does it live in the API contract? Side-by-side with canary in `/regime/canary/`? Or a new `/regime/capitulation/` endpoint?

Per `docs/research/regime/CLAUDE.md` and the v1 design spec, calibration changes require their own spec under `docs/superpowers/specs/`. v2-D is past calibration — it's a new indicator. **This is a multi-week effort. Don't start until the cheap items (#1, #2) are done.**

### #7 — UI window picker on the Validation panel

**Why.** The current `/regime/canary/validation` endpoint returns the most recent winning-form run for the current `composite_version`. Walk-forward windows WF-1..WF-6 are not accessible to the user. A user looking at the panel during a 2026-style dip cannot see how the indicator performed in WF-2 (Volmageddon) for comparison.

**Cost.** Medium. Backend change (extend `/regime/canary/validation` with a `?run_id=...` or `?window=WF-N` query param) + frontend window selector + types regeneration. ~2-3 hours.

**Priority.** Low. The walk-forward results are in the DB and accessible via the SQL cookbook in `closure-2026-05-24.md`. A UI is convenience; the methodology is sound without it.

### #8 — Archive run id 25 (smoke duplicate of run 26)

**Why.** Run 25 and run 26 are both `phase=robustness` against the same 2011-02-08..2026-05-21 window. Run 26 is the canonical one cited in v1 §9. Run 25 is a duplicate that survived. Currently the table has no soft-delete mechanism.

**Cost.** This is the same migration the VCG roadmap already calls for as item #7 (`regime_backtest_runs.archived_at` column + repository helper). Build the migration once, both indicators benefit.

**Status.** Coordinate with VCG roadmap's item #7. Don't build two parallel migrations.

---

## 4. Cross-cutting decisions to make explicit

### When does `COMPOSITE_VERSION` bump?

Per the v1 design spec, the rule is: **any change to score arithmetic that produces different score values for the same input bumps the version**. Band-threshold changes do **not** bump (they're post-score classifications).

| Candidate | Bumps version? | Why |
|---|---|---|
| v2-A (drop speed from score) | YES (1 → 2) | Score values change for every day with non-NEUTRAL speed |
| v2-B (STRONG_BUY threshold) | NO | Band classification only; raw scores unchanged |
| v2-C (form change `linear` → `convex` etc.) | YES (1 → 2) | Score arithmetic changes |
| v2-C (threshold-only WATCH tighten) | NO | Band classification only |
| v2-D (capitulation scorer added) | YES (1 → 2) — or 2 → 3 if v2-A already shipped | New scoring component |

Each `COMPOSITE_VERSION` bump triggers a full backfill rerun with `--overwrite` (per `scripts/canary_backfill.py:97`). Plan accordingly.

### Calibration recalibration discipline

**Do not** rerun `--calibrate` against the train window using the freshly-backfilled 2011-2014 data and then run walk-forward against 2015-2026.

Why: the 2011 data is the same data the walk-forward judged the v1 calibration on. Recalibrating against it and then re-evaluating against the rest of the same period would be circular — the v1 walk-forward result is the empirical anchor we just bought with the backfill. Throwing it away by recalibrating defeats the purpose.

If recalibration is genuinely needed (e.g. v2-A or v2-C ships), the discipline is:
- Reserve a holdout (e.g. 2024-onward) that is not used for any threshold setting.
- Calibrate on 2011-2023.
- Evaluate the final v2 calibration on 2024-onward as a pure OOS check.

This is the same discipline applied in v1 but with a different holdout window.

### OOS gate update protocol

Per `docs/research/regime/CLAUDE.md:25`, any recalibration that moves AUCs >0.02 must update `LAST_KNOWN_AUC_*` in `tests/integration/regime/test_canary_oos_gate.py`. This is a CI-blocking gate — the update must be in the same PR as the calibration change, not a follow-up.

---

## 5. Recommended sequencing

```
Phase A — measurement (do this week):
  #1 Re-run --form-sweep against full 2011-2026 dataset
  #2 File v2-A / v2-B / v2-C / v2-D as GitHub issues
  → Both can run in parallel; #1 produces data, #2 produces a home for the conversation

Phase B — decision (after #1 reports):
  #3 Decide on v2-A using #1 output
  #5 Decide on v2-C sub-path using #1 output
  #4 Decide on v2-B (lower priority, defer if v2-C is moving)

Phase C — convenience / hygiene (parallel to Phase B):
  #7 UI window picker (when there's a slow day)
  #8 archived_at migration (coordinate with VCG roadmap item #7)

Phase D — design (no earlier than Phase B resolves):
  #6 v2-D capitulation scorer brainstorm + spec
```

**If only one item ships from this list in the next two weeks, make it #1.** It is the smallest measurement that meaningfully changes what we know about the system.

If two ship, make them #1 and #2.

If three ship, make them #1, #2, and #3 (the decision on v2-A — the architecture call most affected by #1's output).

---

## 6. Acceptance criteria for each phase

### Phase A acceptance
- 4 new rows in `regime_backtest_runs` (one per `score_form`) with `params.phase='form_sweep_full'`, `start_date=2011-02-08`, `end_date=2026-05-21`, `composite_version='1'`.
- An updated section in this memo (or a new artifact) capturing winning form, AUC delta vs the original 2015-2019 sweep, and band-distribution drift.
- 4 GitHub issues filed (or local issues — wherever follow-ups live), each with hypothesis / evidence / falsification / effort / version-bump-required fields.

### Phase B acceptance
- A go/no-go decision for v2-A, v2-B, v2-C captured as a single commit on `main` updating §10 of `canary-5yr-executive-summary.md` with current state ("DEFERRED" / "PROMOTED to PR planning" / "REJECTED with reason").
- If any candidate is promoted: a draft spec under `docs/superpowers/specs/` referencing the v1 spec's invariants section.

### Phase C acceptance
- UI window picker: user can select WF-1..WF-6 from the validation panel and see per-window AUC + episode count.
- `archived_at` migration: `SELECT id FROM uw_scan.regime_backtest_runs WHERE archived_at IS NOT NULL` returns ≥ 1 row (run 25 archived).

### Phase D acceptance
- A capitulation-scorer design spec exists and has been reviewed via `/codex-review --plan`.
- The spec answers explicitly: 6th scorer in the composite vs separate indicator; API contract; train/OOS partition; how it interacts with v2-A if v2-A shipped.

---

## 7. Risks and what could go wrong

| Risk | Mitigation |
|---|---|
| #1 returns a non-`linear` winner — we get pressured to ship v2-C quickly | Don't. Re-pin to the train/holdout discipline in §4. A new form requires a calibration redo with a reserved holdout, which takes 1-2 days minimum, not 1 hour. |
| v2-A ships and breaks the v1 OOS gate, blocking CI | Update `LAST_KNOWN_AUC_*` constants in the same PR (per the standing rule). Don't ship v2-A as a separate PR from the gate update. |
| `COMPOSITE_VERSION` bumps and snapshot rows for `version=1` are orphaned | The backfill script's `--overwrite` flag handles this cleanly. Plan for ~10 min of downtime on the live snapshot during the rerun. |
| v2-D scope-creeps into "rewrite the whole indicator" | Hard-cap the spec to one literature review week + one design spec. If the spec doesn't converge, the answer is "capitulation is its own indicator, not part of canary." |
| Running #1 against the full dataset masks the original 2015-2019 form result | Don't overwrite the run 18 row. Add a new `phase=form_sweep_full` set of rows; keep the original sweep visible for comparison. |

---

## 8. Out of scope

These came up in the v1 conversation but are deliberately not on this roadmap:

- **Per-window recalibration in walk-forward** (true expanding-train walk-forward where each window has its own thresholds): correct in principle, but requires `--calibrate` per window and a per-window `composite_version` in the DB schema. ~1 week of work, low expected lift over the frozen-calibration approach we just validated.
- **Intraday canary updates**: out of scope by design — the indicator is EOD-only because all five inputs (VIX, VVIX, VIX3M, COR1M, SPX) are EOD-anchored.
- **Joint signal with CRI or VCG**: explicitly the VCG roadmap's territory (`vcg-next-steps-2026-05-26.md` item #3). When joint-signal work happens, canary will be a co-occurrence input; it does not lead.

---

## 9. The discipline this enforces

After a validated v1, the temptation is to start "improving" the calibration immediately. But v1 earned its right to ship by being honest about its limitations (vol-only beats composite, WATCH overfires, STRONG_BUY never fires) and by passing 5/6 walk-forward windows with the *frozen* calibration. Rushing to change the calibration before measuring what would actually move it would burn that signal.

The cheap measurement (#1) is the work that protects the v1 result while still moving forward. The issue-filing step (#2) creates the venue where v2 designs can be debated without ad-hoc Slack threads. Both are unsexy compared to "let's redesign the scorer", but both are the prerequisite to redesigning the scorer well.

If this memo prompts the urge to skip to #6 (capitulation scorer) — pause. #1 first.
