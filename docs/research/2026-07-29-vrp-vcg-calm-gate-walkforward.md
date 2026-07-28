# Walk-forward validation — does the VCG calm gate survive OOS?

**Index**: SPX. **Overlap**: 4,758 sessions with both a VRP quote and a VCG score, 2007-08-23 → 2026-07-24. **OOS span**: 2013–2026 (14 folds).

The in-sample probe (`2026-07-29-vrp-vcg-calm-gate.md`) declined to wire the gate in and set this bar: re-fit the |z| threshold **inside each training window** instead of choosing it once on the whole sample. This is that test.

Expanding window: train on everything through year Y−1, choose the threshold by train Sharpe, score year Y, advance. Every fold's threshold is selected from `gate0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0` — `None` (no veto) is in the menu on purpose, so a fold that finds no useful threshold can say so rather than being forced to fit noise. A training window with fewer than 20 trades falls back to no veto.

All four arms are scored on the **same concatenated OOS months**. `refit` vs `gate0` decides deployment; `refit` vs `fixed1.0` isolates whether re-fitting adds anything over the earlier hand-picked value.

## Verdict — survives in most cells, with one real failure

**1. `refit` vs `gate0` (the deployment question)**: wins on OOS Sharpe in **3/4** grid cells. Margins: +0.06, +0.33, -0.31, +0.38. The loser(s): **0.25Δ/30d** (1.07 vs 1.39). That is not a rounding error and it is not explained away by the other three — a rule that reverses on one plausible structural config is a rule whose config choice is now load-bearing.

**2. Against always-on**: `refit` wins **4/4**. A gate that beats `gate0` but loses to doing nothing is not a gate worth shipping — `gate0` is a low bar, as the in-sample probe already noted.

**3. Does re-fitting beat the hand-picked 1.0?** `refit` beats `fixed1.0` in **3/4** cells. Re-fitting costs a degree of freedom; if it does not clear the fixed value, the extra machinery is buying variance, not edge.

**4. Drawdown**: `refit` improves maxDD versus `gate0` in **3/4** cells, mean +1.73× max-loss. Drawdown control was the strongest in-sample claim, so this is where survival matters most.

**5. Per-window catastrophic-degradation gate**: `refit` passes in **0/4** cells — but so does `always` in **0/4** and `gate0` in **0/4**. **The gate does not discriminate on this book**: the ungated baseline fails it too, so it is describing short vol as an asset class — 2018Q1 and 2020Q1 reverse the sign with larger magnitude whatever the entry rule — rather than indicting the candidate. Reporting refit's failure without this line would be a misread dressed as rigour. A short-vol book has a left tail; that is the trade, not a defect the gate discovered.

**6. Threshold stability**: the anchor config picked **1 distinct value(s)** (0.75) across 14 folds, with 0 declining to veto at all. Every training window landed on the same threshold — no added year was ever enough to move it. That directly contradicts the in-sample probe's read that the parameter 'flips between halves': the era split compared two hand-cut windows, this re-fits from scratch 14 times and never wavers. Note also that the fitter chose a value the earlier probe never tested. Caveat that limits the strength of this: expanding windows are nested, so the 14 choices are autocorrelated by construction and are not 14 independent confirmations.

### Limits of this test

Flat-vol pricing with no skew, so a put spread's real credit is understated. One-at-a-time ladder, so the gate mostly shifts *when* trades open rather than how many. SPX only. Each fold's ladder starts flat, so a position open at a fold boundary is not carried across it. The VCG z itself is computed on a trailing 63-session window and is not re-derived per fold — only the *threshold* is re-fit, so a residual in-sample component remains in the signal's own normalisation.

## SPX · 0.20Δ short · 20-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar | quarter gate |
|---|---:|---:|---:|---:|---:|:--:|
| always | 163 | 0.72 | 0.80 | -2.59 | 0.31 | FAIL |
| gate0 | 135 | 1.03 | 0.92 | -3.42 | 0.27 | FAIL |
| fixed1.0 | 128 | 1.08 | 0.93 | -1.15 | 0.81 | FAIL |
| refit | 126 | 1.10 | 0.95 | -1.15 | 0.83 | FAIL |

