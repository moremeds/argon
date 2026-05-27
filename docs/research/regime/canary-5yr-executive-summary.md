# 5% Canary — Executive Summary (Preliminary Results)

**Date**: 2026-05-27
**Composite version**: `1` (frozen calibration, `score_form=linear`)
**Source DB**: `option_wizard.uw_scan.canary_snapshots`
**Backtest run id**: `18` (OOS, marked `is_winning_form=true` by the current gate)
**Status**: **PRELIMINARY** — promising vol-driven OOS signal, but **not yet validated as regime-robust**. Awaiting the 2011 backfill + walk-forward.
**Scope**: Review-ready summary of the populated dataset, the preliminary single-window result, the data still missing, and the engineering steps that close the validation loop.

---

## TL;DR

- **1,400 daily snapshots** populated, covering **2020-10-23 → 2026-05-21** (~5.5 years).
- Backtester reports a **preliminary OOS edge** over this single window with AUC **0.61 / 0.64 / 0.66** at 5d / 20d / 60d forward-drawup horizons. The edge is **directionally encouraging**, but treating it as regime-robust requires the 2011-onward backfill and walk-forward.
- **The composite is a vol-resolution predictor with the Thrasher speed state acting as context / safety gating** — not the other way around. The ablation table is unambiguous: vol-only AUC ≈ composite AUC; speed-only AUC ≈ random. Speed contributes regime context (BTD = bullish setup, CCA = bearish setup) and the cap-rule veto on CCA/BOTH, not predictive rank.
- **Additional lookback available: ~2,443 trading days (≈ 9.7 calendar years), back to 2011-02-08**. The binding constraint is `MIN_ALIGNED_BARS=350` against VIX3M's first aligned date (2009-09-18). That extra decade contains 2011, 2014, 2015, Brexit, **Volmageddon 2018**, Q4-2018, and the 2020 COVID crash — the exact regimes the current single-window OOS misses.

---

## 1. Dataset Coverage

| Metric | Value |
|---|---|
| Rows populated | **1,400** |
| First snapshot | 2020-10-23 |
| Latest snapshot | 2026-05-21 |
| Span | 5.6 years (~252 trading days/year × 5.5) |
| Composite version | 1 |
| Score form | linear |
| Symbols required | SPX, VIX, VVIX, VIX3M, COR1M (all 5 must align per trading day) |

### Score distribution

| Stat | Value |
|---|---|
| Mean | 21.84 |
| Stddev | 11.52 |
| Min | 0.00 |
| P50 | 20.23 |
| P75 | 28.73 |
| P90 | 35.56 |
| P95 | 41.00 |
| Max | **66.36** (2020-11-12) |

Mean ~22 sits below the WATCH threshold (25) — most days the signal is quiet. P95 brushing the BUY threshold (50) is by design: the calibration is tuned so BUY-band days are rare.

### Band distribution

| Band | Days | % of dataset |
|---|---:|---:|
| NONE | 915 | 65.4% |
| WATCH | 435 | 31.1% |
| BUY | 50 | 3.6% |
| STRONG_BUY | 0 | 0.0% |

NONE + WATCH = 96.5% — the score is not over-firing. For a crisis-resolution canary, that sparsity is a feature, not a bug. **STRONG_BUY has never fired in 5.5 years** — either correctly reserved for GFC-class events, or too aggressive. The 2011 backfill will tell us (2011 / 2015 / 2018 are the candidates).

### Speed-state distribution (raw `speed.state` from the scoring layer)

The speed sub-state comes directly from the 4-state machine in `canary_scoring.derive_speed()`. It is *not* the same as `warning_state` (which is `speed.state` after cap-lift / anchor logic).

| Speed state | Days | % |
|---|---:|---:|
| NEUTRAL | 1,172 | 83.7% |
| BUY_THE_DIP_ACTIVE | 172 | 12.3% |
| CONFIRMED_CANARY_ACTIVE | 56 | 4.0% |
| BOTH_ACTIVE_AMBIGUOUS | 0 | 0.0% |

### Warning-state distribution (effective state after cap-lift gating)

Today's `canary_snapshots.warning_state` happens to be identical to `speed.state` because no cap-lift override has fired (i.e. CCA/BOTH days never met the cap-lift conditions). That makes the two tables collapse to the same numbers in the current sample — but the schemas are distinct and the backfill may surface days where they diverge.

| Warning state | Days | % |
|---|---:|---:|
| NONE | 1,172 | 83.7% |
| BUY_THE_DIP_ACTIVE | 172 | 12.3% |
| CONFIRMED_CANARY_ACTIVE | 56 | 4.0% |
| BOTH_ACTIVE_AMBIGUOUS | 0 | 0.0% |

