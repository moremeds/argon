# Regime indicators — CRI · VCG · 5% Canary (results)

Final results for the three macro-regime indicators. **These are descriptive / probabilistic
*classifiers* of market-regime stress, not tradeable strategies** — so there is **no equity
curve or buy-and-hold P&L here**; they are scored by discrimination (**AUC**), named-crash
timing, and band distribution. The tradeable equity-line research that *consumes* this regime
read is the sibling [`../vrp/`](../vrp/) short-vol study.

> Numbers below are `[COMPUTED]` from the persisted backtests
> (`uw_scan.regime_backtest_runs` / `regime_backtest_daily`, `canary_snapshots`). The DB is the
> source of truth; see [`closure-2026-05-24.md`](./closure-2026-05-24.md) for the SQL cookbook.
> This README summarizes; the methodology docs (`cri-/vcg-/canary-methodology.md`) and
> [`_iterations/`](./_iterations/) hold the detail and the superseded design notes.

> **Why files stayed in place (not all archived):** `guidance.md` is **read live by the API**
> (`api/routers/regime_validation.py`), `canary-calibration-v{1,2}.json` are **loaded at runtime**
> by `cards/canary_calibration.py`, and the three `*-methodology.md` + `ground-truth-labels/*.yaml`
> are code/PR-contract "source of truth." Only genuine discussion/next-steps/design files moved to
> `_iterations/`.

---

## 1. The three indicators at a glance

| Indicator | What it measures | Verdict | Use |
|---|---|---|---|
| **CRI** — Crash Risk Indicator | 4-component vol-complex stress score (0–100), `composite_version=3` | **Leading** vol-stress score; AUC ~0.63 | Early-warning / posture gate |
| **VCG** — Vol-Credit Gap | Credit-spread-vs-vol residual z (HYG proxy), `composite_version=1` | **Descriptive, NOT predictive** — *late* on Lehman | Confirmation, pair with CRI |
| **5% Canary** | Capitulation/bottom-fishing canary (Thrasher 2023 + 5 vol signals), `composite_version=1` | **Validated v1**; composite AUC ~0.62 | Dip-buy trigger, not a warning |

---

## 2. Metrics

### 2.1 CRI — Crash Risk Indicator

First DB-of-record run (`run_id=1`): **4,873 daily rows**, `composite_version=3`,
**AUC dd5 = 0.6343**, **AUC dd10 = 0.6329**, **255 fired-trigger days**. Out-of-sample
walk-forward against ~20 years of CBOE vol-complex data (`cri-validation.ipynb` §9 is the honest
accuracy breakdown). Architecture is a fixed 4 × 25 = 100 composite; CRI level → trading posture
is the `guidance.md` lookup the API serves.

### 2.2 VCG — Vol-Credit Gap

First DB-of-record run (`run_id=3`): **4,708 daily rows**, HYG credit proxy, `composite_version=1`.
**The headline is a limitation, honestly recorded:** VCG is **descriptive, not predictive**. On the
±5d named-crash window it was *late* on Lehman — SUPPRESSED days −5…−1, BOUNCE day 0, RISK_OFF day
+3 — and the modal state is **SUPPRESSED at ~52%** of days. Forward-return study (see project memory
`project_vcg_forward_returns_descriptive`): PANIC mean-reverts +2.88% over 20d, RISK_OFF +3.04% over
60d (indistinguishable from baseline). **Use as a dip-buy / confirmation trigger paired with a
leading signal — never as a standalone early warning.**

### 2.3 5% Canary — Validated v1

**3,843 daily snapshots**, **2011-02-08 → 2026-05-21 (~15.3 years)**, `composite_version=1`,
`score_form=linear`. Backtest runs `18` (single-window), `19–24` (6-window walk-forward), `26`
(robustness).

| Metric | 5d | 20d | 60d |
|---|--:|--:|--:|
| **Composite AUC (full 15yr)** | 0.620 | 0.627 | 0.619 |

- **Walk-forward: 5 of 6 windows pass** the primary criterion (60d AUC ≥ 0.58). Only WF-2 (2017–18,
  Volmageddon era) fails — and just barely, at **0.569**. Excluding the 2020-Q4 anomaly lifts 60d to **0.665**.