`refit` vs `gate0`: Sharpe +0.06, maxDD +2.27 xmaxloss. `refit` vs `fixed1.0`: Sharpe +0.02.

## SPX · 0.25Δ short · 20-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar | quarter gate |
|---|---:|---:|---:|---:|---:|:--:|
| always | 163 | 0.75 | 0.96 | -3.76 | 0.26 | FAIL |
| gate0 | 135 | 1.03 | 1.11 | -3.85 | 0.29 | FAIL |
| fixed1.0 | 128 | 1.17 | 1.20 | -1.62 | 0.74 | FAIL |
| refit | 126 | 1.35 | 1.31 | -1.05 | 1.25 | FAIL |

`refit` vs `gate0`: Sharpe +0.33, maxDD +2.80 xmaxloss. `refit` vs `fixed1.0`: Sharpe +0.18.

## SPX · 0.25Δ short · 30-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar | quarter gate |
|---|---:|---:|---:|---:|---:|:--:|
| always | 121 | 1.02 | 1.07 | -3.17 | 0.34 | FAIL |
| gate0 | 101 | 1.39 | 1.14 | -1.01 | 1.12 | FAIL |
| fixed1.0 | 99 | 1.49 | 1.16 | -1.01 | 1.15 | FAIL |
| refit | 99 | 1.07 | 0.95 | -1.41 | 0.68 | FAIL |

`refit` vs `gate0`: Sharpe -0.31, maxDD -0.40 xmaxloss. `refit` vs `fixed1.0`: Sharpe -0.42.

## SPX · 0.30Δ short · 20-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar | quarter gate |
|---|---:|---:|---:|---:|---:|:--:|
| always | 163 | 0.78 | 1.16 | -4.87 | 0.24 | FAIL |
| gate0 | 135 | 1.07 | 1.33 | -3.49 | 0.38 | FAIL |
| fixed1.0 | 128 | 1.27 | 1.48 | -1.73 | 0.86 | FAIL |
| refit | 126 | 1.45 | 1.59 | -1.23 | 1.30 | FAIL |

`refit` vs `gate0`: Sharpe +0.38, maxDD +2.27 xmaxloss. `refit` vs `fixed1.0`: Sharpe +0.18.

## What each training window chose

A threshold that will not sit still has not been identified. This table is the honest record of how much the fitted value moves.

| test year | chosen |z| threshold (0.25Δ/20d) | refit OOS ROR | gate0 OOS ROR |
|---|---|---:|---:|
| 2013 | < 0.75 | +1.92 | +1.91 |
| 2014 | < 0.75 | +0.66 | +0.84 |
| 2015 | < 0.75 | +0.83 | +0.60 |
| 2016 | < 0.75 | +1.17 | +1.40 |
| 2017 | < 0.75 | +2.24 | +2.46 |
| 2018 | < 0.75 | -0.40 | -1.66 |
| 2019 | < 0.75 | +1.07 | -0.27 |
| 2020 | < 0.75 | +1.14 | +0.14 |
| 2021 | < 0.75 | +2.12 | +2.61 |
| 2022 | < 0.75 | +0.45 | -0.77 |
| 2023 | < 0.75 | +2.55 | +2.46 |
| 2024 | < 0.75 | +1.55 | +1.55 |
| 2025 | < 0.75 | +1.09 | +2.27 |
| 2026 | < 0.75 | +1.18 | +1.41 |

**1 distinct value(s)** across 14 folds (0.75); **0/14** folds chose no veto at all.

**Do not read this as 14 independent confirmations.** The windows are *expanding*, so fold 14's training set contains fold 2's almost entirely; consecutive choices are heavily autocorrelated by construction. What the column honestly shows is that the choice is **not fragile** — no single added year was ever enough to flip it — which is a weaker claim than independent replication, and a stronger one than the in-sample probe's era-split could make.