The anchor invariant is holding: BOTH_ACTIVE_AMBIGUOUS has zero days, meaning once a Canary fires against a 252-day high, BTD cannot also fire against the same anchor (and vice versa).

---

## 2. Year-by-year Breakdown

| Year | Days | NONE | WATCH | BUY | CCA | BTD | Peak score | Mean score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 (partial — from 2020-10-23) | 48 | 0 | 18 | 30 | 0 | 0 | 66.4 | 51.2 |
| 2021 | 252 | 133 | 102 | 17 | 0 | 43 | 58.0 | 26.1 |
| 2022 | 251 | 189 | 62 | 0 | 23 | 0 | 38.7 | 19.3 |
| 2023 | 250 | 177 | 73 | 0 | 0 | 43 | 41.0 | 19.9 |
| 2024 | 252 | 211 | 41 | 0 | 0 | 0 | 47.6 | 14.8 |
| 2025 | 250 | 172 | 78 | 0 | 33 | 28 | 41.0 | 20.6 |
| 2026 (YTD through 2026-05-21) | 97 | 33 | 61 | 3 | 0 | 58 | 51.3 | 29.7 |

Notable observations:
- **2020-Q4 is anomalously elevated** (mean 51, peak 66) — the dataset begins mid-vol-crush (post-election + vaccine announcement). VRP gate fired strongly because realized vol was crashing relative to implied. This is a calibration corner case worth flagging in walk-forward work.
- **2024 was the quiet year** (mean 14.8, peak 47.6, zero CCA/BTD episodes). Healthy bull regime; signal sat correctly idle.
- **2026 YTD is elevated** (mean 29.7, peak 51.3, 58 BTD days through May) — the indicator has been actively flagging the spring 2026 dip / recovery.

---

## 3. Episodes vs Event Fires — Two Different Counts

This is an important reconciliation that was conflated in the previous draft.

| Concept | Source | Count |
|---|---|---|
| **Episodes** (collapsed `warning_state != NONE` runs in `canary_snapshots`) | SQL over the snapshots table, group by transitions | **6** |
| **Event fires** (unique `fire_date` entries in the scoring state machine) | Backtester run_id 18, `state.emitted` | **7** (4 BTD + 3 CCA) |

The two are not the same:
- An *episode* is a contiguous calendar run during which `warning_state != NONE` in the persisted snapshots.
- An *event fire* is a single fire-date produced by `step_primary_events` / `step_confirmed_canary`. Each fire opens a 42-trading-day activity window that *can* be eclipsed by a later fire of the other kind (e.g. a Canary fire followed by a BTD fire against the same prior anchor would not be possible — anchor invariant — but a Canary fire on anchor A followed by a BTD fire on a new anchor B IS possible).

The arithmetic gap (7 fires vs 6 episodes) is most likely **one CCA fire whose 42-day window was eclipsed by the next anchor-reset before it accumulated multi-day continuous CCA snapshots**. This will be reconciled cleanly in the 2011 backfill — with a longer window and more fires we can sort fires by date and check whether each episode boundary maps one-to-one.

### The 6 episodes

| # | State | Window | Trading days | Peak score | Likely macro context |
|---|---|---|---:|---:|---|
| 1 | BTD | 2021-09-30 → 2021-11-30 | ~44 | 41.0 | Sep-Oct '21 correction (energy / supply chain) |
| 2 | CCA | 2022-01-24 → 2022-03-16 | ~36 | 33.4 | Fed pivot to hawkish; Q1 '22 sell-off |
| 3 | BTD | 2023-09-21 → 2023-11-20 | ~43 | 41.0 | Aug-Oct '23 bond-yield-driven sell-off |
| 4 | CCA | 2025-03-11 → 2025-05-07 | ~40 | 33.4 | Q1 '25 selloff (tariff / regime-shift period) |
| 5 | BTD | 2025-11-20 → 2026-01-23 | ~44 | 41.0 | Q4 '25 / Q1 '26 dip |
| 6 | BTD | 2026-03-18 → 2026-05-18 (still active at end of dataset) | ~43 | **51.3** | Spring '26 dip / current episode |

**Pattern observation**: Episodes run ~30-45 trading days, consistent with `SPEED_ACTIVITY_WINDOW_DAYS=42`. Episode 6's peak score of 51.3 is the highest BTD-active reading in the dataset and the only BTD episode to enter the BUY band — the most recent live signal.

