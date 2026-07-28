# Does the VCG calm core improve the VRP macro short-vol book?

**Index**: SPX. **Overlap**: 4,758 sessions with both a VRP quote and a VCG score, 2007-08-23 → 2026-07-24.

Same P&L machinery as `scripts/_vrp_macro_param_sweep.py` (`build_bull_put_spread`, `CostModel`, `monthly_summary`); the **only** difference between arms is the sizing function, so any Sharpe gap is the gate and not a re-implementation. One-at-a-time ladder, flat-vol pricing, model-free settle at the realised close, long wing as the stop.

**The comparison that matters is `gate0_and_calm` vs `gate0`.** Beating `always` proves nothing — `gate0` already does that.

| arm | rule |
|---|---|
| `always` | 1.0 — structural baseline |
| `gate0` | `vrp_z >= 0` — the committed winner |
| `vcg_calm` | `abs(vcg_z) < 1` — the new candidate, alone |
| `gate0_and_calm` | `vrp_z >= 0 AND abs(vcg_z) < 1` |
| `gate0_not_armed` | `vrp_z >= 0 AND abs(vcg_z) < 2` — weaker veto |

## Verdict — promising, NOT proven. Do not wire it in yet.

**1. It reliably repairs `gate0`.** `gate0_and_calm` beats `gate0` on Sharpe in **4/4** grid cells and in both eras. That is a consistent, real effect.

**2. But that is a low bar — `gate0` is itself beaten by doing nothing** in 3/4 cells. Against always-on the combined gate does win **4/4**, but the margins are thin: +0.11, +0.04, +0.39, +0.03 Sharpe. And the era split breaks it — in 2007–2016 the gate returns 0.79 against an always-on 1.14. Much of what the calm filter does is undo damage `gate0` caused rather than add alpha over always-on.

**3. Where it does win is drawdown.** maxDD improves versus always-on in **4/4** cells, by 1.46× max-loss on average (e.g. 0.25Δ/30d: −2.83 → −1.01, Calmar 0.26 → 0.89). If this survives, it is a **drawdown-control overlay**, not a return engine — which is still worth having on a short-vol book, where the tail is the whole risk.

**4. VCG alone is not a gate.** `vcg_calm` on its own underperforms always-on in **4/4** cells. It only does work in conjunction with `vrp_z`, which means it is a conditioning variable, not a signal.

**5. The threshold looks unstable here.** |z| < 1 and |z| < 2 rank differently across eras — in 2017→now the weaker veto is *better* (1.06 vs 1.03), in 2007–2016 it is much worse (0.48 vs 0.79). A parameter whose ordering flips between halves has not been identified, it has been fitted.

> **Superseded on this point.** `2026-07-29-vrp-vcg-calm-gate-walkforward.md` re-fits the threshold from scratch on 14 expanding training windows and every one picks 0.75 — a value this probe never tested. The instability above is an artifact of comparing two hand-cut eras at two hand-picked thresholds, not a property of the parameter. The rest of this verdict stands.

### What would make this deployable

Not another in-sample table. It needs the committed walk-forward harness (`src/uw_scan/backtest/`, which already has per-window OOS gates and the per-regime catastrophic-degradation check) with the |z| threshold **re-fit inside each training window** rather than chosen once on the whole sample. If the gate survives that, it earns a place in the VRP entry path. If it does not, this file is the record of why not.

**Honest accounting of this probe's weaknesses**: the threshold was chosen on 2007–2026 SPX vol and scored on overlapping 2007–2026 SPX option P&L — not out-of-sample; flat-vol pricing with no skew, so a put spread's real credit is understated; a one-at-a-time ladder means the gate mostly shifts *when* trades open rather than how many, so trade counts barely move between arms; and SPX-only, single index.

## SPX · 0.20Δ short · 20-day hold

| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| always | 226 | 100 | 0.71 | 0.81 | -3.94 | 0.21 |
| gate0 | 187 | 55 | 0.62 | 0.63 | -3.28 | 0.19 |
| vcg_calm | 221 | 73 | 0.49 | 0.59 | -3.72 | 0.16 |
| gate0_and_calm | 178 | 41 | 0.81 | 0.76 | -2.45 | 0.31 |
| gate0_not_armed | 183 | 52 | 0.72 | 0.70 | -2.45 | 0.28 |

`gate0_and_calm` vs `gate0`: Sharpe +0.19, maxDD +0.83 xmaxloss, trades -9.

## SPX · 0.25Δ short · 20-day hold

| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| always | 226 | 100 | 0.87 | 1.11 | -3.62 | 0.31 |
| gate0 | 187 | 55 | 0.64 | 0.77 | -3.85 | 0.20 |
| vcg_calm | 221 | 73 | 0.63 | 0.85 | -4.16 | 0.20 |
| gate0_and_calm | 178 | 41 | 0.91 | 0.99 | -2.08 | 0.47 |
| gate0_not_armed | 183 | 52 | 0.74 | 0.86 | -2.08 | 0.41 |

`gate0_and_calm` vs `gate0`: Sharpe +0.27, maxDD +1.77 xmaxloss, trades -9.

## SPX · 0.25Δ short · 30-day hold

| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| always | 153 | 100 | 0.65 | 0.73 | -2.83 | 0.26 |
| gate0 | 134 | 55 | 0.81 | 0.78 | -1.64 | 0.48 |
| vcg_calm | 151 | 73 | 0.60 | 0.68 | -3.44 | 0.20 |
| gate0_and_calm | 132 | 41 | 1.04 | 0.90 | -1.01 | 0.89 |
| gate0_not_armed | 133 | 52 | 0.84 | 0.79 | -1.22 | 0.64 |

`gate0_and_calm` vs `gate0`: Sharpe +0.23, maxDD +0.63 xmaxloss, trades -2.

## SPX · 0.30Δ short · 20-day hold

| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| always | 226 | 100 | 0.95 | 1.36 | -3.07 | 0.44 |
| gate0 | 187 | 55 | 0.70 | 0.97 | -3.49 | 0.28 |
| vcg_calm | 221 | 73 | 0.75 | 1.12 | -4.58 | 0.25 |
| gate0_and_calm | 178 | 41 | 0.98 | 1.23 | -2.07 | 0.59 |
| gate0_not_armed | 183 | 52 | 0.78 | 1.03 | -2.07 | 0.50 |

`gate0_and_calm` vs `gate0`: Sharpe +0.28, maxDD +1.43 xmaxloss, trades -9.

## Era split — 0.25Δ / 20-day, split at 2017-01-01

The gate threshold was chosen on the full sample, so this is *not* clean OOS. It only answers the weaker question: does the gate behave consistently across halves, or is it one regime's artifact?

### 2007→2016

| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| always | 113 | 100 | 1.14 | 1.35 | -2.32 | 0.58 |
| gate0 | 94 | 55 | 0.51 | 0.65 | -2.08 | 0.31 |
| vcg_calm | 110 | 73 | 0.49 | 0.69 | -4.16 | 0.17 |
| gate0_and_calm | 89 | 41 | 0.79 | 0.89 | -2.08 | 0.43 |
| gate0_not_armed | 92 | 52 | 0.48 | 0.60 | -2.08 | 0.29 |

### 2017→now

| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| always | 114 | 100 | 0.87 | 1.10 | -2.03 | 0.54 |
| gate0 | 93 | 55 | 0.77 | 0.90 | -3.85 | 0.23 |
| vcg_calm | 111 | 73 | 0.62 | 0.82 | -3.00 | 0.28 |
| gate0_and_calm | 89 | 42 | 1.03 | 1.09 | -1.62 | 0.67 |
| gate0_not_armed | 92 | 52 | 1.06 | 1.13 | -1.78 | 0.63 |

