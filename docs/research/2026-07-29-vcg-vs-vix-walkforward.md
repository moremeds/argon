# Is the VCG calm gate anything more than a VIX filter?

**Index**: SPX. **Universe**: 4,758 sessions with a VRP quote, a VCG score and a trailing-252 VIX rank, 2007-08-23 → 2026-07-24. **OOS span**: 2013–2026 (14 folds).

The walk-forward result (`2026-07-29-vrp-vcg-calm-gate-walkforward.md`) showed the calm gate survives OOS. It did **not** show the credit leg was doing the work. VCG is built from VIX/VVIX versus credit, so a calm VCG day is a low-VIX day, and low VIX predicting low forward vol is the best-known fact in the field. This script asks whether anything survives once VIX is given its own arm.

Raw correlation of `vcg_z` with the VIX level over 4,758 shared sessions: **-0.030**.

| arm | rule |
|---|---|
| `always` | no gate |
| `gate0` | `vrp_z >= 0` |
| `calm` | `gate0` AND `abs(vcg_z) < t` — t re-fit per fold |
| `vix_low` | `gate0` AND trailing-252 VIX percentile `< p` — p re-fit per fold |
| `resid` | `gate0` AND `abs(vcg_z residualised on VIX) < t` — OLS fit on train only |

The VIX percentile is ranked within the 252 sessions **strictly before** the entry date. `resid` fits `vcg_z ~ a + b*VIX` on the training window only and applies those coefficients out-of-sample, so it measures the part of VCG that VIX cannot explain.

## Verdict — VCG carries content VIX does not

Sharpe by arm across the 4 grid cells:

- `gate0`: 1.03, 1.03, 1.39, 1.07
- `calm`: 1.10, 1.35, 1.07, 1.45
- `vix_low`: 1.06, 1.18, 0.85, 1.07
- `resid`: 1.10, 1.36, 1.07, 1.47

**1. Does the cheap rival work?** `vix_low` beats `gate0` in **3/4** cells. If this matches `calm`'s **3/4**, the calm gate was reading the VIX level.

**2. Head to head.** `calm` beats `vix_low` in **4/4** cells. This is the question — a tie means prefer VIX: fewer inputs, no HYG capture dependency, no 63-session normalisation to maintain.

**3. What survives orthogonalisation?** `resid` — VCG with VIX regressed out — beats `gate0` in **3/4** cells and `vix_low` in **4/4**. This is the strictest test of whether the credit leg carries independent information.

**4. How much of VCG is VIX?** Raw correlation **-0.030**. The per-fold OLS slopes in the table above show how stable that relationship is across training windows.

### Limits

Flat-vol pricing with no skew. One-at-a-time ladder. SPX only. The VIX arm gets a trailing-252 percentile, which is one reasonable specification among several — a different lookback or an absolute VIX level might do better or worse, so 'VIX does not work here' is weaker than 'VIX cannot work'. The residual is linear in the VIX level only; a non-linear or VVIX-inclusive control could absorb more.

## SPX · 0.20Δ short · 20-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|
| always | 163 | 0.72 | 0.80 | -2.59 | 0.31 |
| gate0 | 135 | 1.03 | 0.92 | -3.42 | 0.27 |
| calm | 126 | 1.10 | 0.95 | -1.15 | 0.83 |
| vix_low | 64 | 1.06 | 0.56 | -1.01 | 0.56 |
| resid | 126 | 1.10 | 0.95 | -1.15 | 0.83 |

## SPX · 0.25Δ short · 20-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|
| always | 163 | 0.75 | 0.96 | -3.76 | 0.26 |
| gate0 | 135 | 1.03 | 1.11 | -3.85 | 0.29 |
| calm | 126 | 1.35 | 1.31 | -1.05 | 1.25 |
| vix_low | 76 | 1.18 | 0.83 | -1.12 | 0.75 |
| resid | 126 | 1.36 | 1.32 | -1.05 | 1.26 |

## SPX · 0.25Δ short · 30-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|
| always | 121 | 1.02 | 1.07 | -3.17 | 0.34 |
| gate0 | 101 | 1.39 | 1.14 | -1.01 | 1.12 |
| calm | 99 | 1.07 | 0.95 | -1.41 | 0.68 |
| vix_low | 86 | 0.85 | 0.78 | -1.65 | 0.47 |
| resid | 99 | 1.07 | 0.95 | -1.41 | 0.68 |

## SPX · 0.30Δ short · 20-day hold

| arm | OOS trades | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |
|---|---:|---:|---:|---:|---:|
| always | 163 | 0.78 | 1.16 | -4.87 | 0.24 |
| gate0 | 135 | 1.07 | 1.33 | -3.49 | 0.38 |
| calm | 126 | 1.45 | 1.59 | -1.23 | 1.30 |
| vix_low | 80 | 1.07 | 0.97 | -1.43 | 0.68 |
| resid | 126 | 1.47 | 1.61 | -1.23 | 1.31 |

## What each training window chose (0.25Δ/20d)

| test year | calm |z| | VIX pct | resid |z| | OLS slope b |
|---|---|---|---|---:|
| 2013 | 0.75 | 0.4 | 0.75 | -0.002 |
| 2014 | 0.75 | 0.4 | 0.75 | -0.002 |
| 2015 | 0.75 | 0.4 | 0.75 | -0.002 |
| 2016 | 0.75 | 0.5 | 0.75 | -0.002 |
| 2017 | 0.75 | 0.5 | 0.75 | -0.002 |
| 2018 | 0.75 | 0.5 | 0.75 | -0.001 |
| 2019 | 0.75 | 0.2 | 0.75 | -0.001 |
| 2020 | 0.75 | 0.3 | 0.75 | -0.002 |
| 2021 | 0.75 | 0.3 | 0.75 | -0.004 |
| 2022 | 0.75 | 0.3 | 0.75 | -0.004 |
| 2023 | 0.75 | 0.3 | 0.75 | -0.004 |
| 2024 | 0.75 | 0.3 | 0.75 | -0.003 |
| 2025 | 0.75 | 0.4 | 0.75 | -0.003 |
| 2026 | 0.75 | 0.4 | 0.75 | -0.004 |

