# VCG roadmap — 2026-05-28

**Status:** active. Supersedes `vcg-next-steps-2026-05-26.md` for VCG-direction questions (that file remains the source of truth for the credit-proxy A/B research it describes).

**Anchor evidence:** `vcg-forward-return-probes-2026-05-28.md` — 13 probes against `run_id=31` (4,710 days, 18.5yr at COMPOSITE_VERSION=2).

**Anchor positioning** (now §1 of `vcg-methodology.md`):
> VCG stress states should not be interpreted as bearish forward-return signals. PANIC and RISK_OFF are coincident vol-stress / capitulation regimes, not forward sell signals.

---

## 1. Decision matrix

### 1.1 Ruled out — do NOT build

| Item | Why | Probe |
|---|---|---|
| **NDX/RUT classifier math wiring** | 16 dispersion days in 18 years; 0 dispersion-only events overlap PANIC/RISK_OFF/EDR. Volume too low to change a classifier. | Probe 2 (dispersion-gap) |
| **VCG ∩ CRI joint bearish signal** | "Lagged + lagged" — VCG misses credit-led events, but those events do not draw down forward. Coverage without precision is not improvement. | Probe 13E (credit-coverage forward returns) |
| **VCG ∩ GEX joint validation today** | GEX history is ~257 trading days vs VCG's 4,710. Cannot validate over a meaningful sample. Reconsider once GEX has ≥3yr persisted history. | (capability gap, not probe) |
| **Buffered backwardation (1.05×) signal** | Buffer makes the signal *worse*, not better. Original unbuffered framing is correct. | Probe 10 (buffer sensitivity) |
| **BOUNCE productization** | n=5, dominated by 2008 GFC days. Not validated as a rebound signal. Mean fwd 60d return is −8.15%. Do not surface as a trade direction. | §6.9 of methodology |
| **Bullish-from-PANIC product copy** | Edge is tail-driven, not hit-rate-driven (median +0.34%, std 9.92%, p10 −8.82%). Calling PANIC a "buy signal" misrepresents the variance profile. | Probe 4 (PANIC event study) |

### 1.2 Deferred — research candidate, not yet build queue