---

## 4. Preliminary OOS Result (run_id 18)

OOS window: 2020-10-23 → 2026-05-21. Composite v1. Score form `linear`.

### Daily AUCs (composite score → forward drawup classifier)

| Horizon | Threshold | AUC | Note |
|---|---|---:|---|
| 5 trading days | +2% | 0.608 | Diagnostic — 5d is the noisiest horizon |
| 20 trading days | +5% | 0.638 | Secondary criterion |
| 60 trading days | +10% | **0.661** | **Primary criterion** — strongest |

The 60d AUC being highest is exactly what you'd want from a regime-resolution indicator (not picking up noisy short-term bounces). All three pass the legacy single-window 0.55 hurdle.

**Caveat — autocorrelation**: 1,400 daily rows sound large, but episodes create many correlated active days. The naive AUC computation treats each day as independent; the true effective sample size is closer to the number of distinct fire-event windows (~6-7) plus the calm days. Block-bootstrap CIs will replace point estimates in the walk-forward phase.

### Ablation

| Variant | AUC 5d | AUC 20d | AUC 60d | Interpretation |
|---|---:|---:|---:|---|
| Speed-only | 0.470 | 0.465 | 0.430 | Near random — speed alone has no predictive rank |
| Vol-only | 0.621 | **0.654** | **0.666** | Carries the predictive signal |
| Composite | 0.608 | 0.638 | 0.661 | Vol-anchored, mildly degraded by speed gating |

**Read**: **The vol layer carries the predictive score. The speed layer provides regime state / context / veto, not rank improvement.** Composite AUC is slightly *below* vol-only because the speed gating costs a small amount of rank discrimination — that's an acceptable trade for the state/context the speed layer adds, but the marketing should not claim "speed events predict returns." That isn't what the data show.

### Event-level metrics — **descriptive only at current n**

| Event type | Count | Median 42d fwd | CI lower | 60d follow-through rate |
|---|---:|---:|---:|---|
| BUY_THE_DIP fires | 4 | +6.82% drawup | +5.26% | 100% recovered within 60d |
| CONFIRMED_CANARY fires | 3 | −11.01% drawdown | −27.60% | 67% further drawdown |

**Rule**: with n < 5, event metrics are descriptive only — directionally aligned with the design hypothesis but not yet a hard pass/fail signal. The CI lower on CCA drawdown is −27.6% — that range alone tells you the sample size is too small for a strong claim. Backfill will materially shrink this.

### Cap rule clarification

The hard-cap rule prevents **CONFIRMED_CANARY_ACTIVE** (and the hypothetical BOTH_ACTIVE_AMBIGUOUS) regimes from printing a BUY/STRONG_BUY band unless explicit cap-lift conditions are met (`spx_above_sma200_2d` ∧ `vix_term_normalized` ∧ `higher_closing_low`). **BTD (BUY_THE_DIP_ACTIVE) is the bullish speed state and is not capped** — that's why episode 6 was free to print BUY-band days (score 51.1 on 2026-03-31).

---

## 5. Lookback Availability — Corrected Numbers

This is the actionable input for walk-forward planning.

### Per-symbol coverage in `vol_index_daily`

| Symbol | First date | Last date | Rows |
|---|---|---|---:|
| SPX | 1975-01-02 | 2026-05-21 | 12,955 |
| VIX | 1990-01-02 | 2026-05-21 | 9,190 |
| COR1M | 2006-01-03 | 2026-05-21 | 5,128 |
| VVIX | 2006-03-06 | 2026-05-21 | 5,025 |
| **VIX3M** | **2009-09-18** | 2026-05-21 | **4,194** ← limiting |

### Maximum aligned window (corrected — binding gate is `MIN_ALIGNED_BARS=350`, not 200d SMA)

| Metric | Value |
|---|---|
| First date all 5 symbols align | 2009-09-18 |
| Last aligned day | 2026-05-21 |
| Total aligned trading days | 4,192 |
| Warm-up gate in scanner | **`MIN_ALIGNED_BARS = 350`** |
| 200-bar (SMA-200) mark | 2010-07-06 (not binding alone) |
| 252-bar (canary high anchor) mark | 2010-09-17 (not binding alone) |
| **350-bar mark — first computable snapshot** | **2011-02-08** |
| Currently backfilled (first row) | 2020-10-23 |
| **Additional lookback available** | **2,443 trading days (≈ 9.7 calendar years from 2011-02-08 to 2020-10-22)** |

