# Canary v2-C — Design Notes (post v2-A STOP verdict)

**Status:** Pre-spec. Captures the three candidate directions surfaced after [v2-A's terminal STOP verdict](canary-5yr-executive-summary.md#14-v2-a-volspeed-separation-result-2026-05-28-terminal-verdict-for-v2-a). This document is NOT a full spec — it's the alignment artifact before a spec brainstorm.

**Date:** 2026-05-28
**Owner:** chenxi
**Related:** [v2-A spec](../../superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md) · [v2-A plan](../../superpowers/plans/2026-05-27-canary-v2a-vol-speed-separation-plan.md) · [PR #94](https://github.com/moremeds/unusual-whales/pull/94)

---

## Why v2-C exists

v2-A's "binary remove `speed.score` from the composite" failed AC-F4 (WF-5 regression of −0.134 AUC). The interpretation:

- **`speed.score` is NOT a panic detector.** Vol-complex (`tactical + structural`) carries the panic signal in crisis regimes (WF-3 +0.087, WF-6 +0.217).
- **`speed.score` IS an early-instability detector in quiet regimes.** WF-5 (2024 quiet) collapsed when speed was removed — most likely because speed was carrying low-vol breakout / lead-lag / flow-acceleration / gamma-transition information that becomes load-bearing when vol-complex signals are dormant.

The problem with v2-A was not "is speed useful" but "should speed dominate the composite". Binary removal was too blunt.

---

## Three candidate directions

### A. Regime-conditional weighting (most direct)

```python
if vol_regime == "crisis":
    weight_speed = 0.0  # or small
    weight_vol_complex = 1.0
elif vol_regime == "quiet":
    weight_speed = 1.0  # full
    weight_vol_complex = 1.0
else:  # transition
    interpolate
```

**Pros:** Easy to reason about; cleanest hypothesis test (preserve quiet-regime contribution + preserve crisis-regime lift).
**Cons:** Adds a regime-detection signal that needs its own validation. Two-stage classifier increases failure surface.
**Open question:** What defines `vol_regime`? Realized vol percentile? VIX level percentile? VVIX/VIX ratio? Each choice is a new pre-committed gate.

### B. Rank inversion within BUY (most nuanced)

Keep v1's `tactical + structural + speed.score` formula to qualify the BUY bucket (preserves cross-sectional ranking), then use `speed` as a **secondary ordering signal within already-qualified BUYs only**.

```python
raw = tactical + structural + speed.score  # v1 formula — keeps quiet contribution
band = compute_band(raw)
if band == "BUY":
    # within-BUY ranking uses speed as tie-breaker on tactical+structural ties
    final_rank = (tactical + structural, speed.score)
```

**Pros:** Doesn't change the band-classification machinery (low-risk for production). Surgical — only affects within-BUY ordering, which is exactly where the form-sweep saw rank inversion. The user [originally called this v2-C](canary-5yr-executive-summary.md#10-v2-candidate-issues-file-as-follow-up-github-issues-do-not-block-pr-83).
**Cons:** Doesn't fix the WF-5 contribution problem directly — speed still contributes to the raw score, so WF-5 wouldn't change. But the v2-A AUC lift might disappear too. This is a different bet (cross-sectional ordering) rather than a v2-A replacement.

### C. Convex blending (nonlinear interaction)

```python
# instead of additive:
raw = tactical + structural + speed.score
# try multiplicative or clipped:
raw = (tactical + structural) * regime_fn(speed.score)
# or:
raw = tactical + structural + clip(speed.score, 0, threshold_by_regime)
```

**Pros:** Captures the intuition that speed's *contribution magnitude* should depend on the vol-complex's own state (when vol-complex is already saying "crisis", speed adds little).
**Cons:** Hyperparameter search space explodes. Hard to falsify cleanly.

---

## Pre-experiment requirements (must complete before any v2-C variant runs)

These are non-negotiable for institutional discipline.

### 1. WF-5 deep-dive (highest priority — gold mine)

Probe scaffold lives at [`scripts/probe_canary_wf5.py`](../../../scripts/probe_canary_wf5.py). First-pass output answers: in WF-5, how often did `speed.state != NEUTRAL`? What was `speed.score`'s distribution? How does that compare to WF-3 (where v2 won big) and WF-1 (where v2 broke even)?

**Probe 2 — forward-return by `warning_state` bucket — completed 2026-05-28.** Script: [`scripts/probe_canary_wf5_fwd_return.py`](../../../scripts/probe_canary_wf5_fwd_return.py). Three windows × three horizons (20d / 60d / 120d).

| Window | Horizon | Non-NONE mean | NONE mean | Welch's t |
|---|---|---|---|---|
| WF-5 (quiet) | 60d | **+11.4%** (BTD only) | +4.0% | **+17.16** |
| WF-5 | 120d | **+17.5%** (BTD only) | +7.5% | +24.15 |
| WF-3 (crisis) | 60d | +7.9% (CCA +14.9% / BTD +0.9%) | +2.6% | +4.77 |
| WF-3 | 120d | +15.9% (CCA +23.3% / BTD +8.5%) | +5.5% | +9.25 |
| WF-1 (baseline) | 60d | +3.3% (BTD only) | +1.2% | +2.59 |

**Three findings that reshape the v2-C direction call:**

1. **The "speed = early-instability detector in quiet regimes" framing was wrong.** In WF-5 `warning_state` never escalates beyond `BUY_THE_DIP_ACTIVE` (no CCA fires). When BTD fires (speed=20), forward 60d returns are +11.4% vs +4.0% baseline — t=17.16. Speed's load-bearing role in quiet regimes is **BTD activation**, which predicts strongly *positive* forward returns. v2-A's "drop speed from composite" killed the integer transition that drives BTD activation. The WF-5 -0.134 AUC regression is the cost of removing a +11.4%/60d alpha signal from composite ranking.

2. **CCA fires at mean-reversion bottoms, not selloff tops.** WF-3 CCA bucket has +14.9% / 60d and +23.3% / 120d forward returns — wildly positive, consistent with [[project-vcg-forward-returns-descriptive]] (BOUNCE n=5 dominated by 2008 GFC; PANIC mean-reverts +2.88%/20d). CCA is a *post-selloff dip-buy signal*, NOT a warning of imminent selloff. **This re-confirms why AC-F3 was the wrong gate**: canonical event dates were event *onsets*, but CCA fires at the bottom of the resulting 2-month cluster. AC-F3 reformulation (per §2 below) is no longer optional — it's load-bearing.

3. **Direction B (rank inversion within BUY) is now the leading v2-C candidate.** Direction A (regime-conditional weighting) requires a robust regime detector — itself a new failure surface. Direction C (convex blending) likely still suppresses BTD's quiet-regime contribution. Direction B (keep v1's composite intact, use speed only for *within-BUY ordering*) preserves BTD activation in both crisis AND quiet, and addresses the original BUY-band rank-inversion finding from the form-sweep. The probe's data supports B over A/C with the +11.4% / 60d signal as the load.

**Follow-up probes (queue, updated):**

- ~~Forward 60d return by `speed.state` bucket~~ — **DONE** (results above).
- VVIX percentile during WF-5 BTD-fire days — is BTD activating at *real* dip troughs or just stretched-quiet readings? Decides whether direction B's secondary-ordering signal needs an extra vol-of-vol gate.
- Cross-asset signal correlations during WF-5 (credit, term structure) — is BTD picking up lead-lag from non-vol-complex inputs? Diagnostic for whether v1's additive formula is accidentally capturing dispersion that v2-A removed.

**Probe 3 — bootstrap random-control — completed 2026-05-28.** Script: [`scripts/probe_canary_wf5_random_control.py`](../../../scripts/probe_canary_wf5_random_control.py). K=10000 bootstrap samples of n=43 days without replacement from non-bucket pool, seed=42, per (window, bucket, horizon). Resolves the selection-on-dip caveat from probe 2.

| Window | Bucket | 20td pctile / p | 60td pctile / p | 120td pctile / p |
|---|---|---|---|---|
| **WF-5** (quiet) | **BTD** | **100.00 / ≈0** | **100.00 / ≈0** | **100.00 / ≈0** |
| WF-3 (crisis) | BTD | 24.83 / 0.50 | 2.73 / 0.05 | 75.84 / 0.48 |
| WF-3 | **CCA** | **100.00 / ≈0** | **100.00 / ≈0** | **100.00 / ≈0** |
| WF-1 (baseline) | BTD | 100.00 / ≈0 | 99.79 / 0.004 | 13.54 / 0.27 |

Three findings from probe 3 that lock direction B:

1. **WF-5 BTD survives the strictest within-window null at ALL horizons** (100th percentile, p ≈ 0). Null mean is +4.0% ± 0.7% / 60d; BTD's +11.4% / 60d sits ~11 standard deviations above the null mean. The +11.4%/60d alpha is real signal, not selection-on-dip. **Direction B's evidence base is empirically defensible.**

2. **WF-3 BTD does NOT beat the null** (24.8 / 2.7 / 75.8 pctile). In crisis, ANY 43-day subset of the window has +1-4% / 60d forward returns driven by the COVID recovery rally; BTD's +0.9%/60d is actually *below* the null mean. **This is fine and consistent with v2-A's WF-3 win:** when vol-complex fires strongly (high tactical + structural), speed's BTD contribution adds little marginal info, so v2-A's removal of speed doesn't hurt WF-3. The regime-complementarity is exactly what direction B exploits.

3. **WF-3 CCA crushes the null** at all 3 horizons (100th percentile, p ≈ 0). +14.9% / 60d and +23.3% / 120d are real GFC-style mean-reversion bounces, beyond what within-window random selection could produce. v2-A preserved this pathway (speed → 0 → vol-complex dominates → composite ranking still discriminates CCA days). This is why v2-A's WF-3 60d AUC lifted +0.087.

**Regime structure (now legible):**
- **Crisis regime (WF-3):** vol-complex + CCA carry the signal; speed's contribution is dominated by recovery-rally baseline. v2-A's "drop speed" worked here because vol-complex was already sufficient.
- **Quiet regime (WF-5):** vol-complex is dormant (tactical=0, structural mid-range); speed-driven BTD is the alpha pathway. v2-A's "drop speed" killed this and caused the -0.134 / 60d regression.
- **Direction B (rank inversion within BUY) preserves both** because v1's additive composite is intact for BUY-band qualification.

**WF-1 BTD 120d (pctile 13.54) is an outlier worth one more probe** — at 120d horizon in 2015-2016, BTD's +2.05% sits below the null's +3.05% mean. Could be a 2015-2016 specific artifact (Brexit recovery overshoot) or a generic 120d horizon issue. Not a direction B blocker since WF-1 wasn't a regression window in v2-A, but worth understanding before the spec brainstorm locks horizon weights.

### 2. AC-F3 reformulation (gate redesign)

v2-A's spec required 4 canonical event dates to fire `confirmed_canary_active=True`. Empirically (PR #94), v2 CCA fires on 2-month sustained-stress clusters, not single-day events. The canonical-date selection conflated warning state with dip-buy state (see 2015-08-24 case).

**New gate proposal (must be pre-committed before v2-C runs):**

> "For each of the N canonical stress regimes, CCA must fire at least once within ±K trading days of the regime's onset date."

Pre-committed parameters needed:
- The list of stress regimes (probably 4–6 across 2008–2026, picked from web-validated event chronology — NOT from looking at v2 fire dates)
- `K` (window tolerance) — must be picked from prior research, not after seeing data. Suggest 0–5 trading days.
- Onset definition (first day of regime, or first ≥−3% close, or first VIX > Nth percentile day)

### 3. Regime-conditioned attribution

Don't rely on aggregate full-history AUC. Compute per-window:
- Feature importance for `tactical`, `structural`, `speed.score`, `speed.state` separately
- Marginal AUC contribution: AUC(composite) vs AUC(composite without feature X)
- Stability of attribution across windows (high stability = robust signal; low stability = regime-dependent)

### 4. Vol-concentration check

Hypothesis: v2 dropped speed and concentrated remaining mass in vol-complex, possibly reducing effective dimensionality. Test by computing pairwise correlation of `tactical`, `structural`, `speed.score` within each window. If `tactical` and `structural` are already highly correlated, v2's composite is effectively one signal — fragile under regime change.

---

## What the v2-C spec should look like

When the spec brainstorm starts (post-WF-5 probe), it should:

1. **Pick exactly one of A/B/C** — not all three. Each is a distinct hypothesis with its own falsification criteria.
2. **Pre-commit AC-F1..F6 BEFORE running any backtest.** Same discipline as v2-A. Include:
   - AC-F1 / AC-F2: full-history AUC bars (lift bar should be higher than v2-A's +0.015 — we have more information now)
   - AC-F3 (reformulated): stress-cluster onset-window match per §2 above
   - AC-F4: per-window catastrophic-degradation gate (tolerance −0.02 or tighter)
   - AC-F5: WATCH% bar (v1 reference unchanged at 39.3%)
   - AC-F6: v1 unchanged (golden hash, same as v2-A)
   - **NEW AC-F7:** WF-5 specific gate — v2-C 60d AUC in WF-5 must NOT regress vs v1 by more than −0.02. This is the gate that v2-A failed; v2-C must pass it.
3. **Use the v2-A infrastructure as-is.** `FlipGateEvidence`, renderer, cleanup-on-failure, payload-hash idempotency, scoped-delete repo method — all reusable. Marginal cost of v2-C is the calibration JSON + the formula change.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-28 | v2-A rejected, terminal | AC-F4 + AC-F3 failed; WF-5 regression of −0.134 + 3 of 4 canonical CCA dates missed |
| 2026-05-28 | v2-C promoted to top of queue | Speed contribution in quiet regimes confirmed empirically |
| 2026-05-28 | Pre-spec docs first | WF-5 probe needed before direction-picking spec is written |
| 2026-05-28 | Probe 2 done — direction B leading | Forward-return probe: BTD fires (driven by speed=20) predict +11.4% / 60d in WF-5. v2-A's regression cost = +11.4% / 60d alpha. Direction B (rank inversion within BUY) preserves BTD activation; A and C don't (or only conditionally). |
| 2026-05-28 | CCA reframed as bottom signal | WF-3 CCA forward 60d = +14.9% (mean-reversion bounce, not warning). AC-F3 reformulation is now load-bearing, not optional. |
| 2026-05-28 | **Probe 3 done — direction B locked** | WF-5 BTD beats random-control at 100th pctile / p≈0 across all 3 horizons. Regime structure now legible: crisis = vol-complex + CCA; quiet = BTD. Direction B preserves both pathways. |
| TBD | WF-1 120d outlier check | BTD 120d pctile=13.54 (below null). Diagnostic before horizon weighting in v2-C spec. Not a B blocker. |
| TBD | VVIX % during BTD-fire days probe | Optional now — direction B is locked. Would refine VVIX-gate decision in the spec, not the direction call. |
| TBD | v2-C spec written | Next major step — direction B, AC-F1..F7 pre-committed, AC-F3 reformulated |

---

## References

- [v2-A executive summary §14](canary-5yr-executive-summary.md#14-v2-a-volspeed-separation-result-2026-05-28-terminal-verdict-for-v2-a)
- [PR #94 — research-only v2-A evidence pass](https://github.com/moremeds/unusual-whales/pull/94)
- [v2-A spec](../../superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md) (commit `09a2ea8`)
- [v2-A plan](../../superpowers/plans/2026-05-27-canary-v2a-vol-speed-separation-plan.md) (commit `6782af0`)
- WF-5 probe: `scripts/probe_canary_wf5.py`
