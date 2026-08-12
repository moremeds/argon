# DECISION — stage 2 ships `equal_7`, the validated construction

*2026-08-12 · numbers in `weighting.json` / `results.md`*

## The problem

The validated claim — 2q composite IC 0.039 leak-free, t 2.67 — was produced by an
**equal-weighted** mean of seven raw feature z-scores. Spec §5.2 seeds a *different*
weight set, which §5.2 itself records as unswept. Seeding those into
`fundamental_method_params` and then citing the IC would ship an unvalidated signal
under a validated number.

## Measured, not argued

| construction | IC (1q) | independent t | **paired t vs equal_7** |
|---|---:|---:|---:|
| `equal_7` (validated) | +0.0376 | +3.09 | — |
| `rubric` (§5.2 seeds) | +0.0491 | +4.11 | **+1.79** |
| `no_margins` (post-hoc) | +0.0552 | +4.93 | +2.52 |

**The paired column is the one that decides, and it reverses the reading.** All three
series are built from the same features on the same 79 quarters, so they are heavily
correlated; comparing independent t-stats treats shared quarters as independent evidence
and overstates every gap. Matched quarter-by-quarter, the rubric's advantage is
**t 1.79 — not significant**, on a 57% win rate that is close to a coin flip.

`no_margins` does clear significance at t 2.52, and is still **not shippable**: its two
dropped components were selected *after* observing that both measured inverted. Choosing
components on their realised sign guarantees an in-sample improvement, and the same IC
cannot then detect the overfit. It needs a pre-committed out-of-sample test before it is
a candidate rather than a diagnostic.

## Ruling

1. **`v1_equal` is the active method version** — equal weight across the seven features,
   byte-verified against `V.composite_scores` by a self-check in the probe so the shipped
   composite is the validated one and not merely similar to it.
2. **`v1_rubric` and `v1_no_margins` are seeded as INACTIVE candidates.** Recording them
   as rows costs nothing, keeps the user ruling that weights are data rather than code,
   and means the eventual sweep has its alternatives already expressed in the same schema.
3. **No IC may be quoted for an inactive version.** The only construction with a defensible
   number is the active one.
4. The sweep that would legitimately replace the active version needs walk-forward
   out-of-sample discipline — argon already owns that harness (`backtest/` +
   `backtest_sweep_runs`), which is where this belongs, not here.

## Why this is worth the detour

The eyeball reading (t 4.11 beats t 3.09, ship the rubric) would have replaced a validated
construction with an untested one on evidence that evaporates under the correct test. The
paired comparison cost one function and reversed the conclusion.