The previous draft used 200d SMA as the binding gate — that was wrong. The scanner explicitly returns `None` when `len(common_dates) < 350`, so the first valid snapshot is at the 350th aligned bar, which is **2011-02-08**.

### What that extra decade buys you

The current backfill misses the most informative stress regimes for a vol-anchored indicator:

| Period | Event | Why it matters for the canary |
|---|---|---|
| 2011-08 | US debt downgrade / Euro crisis | Multi-month vol regime; tests structural-vol scoring at sustained high VIX |
| 2014-10 | Bund tantrum / oil collapse | Single-week vol spike — tests tactical "VIX spike revert" scorer |
| 2015-08 | Yuan devaluation | Fast 10%+ S&P correction; tests both 5% canary fire and BTD recovery |
| 2016-01 | China selloff | Slow-bleed correction; tests anchor invariant over a long horizon |
| 2016-06 | Brexit | Single-day shock then recovery — gold standard for BTD vs CCA disambiguation |
| **2018-02** | **Volmageddon (XIV blowup)** | The canonical structural-vol regime shift; absolute must-have for any vol-anchored indicator |
| 2018-Q4 | Fed-pivot sell-off | Three-month decline; tests CCA-active sustain logic |
| **2020-02–03** | **COVID crash** | **Currently OOS excludes this** — without it the validation claim has a glaring hole |

**Critical**: the current OOS starts 2020-10, which means the most important 2020 stress episode (Feb-March crash) is *missing*. Until the backfill includes Feb-Mar 2020, the OOS validation cannot claim to have been tested through a true crisis.

---

## 6. Walk-Forward Plan — Revised

The current single-window OOS is a one-shot test. Walk-forward exposes regime-stability problems a single window misses.

### Window setup

| Window | Train (frozen v1 calibration, used only for context) | OOS test | Macro regime |
|---|---|---|---|
| WF-1 | 2011-02 → 2014-12 | 2015-01 → 2016-12 | China devaluation, Brexit |
| WF-2 | 2011-02 → 2016-12 | 2017-01 → 2018-12 | Volmageddon, Q4-18 selloff |
| WF-3 | 2011-02 → 2018-12 | 2019-01 → 2020-09 | Repo crisis, COVID crash |
| WF-4 | 2011-02 → 2020-09 | 2020-10 → 2022-12 | Post-COVID rally, 2022 inflation |
| WF-5 | 2011-02 → 2022-12 | 2023-01 → 2024-12 | Bond-yield selloff, 2024 quiet |
| WF-6 (live OOS) | 2011-02 → 2024-12 | 2025-01 → present | 2025 tariff regime, 2026 dip |

For v1, the train window is informational only — the frozen calibration is reused across all OOS tests. (True walk-forward with per-window recalibration is a separate future step if v1 regime-stability fails.)

### Success criteria — revised (less strict)

**Per-window pass/fail:**
- **Primary**: 60d AUC ≥ **0.58** in the majority of windows (4 of 6+) — 60d is the indicator's designed horizon and the most stable.
- **Secondary**: 20d AUC ≥ **0.55** in the majority of windows.
- **Diagnostic only**: 5d AUC reported but not gated — too noisy at this horizon for a regime indicator.