| Item | Why deferred | Re-evaluate trigger |
|---|---|---|
| **Backwardation long-lag tracker (post-2018 only)** | n=8 = 5 distinct episodes (within-episode duplication). All post-2018; zero pre-2018 occurrences. "14-day threshold" is binning artifact. | After 2026-03 pending events mature (~2026-06-03) **and** at least 2 additional independent long-lag episodes accumulate. |
| **PANIC 20d stress-dip event study with execution realism** | Mean +2.88% is real but variance is extreme. Needs episode de-duplication, stop-loss rules, cluster control (2008/2020 can't dominate), entry timing (first PANIC day vs second), exit rules, slippage sensitivity. | When the user is ready to scope a backtest project specifically for stress-dip execution. |
| **VCG ∩ GEX joint** | See §1.1 | When GEX has ≥3yr persisted history (probably 2027-Q2 at earliest). |

### 1.3 Keep as ongoing research, no productization

| Item | Why ongoing |
|---|---|
| **OOS gate maintenance** for v2 calibration | Standard hygiene — runs from existing infra; no new work. |
| **Backwardation long-lag post-2018 hypothesis** | Validation cycle: each new episode is fresh OOS data. Wait, don't build. |

### 1.4 Build candidate — single recommended next-build

**Slow-grind price-regime overlay** (separate field/pill, NOT a VCG math change).

Motivation: §6.8 + Probe 5 found that 80.7% of "SPX −10% from 60d high" days are `NORMAL` / `SUPPRESSED`. Worst `SUPPRESSED` drawdown reached −26.5%. This is a real product gap: a user looking at `/regime` sees "SUPPRESSED" during a 20% slow-bleed bear market and interprets it as "market is safe."

**Sketch (full spec to follow under `docs/superpowers/specs/2026-05-28-price-regime-overlay-design.md`):**

```
Inputs:
- SPX close (vol_index_daily.close WHERE symbol='SPX')
- 60d rolling high
- 252d rolling high

Derived per-day fields:
- dd_60d_high   : SPX close vs trailing 60d max, in pct
- dd_252d_high  : SPX close vs trailing 252d max, in pct
- price_regime  : enum
    NORMAL        if dd_60d_high > -5%
    PULLBACK      if -10% < dd_60d_high ≤ -5%
    CORRECTION    if -20% < dd_60d_high ≤ -10%
    BEAR_GRIND    if dd_60d_high ≤ -20% OR ≥N consecutive days below -10%

Persistence:
- regime_backtest_daily.payload.price_regime
- regime_backtest_daily.payload.dd_60d_high
- regime_backtest_daily.payload.dd_252d_high

UI:
- Separate pill on /regime alongside VCG interpretation.
- Never overwrite VCG label. The two pills are independent.

Backtest:
- Compute over the existing 18.5yr SPX series; persist into a new backtest run.
- COMPOSITE_VERSION bump NOT required — price_regime is a parallel field, not a VCG component.
```

**Out of scope for this overlay:**
- Cross-asset (don't add NDX/RUT/IWM yet — those are watchlist work).
- Recession-vs-correction classification (start with drawdown depth + duration only).
- Joint signal with VCG (keep independent until both are individually validated).

---

## 2. Methodology updates locked in (already shipped to `vcg-methodology.md`)

- §1 — Added "Forward-return positioning" callout: "VCG stress states should not be interpreted as bearish forward-return signals."
- §6.8 — Stress states are coincident capitulation, not forward-bearish. Full probe table + trading implication.
- §6.9 — BOUNCE is not a validated forward-rebound signal. n=5 sample, 2008-GFC-dominated.

These edits should be referenced by any future VCG-related spec or product-doc work.

---

## 3. Open research questions (not actionable yet)

- **Why does PANIC have such an extreme right tail (p90 +17.66%)?** Hypothesis: PANIC concentrates in capitulation moments at vol peaks. If true, "vol peak proximity" (e.g. VIX rolling-percentile decay) would discriminate the right tail from the left. Out of scope until someone wants to scope it as a project.
- **Is the backwardation post-2018 era-shift real or sample-period noise?** Need ≥3 more independent episodes. Tracked in §1.2.
- **Does PANIC + a credit-canary filter improve hit rate?** Plausible (HYG/LQD divergence after PANIC could pre-filter the left tail), but speculative. Defer until PANIC dip-buy event-study is funded.

---

## 4. Process lessons (for future research planning)

- **Validate before building** killed three implementation projects at ~5 min SQL cost each: VCG ∩ GEX, backwardation-age tracker, VCG ∩ CRI bearish coverage. Each would have been 3-5 days to build on a signal that didn't hold up. Pattern: run forward-return probes against the existing backtest *before* writing a single line of classifier code.
- **Coverage ≠ precision.** Probe 13 series proved that "VCG misses X type of event" is only useful if "X events have adverse forward returns." Otherwise the gap is by-design noise filtering.
- **n=5 is not a signal.** BOUNCE was treated cautiously precisely because the small-n sample was era-bound. Apply the same skepticism to any post-2018-only result (e.g. backwardation long-lag).

---

## 5. Sequencing for the next 2 weeks

1. **This doc + methodology updates** ship as a docs PR (no code).
2. **VCG UI capitulation-framing PR** — see `docs/superpowers/plans/2026-05-28-vcg-ui-capitulation-framing-plan.md`. Operationalizes §6.8 in the product (forward-return columns + summary line + Signal Detail row + pill tooltip). Small UI win.
3. **Price-regime overlay** — brainstorm → spec → plan → PR. Spec target: `docs/superpowers/specs/2026-05-28-price-regime-overlay-design.md`. Plan target: `docs/superpowers/plans/2026-05-28-price-regime-overlay-plan.md`.
4. *(optional follow-ups)* PANIC dip-buy event study; backwardation post-2018 re-evaluation on 2026-06-03; renaming BOUNCE.