- **Band distribution:** NONE 65.4% · WATCH 31.1% · BUY 3.6% · **STRONG_BUY 0.0%** (never fired in 15yr,
  incl. Volmageddon/Aug-2015/Q4-2018/COVID — either correctly reserved for GFC-class events or too aggressive).

**Three known v2 candidates (real signals, did not block v1):**
1. **Vol-only beats composite by 0.01–0.02 AUC** across every subset/horizon → the speed layer adds
   context/veto, not rank. Drop speed from the *score*, keep it as state/context.
2. **BUY band is anti-predictive** within itself (AUC 0.35–0.45 — regression-to-mean); the score is only
   meaningful within the NONE (0.58–0.60) and WATCH (0.56–0.63) bands.
3. **WATCH overfires** (39% of days on the full set). Narrow it.

---

## 3. Conclusion

- **All three are regime *context*, not timing tools.** CRI is the one *leading* score (AUC ~0.63);
  VCG and the Canary are descriptive — VCG lags crises, the Canary marks capitulation after the fact.
  The validated, mergeable state is: **CRI v3, VCG v1, Canary v1**, all persisted to Postgres-of-record.
- **Pair them.** VCG's lateness is fixed by reading it *alongside* CRI or a leading vol signal; the
  Canary's BUY-band noise means trust the WATCH/NONE discrimination, not the BUY rank.
- **There is no equity curve to show** — that's not what these are. Their economic value is realized by
  *gating a strategy*, which is exactly the open improvement below.

---

## 4. Can we improve them? (open research, from `closure-2026-05-24.md` §4–5)

- **CRI:** add **VIX term-structure** (contango↔backwardation flip) as a 5th component (needs 4×25 → 5×20
  redistribution + VX-futures data); revisit the fixed 10/15 tactical/structural sub-weights against the OOS labels. [INFERRED, MED]
- **VCG v2 recalibration:** the 52% SUPPRESSED rate suggests the 21-day OLS window is too short and/or the
  sign gate should be a *band* not a strict ≤ 0; run the **HYG vs JNK vs LQD** A/B (three `backtest_vcg.py --proxy`
  invocations + comparison SQL); resolve a defensible Y-label so an OOS validation notebook is possible. [KNOWN gap, MED]
- **Canary v2:** act on the three candidates above — drop speed from the score, retune the (never-firing)
  STRONG_BUY threshold, narrow WATCH, add a capitulation scorer. [KNOWN, HIGH-value, well-scoped]
- **Cross-indicator co-firing:** the most interesting research material is *divergence* — when CRI HIGH/CRITICAL
  and VCG EDR/RISK_OFF disagree, one indicator sees something the other doesn't. [INFERRED, MED]
- **Highest-leverage cross-link → wire these into the VRP short-vol gate.** [INFERRED, HIGH] The
  [`../vrp/`](../vrp/) harvest is gated *only* on vol richness (vrp-z) with **no regime veto**. A
  CRI-CRITICAL / VCG-PANIC / term-structure-backwardation kill-switch is the most plausible way to cut that
  strategy's −64% compounding tail — and it tests the "does a kill switch help?" hypothesis the VRP iteration-4
  work left explicitly **untested**. This turns the regime indicators from a dashboard into a P&L lever.

---

## 5. Where things live

| Concern | Location |
|---|---|
| Methodology (source of truth) | `cri-methodology.md`, `vcg-methodology.md`, `canary-methodology.md` |
| Canary full deep-dive | [`canary-5yr-executive-summary.md`](./canary-5yr-executive-summary.md) |
| Closure memo + SQL cookbook | [`closure-2026-05-24.md`](./closure-2026-05-24.md) |
| CRI OOS validation notebook | `cri-validation.ipynb` |
| Runtime calibration (loaded by app) | `canary-calibration-v{1,2}.json` |
| Ground-truth crisis labels (loaded by scripts) | `ground-truth-labels/*.yaml` |
| Superseded design notes / next-steps / source PDF | [`_iterations/`](./_iterations/) |
| Scoring code | `src/uw_scan/cards/{cri_scorers,cri_scoring,vcg_scoring,canary_scoring,canary_calibration}.py` |
| Backtests (write DB, no file output) | `scripts/backtest_{cri,vcg,canary}.py` → `uw_scan.regime_backtest_runs` |
| Directory operating rules | [`CLAUDE.md`](./CLAUDE.md) |