**Event-level:**
- n < 5 fires per window → **descriptive only** (report but don't pass/fail).
- n ≥ 5 fires per window → eligible for sanity-check pass/fail (e.g. BTD median 42d drawup > 0, CCA median 42d drawdown < 0, signs aligned with the design hypothesis).

**Robustness criteria (across windows):**
- Composite vs vol-only AUC gap should stay small (vol-only should never dominate composite by >0.03 AUC, else we have a positive case for dropping the speed layer from the score).
- Band distribution drift: % WATCH days should be stable (±10pp) across windows.

### Failure modes the walk-forward will catch

- **Calibration drift**: if event thresholds were tuned to 2020+ regimes (low-rate / low-realized-vol era), WF-1 and WF-2 may show AUC collapse.
- **Score-form fragility**: the current `linear` form was the winner in a single-window sweep. Walk-forward across 6 regimes will reveal if a non-linear form is more stable.
- **Anchor-invariant correctness in non-trending regimes**: 2015-2016 had two 10%+ corrections without a clean recovery between — does the anchor reset logic behave?
- **Cap-rule stress test**: 2018-Q4 and 2020-Q1 should produce multiple CCA fires where cap-lift conditions flicker on/off mid-episode.

### Implementation

- CLI-only for now. Add `--walk-forward` to `scripts/backtest_canary.py`; loop the 6 windows, write 6 rows to `regime_backtest_runs` (one per window with distinct `oos_start` / `oos_end`).
- No UI window picker in this PR. The validation panel continues to show the most recent winning-form run for the current `composite_version`.

---

## 7. Robustness Report (also CLI-only, alongside walk-forward)

In addition to the 6-window pass/fail, produce a robustness section against the full backfilled dataset:

| Subset | Why it matters |
|---|---|
| **Full dataset (2011-02 → 2026-05)** | The headline AUC numbers |
| **Excluding 2020-Q4** | Removes the anomalous post-vaccine vol-crush window from the OOS mean |
| **Excluding 2026 live period** | The 2026 BTD episode is still ongoing; forward labels are partial |
| **Composite vs vol-only across each subset** | Quantifies the speed layer's net contribution |
| **AUC by calendar year** | Surfaces specific regimes where the indicator fails |
| **AUC by score band** | Within-band rank discrimination — does WATCH actually carry information vs NONE? |
| **True event-fire stats (not warning-state-derived)** | Uses `state.emitted` directly, not snapshot transitions |
| **Block-bootstrap CI on every AUC** (block_len=20) | Honest confidence intervals given daily autocorrelation |

---

## 8. Open Questions / Caveats

1. **STRONG_BUY band has zero hits in 5.5 years**: backfilling to 2011 will surface 2011 / 2015 / 2018 / Feb-Mar 2020 candidates — we'll know quickly whether the threshold is correctly reserved for once-a-decade events or simply too aggressive.
2. **Speed layer's net AUC contribution is negative** (composite slightly below vol-only at every horizon). The walk-forward should confirm whether this generalizes; if so, an explicit redesign would separate `vol_resolution_score` (predictive) from `speed_state` (context) from `warning_cap` (veto) as three independent outputs rather than a single composite.
3. **The hard-cap rule has not yet been stress-tested in a regime where cap-lift conditions flicker rapidly mid-episode**. 2018-Q4 and Feb-Mar 2020 are the candidate episodes for this test.
4. **CCA n=3 is too small for any confidence claim**. The −27.6% CI lower bound on the drawdown median tells you that. Backfill will roughly double the sample.
5. **The score's behavior during *max fear* (deep CCA) is structurally muted**: scorers fire on mean-reversion-in-progress, not on the depth of stress. The composite peaks during *recovery*, not during *capitulation*. This is an intentional design choice (matches Thrasher 2023) but worth flagging — if the user-facing read is "buy when canary is high during fear," the indicator's behavior won't match that intuition. The walk-forward result will inform whether this is the right design.

---

## 9. Suggested Next Actions

Priority order, with the deferral discipline from your review:

| # | Action | Effort | Priority |
|---|---|---|---|
| 1 | Backfill canary_snapshots back to **2011-02-08** (~2,443 more rows) | 10 min | **CRITICAL** |
| 2 | Add `--walk-forward` flag to `scripts/backtest_canary.py` (CLI-only) | 2-4 hr | **HIGH** |
| 3 | Add robustness report alongside walk-forward (composite vs vol-only across exclusion regimes, AUC by year/band, true event-fire stats, block-bootstrap CI) | 2-3 hr | **HIGH** |
| 4 | Run 6-window walk-forward + robustness report against the 2011-onward dataset | 30 min | HIGH |
| 5 | **Decide** based on results whether v1 calibration is regime-robust enough to merge PR #83 or needs retune | — | gate |
| 6 | (If needed) re-tune calibration; explicit redesign into `vol_resolution_score` + `speed_state` + `warning_cap` is on the table if vol-only continues to dominate | TBD | follow-up PR |
| 7 | UI window picker on the Validation panel | 2 hr | LOW |

**Important deferral**: do not change calibration before the walk-forward result is in. The whole point of step 4 is to find out whether the v1 calibration is regime-robust; pre-tweaking destroys the empirical validation.

---

## Appendix: How this document was generated

- Dataset stats: SQL queries against `uw_scan.canary_snapshots` (5.6-year window).
- Backtest metrics: `scripts/backtest_canary.py --report` against `option_wizard`, run id 18.
- Per-year / band-by-band tables: raw SQL with `WHERE composite_version = 1`.
- Lookback availability: aligned-date count across the 5 required symbols, with `MIN_ALIGNED_BARS=350` as the binding warm-up gate (verified against `src/uw_scan/scanners/canary.py:27` and the `len(common_dates) < MIN_ALIGNED_BARS` check).
- Episode reconciliation note (§3) is explicit about the difference between snapshot-state collapses and state-machine event fires.
