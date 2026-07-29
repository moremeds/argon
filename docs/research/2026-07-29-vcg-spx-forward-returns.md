# VCG z-score vs forward SPX — does the signal predict anything?

**Sample**: 4,758 aligned sessions, 2007-08-23 → 2026-07-24 (18.9 years). Proxy HYG, `basis='eod'`.

**Reproduce**: `PGPASSWORD=… uv run python scripts/research/vcg_spx_forward_returns.py --host 100.66.147.98 --db option_wizard`

Prior work asked this of the categorical cascade states and found VCG descriptive, not predictive (`docs/research/regime/vcg-forward-return-probes-2026-05-28.md`). This probe asks it of the **continuous z** and of the **arming thresholds the panel now draws** (|z| ≥ 2.0, ≥ 2.5).

All t-stats are **Newey–West corrected with lag = h − 1**. Forward windows overlap, so daily observations are heavily autocorrelated; a naive t-stat on overlapping h-day returns is inflated by roughly √h.

## Verdict

**VCG does not predict SPX direction — at any threshold, at any horizon. It does carry information about forward volatility.**

1. **Direction: dead.** Across all 30 rule×horizon cells in Q2, the largest |t vs rest| is **1.10** (`armed  z >= +2.0`, h=10). Nothing approaches significance. The `t vs 0` column looks better and is a mirage: SPX drifts up, so long-horizon buckets clear a zero-null trivially — `z >= +2.0` at h=63 scores t=+3.20 against zero and **+0.24** against the rest of the sample.
2. **The era split confirms it.** Armed days return +0.50% vs a +0.51% baseline pre-2017, and +1.24% vs +1.17% after. Both halves: no edge, and the apparent improvement in the second half is the baseline rising, not the signal working.
3. **Volatility: a real but modest signal.** Both tails predict elevated forward realised vol, and the calm core predicts calm — the |z| < 1 bucket (n=3,486) runs below-baseline vol at 5d with t=-2.72. That large-n cell is the most robust result here.
4. **But the tails are crisis-driven.** `z <= -2.5` shows 5d mean vol of 30.7% vs a 15.6% baseline — a +15.2pt lift whose **median lift is only +2.1pt**. The mean is a handful of 2008/2020 episodes. With n=73 clustered into a few autocorrelated episodes, the effective sample is far below nominal and t≈2 is weak evidence.

**How to use it:** as a volatility-regime classifier, not a directional one. The most defensible cell is the calm core — |z| < 1 marking below-baseline forward vol is the kind of permissive gate a short-vol/VRP book wants, and it rests on 3,486 observations rather than 73. Reading an armed VCG as 'sell equities' is empirically unsupported.

**Limitations.** Overlapping windows (NW-corrected, but episode clustering still inflates effective n); extreme buckets are 54–83 observations spanning few distinct episodes; SPX close-to-close with no dividends, costs, or slippage; no multiple-testing correction across the 30 Q2 cells — with that many looks, a |t| near 2 is expected by chance alone.

## Q1 — Forward SPX returns by z bucket

### h = 1 sessions  ·  baseline mean +0.04%  (n=4,757)

| z bucket | n | mean % | median % | win % | NW t | vs base |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | +0.19 | +0.20 | 60.3 | +0.58 | +0.15 |
| -2.5 < z <= -2.0 | 83 | -0.19 | -0.12 | 45.8 | -1.39 | -0.24 |
| -2.0 < z <= -1.0 | 488 | +0.03 | +0.02 | 51.4 | +0.44 | -0.01 |
| -1.0 < z <  +1.0 | 3,490 | +0.04 | +0.08 | 54.6 | +2.12 | +0.00 |
| +1.0 <= z < +2.0 | 503 | +0.06 | +0.10 | 56.7 | +1.07 | +0.02 |
| +2.0 <= z < +2.5 | 66 | +0.17 | +0.22 | 59.1 | +1.37 | +0.13 |
| z >= +2.5 | 54 | +0.00 | -0.06 | 46.3 | +0.00 | -0.04 |

### h = 5 sessions  ·  baseline mean +0.20%  (n=4,753)

| z bucket | n | mean % | median % | win % | NW t | vs base |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | +0.22 | +0.63 | 60.3 | +0.36 | +0.01 |
| -2.5 < z <= -2.0 | 83 | +0.17 | +0.15 | 55.4 | +0.60 | -0.03 |
| -2.0 < z <= -1.0 | 488 | +0.19 | +0.38 | 58.0 | +1.35 | -0.02 |
| -1.0 < z <  +1.0 | 3,486 | +0.19 | +0.38 | 59.4 | +3.07 | -0.01 |
| +1.0 <= z < +2.0 | 503 | +0.28 | +0.41 | 59.8 | +2.10 | +0.07 |
| +2.0 <= z < +2.5 | 66 | +0.65 | +0.87 | 68.2 | +2.95 | +0.45 |
| z >= +2.5 | 54 | -0.12 | +0.42 | 55.6 | -0.28 | -0.33 |

### h = 10 sessions  ·  baseline mean +0.40%  (n=4,748)

| z bucket | n | mean % | median % | win % | NW t | vs base |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | +0.13 | +1.19 | 64.4 | +0.16 | -0.28 |
| -2.5 < z <= -2.0 | 83 | +0.74 | +1.18 | 60.2 | +2.36 | +0.33 |
| -2.0 < z <= -1.0 | 488 | +0.39 | +0.61 | 59.0 | +1.64 | -0.01 |
| -1.0 < z <  +1.0 | 3,481 | +0.37 | +0.68 | 62.2 | +3.11 | -0.03 |
| +1.0 <= z < +2.0 | 503 | +0.47 | +0.86 | 63.6 | +2.54 | +0.07 |
| +2.0 <= z < +2.5 | 66 | +1.01 | +1.42 | 69.7 | +4.35 | +0.61 |
| z >= +2.5 | 54 | +0.81 | +1.65 | 74.1 | +1.26 | +0.41 |

### h = 21 sessions  ·  baseline mean +0.84%  (n=4,737)

| z bucket | n | mean % | median % | win % | NW t | vs base |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | +0.68 | +1.77 | 60.3 | +0.39 | -0.16 |
| -2.5 < z <= -2.0 | 83 | +0.68 | +1.27 | 60.2 | +1.44 | -0.16 |
| -2.0 < z <= -1.0 | 487 | +1.11 | +1.51 | 65.3 | +2.85 | +0.27 |
| -1.0 < z <  +1.0 | 3,471 | +0.77 | +1.45 | 65.8 | +3.06 | -0.07 |
| +1.0 <= z < +2.0 | 503 | +1.03 | +1.45 | 65.4 | +3.27 | +0.19 |
| +2.0 <= z < +2.5 | 66 | +1.21 | +1.35 | 69.7 | +1.89 | +0.36 |
| z >= +2.5 | 54 | +1.11 | +3.50 | 72.2 | +0.99 | +0.27 |

### h = 63 sessions  ·  baseline mean +2.49%  (n=4,695)

| z bucket | n | mean % | median % | win % | NW t | vs base |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | +1.84 | +3.53 | 65.8 | +0.72 | -0.65 |
| -2.5 < z <= -2.0 | 83 | +2.94 | +3.41 | 67.5 | +5.33 | +0.44 |
| -2.0 < z <= -1.0 | 483 | +2.43 | +3.39 | 68.5 | +2.68 | -0.06 |
| -1.0 < z <  +1.0 | 3,438 | +2.59 | +3.81 | 73.2 | +3.45 | +0.10 |
| +1.0 <= z < +2.0 | 500 | +1.83 | +3.37 | 64.8 | +2.04 | -0.66 |
| +2.0 <= z < +2.5 | 64 | +3.44 | +4.35 | 71.9 | +5.92 | +0.95 |
| z >= +2.5 | 54 | +1.95 | +3.09 | 63.0 | +1.11 | -0.54 |

## Q2 — The arming thresholds the panel draws

`t vs 0` tests the bucket mean against zero — it clears easily at long horizons purely because SPX drifts up. **`t vs rest` is the one that matters**: it tests the rule against every other session in the sample.

| rule | h | n | mean % | median % | win % | t vs 0 | vs base | **t vs rest** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| armed  |z| >= 2.0 | 1 | 276 | +0.03 | +0.05 | 52.9 | +0.30 | -0.01 | **-0.08** |
| armed  |z| >= 2.0 | 5 | 276 | +0.24 | +0.59 | 59.8 | +0.78 | +0.04 | **+0.13** |
| armed  |z| >= 2.0 | 10 | 276 | +0.66 | +1.36 | 66.3 | +1.25 | +0.25 | **+0.50** |
| armed  |z| >= 2.0 | 21 | 276 | +0.89 | +1.45 | 64.9 | +1.14 | +0.05 | **+0.07** |
| armed  |z| >= 2.0 | 63 | 274 | +2.57 | +3.36 | 67.2 | +1.97 | +0.07 | **+0.05** |
| | | | | | | | | |
| armed  z <= -2.0 | 1 | 156 | -0.02 | +0.02 | 52.6 | -0.09 | -0.06 | **-0.35** |
| armed  z <= -2.0 | 5 | 156 | +0.19 | +0.51 | 57.7 | +0.49 | -0.01 | **-0.02** |
| armed  z <= -2.0 | 10 | 156 | +0.45 | +1.18 | 62.2 | +0.90 | +0.05 | **+0.10** |
| armed  z <= -2.0 | 21 | 156 | +0.68 | +1.33 | 60.3 | +0.77 | -0.16 | **-0.18** |
| armed  z <= -2.0 | 63 | 156 | +2.42 | +3.43 | 66.7 | +1.52 | -0.07 | **-0.04** |
| | | | | | | | | |
| armed  z >= +2.0 | 1 | 120 | +0.10 | +0.08 | 53.3 | +0.78 | +0.05 | **+0.44** |
| armed  z >= +2.0 | 5 | 120 | +0.30 | +0.67 | 62.5 | +1.01 | +0.10 | **+0.33** |
| armed  z >= +2.0 | 10 | 120 | +0.92 | +1.46 | 71.7 | +1.98 | +0.52 | **+1.10** |
| armed  z >= +2.0 | 21 | 120 | +1.16 | +2.32 | 70.8 | +1.88 | +0.32 | **+0.50** |
| armed  z >= +2.0 | 63 | 118 | +2.76 | +3.18 | 67.8 | +3.20 | +0.27 | **+0.24** |
| | | | | | | | | |
| RISK_OFF  |z| >= 2.5 | 1 | 127 | +0.11 | +0.07 | 54.3 | +0.52 | +0.07 | **+0.33** |
| RISK_OFF  |z| >= 2.5 | 5 | 127 | +0.07 | +0.62 | 58.3 | +0.16 | -0.13 | **-0.30** |
| RISK_OFF  |z| >= 2.5 | 10 | 127 | +0.42 | +1.34 | 68.5 | +0.54 | +0.01 | **+0.02** |
| RISK_OFF  |z| >= 2.5 | 21 | 127 | +0.86 | +2.22 | 65.4 | +0.57 | +0.02 | **+0.02** |
| RISK_OFF  |z| >= 2.5 | 63 | 127 | +1.89 | +3.15 | 64.6 | +0.74 | -0.61 | **-0.24** |
| | | | | | | | | |
| RISK_OFF  z <= -2.5 | 1 | 73 | +0.19 | +0.20 | 60.3 | +0.58 | +0.15 | **+0.46** |
| RISK_OFF  z <= -2.5 | 5 | 73 | +0.22 | +0.63 | 60.3 | +0.36 | +0.01 | **+0.02** |
| RISK_OFF  z <= -2.5 | 10 | 73 | +0.13 | +1.19 | 64.4 | +0.16 | -0.28 | **-0.35** |
| RISK_OFF  z <= -2.5 | 21 | 73 | +0.68 | +1.77 | 60.3 | +0.39 | -0.16 | **-0.09** |
| RISK_OFF  z <= -2.5 | 63 | 73 | +1.84 | +3.53 | 65.8 | +0.72 | -0.65 | **-0.25** |
| | | | | | | | | |
| RISK_OFF  z >= +2.5 | 1 | 54 | +0.00 | -0.06 | 46.3 | +0.00 | -0.04 | **-0.18** |
| RISK_OFF  z >= +2.5 | 5 | 54 | -0.12 | +0.42 | 55.6 | -0.28 | -0.33 | **-0.73** |
| RISK_OFF  z >= +2.5 | 10 | 54 | +0.81 | +1.65 | 74.1 | +1.26 | +0.41 | **+0.63** |
| RISK_OFF  z >= +2.5 | 21 | 54 | +1.11 | +3.50 | 72.2 | +0.99 | +0.27 | **+0.24** |
| RISK_OFF  z >= +2.5 | 63 | 54 | +1.95 | +3.09 | 63.0 | +1.11 | -0.54 | **-0.29** |
| | | | | | | | | |

## Q3 — Forward realised SPX vol by z bucket

Vol is the hypothesis most likely to hold: VCG is built from VIX/VVIX and a credit proxy, so it should co-move with future realised vol even if it says nothing about direction.

### h = 5 sessions  ·  baseline realised vol 15.6%  (n=4,753)

| z bucket | n | mean vol % | median vol % | vs base | median vs base | **t vs rest** |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | 30.7 | 14.5 | +15.2 | +2.1 | **+2.08** |
| -2.5 < z <= -2.0 | 83 | 19.0 | 14.1 | +3.4 | +1.7 | **+1.31** |
| -2.0 < z <= -1.0 | 488 | 17.0 | 14.1 | +1.4 | +1.7 | **+1.38** |
| -1.0 < z <  +1.0 | 3,486 | 14.8 | 12.0 | -0.7 | -0.4 | **-2.72** |
| +1.0 <= z < +2.0 | 503 | 15.7 | 13.0 | +0.1 | +0.6 | **+0.13** |
| +2.0 <= z < +2.5 | 66 | 16.5 | 13.9 | +0.9 | +1.5 | **+0.41** |
| z >= +2.5 | 54 | 22.5 | 16.0 | +6.9 | +3.6 | **+1.72** |

The median column is load-bearing: a mean lift driven entirely by a handful of crisis episodes is not a tradable regime signal, and mean-vs-median divergence is exactly how you tell the two apart.

### h = 21 sessions  ·  baseline realised vol 16.5%  (n=4,737)

| z bucket | n | mean vol % | median vol % | vs base | median vs base | **t vs rest** |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | 26.3 | 14.5 | +9.8 | +1.0 | **+1.72** |
| -2.5 < z <= -2.0 | 83 | 19.6 | 15.0 | +3.2 | +1.5 | **+1.24** |
| -2.0 < z <= -1.0 | 487 | 17.5 | 14.4 | +1.1 | +0.9 | **+0.63** |
| -1.0 < z <  +1.0 | 3,471 | 15.9 | 13.2 | -0.6 | -0.3 | **-1.27** |
| +1.0 <= z < +2.0 | 503 | 16.5 | 14.0 | +0.0 | +0.5 | **+0.03** |
| +2.0 <= z < +2.5 | 66 | 17.9 | 15.3 | +1.4 | +1.9 | **+0.71** |
| z >= +2.5 | 54 | 23.1 | 16.3 | +6.7 | +2.9 | **+1.63** |

The median column is load-bearing: a mean lift driven entirely by a handful of crisis episodes is not a tradable regime signal, and mean-vs-median divergence is exactly how you tell the two apart.

### h = 63 sessions  ·  baseline realised vol 17.1%  (n=4,695)

| z bucket | n | mean vol % | median vol % | vs base | median vs base | **t vs rest** |
|---|---:|---:|---:|---:|---:|---:|
| z <= -2.5 | 73 | 24.2 | 15.5 | +7.1 | +1.6 | **+2.57** |
| -2.5 < z <= -2.0 | 83 | 18.7 | 15.0 | +1.6 | +1.0 | **+0.94** |
| -2.0 < z <= -1.0 | 483 | 18.0 | 14.7 | +1.0 | +0.7 | **+0.46** |
| -1.0 < z <  +1.0 | 3,438 | 16.6 | 13.5 | -0.5 | -0.4 | **-0.83** |
| +1.0 <= z < +2.0 | 500 | 17.5 | 14.4 | +0.4 | +0.4 | **+0.21** |
| +2.0 <= z < +2.5 | 64 | 17.8 | 14.7 | +0.7 | +0.7 | **+0.50** |
| z >= +2.5 | 54 | 23.3 | 15.9 | +6.2 | +2.0 | **+2.39** |

The median column is load-bearing: a mean lift driven entirely by a handful of crisis episodes is not a tradable regime signal, and mean-vs-median divergence is exactly how you tell the two apart.

## Era split — 20d forward return, |z| >= 2.0

A signal that only works in one half of the sample is a regime artifact. Split at 2017-01-01 (roughly halves the session count).

| era | n armed | mean % | median % | win % | NW t | baseline % |
|---|---:|---:|---:|---:|---:|---:|
| 2007-08-23 → 2016-12-31 | 130 | +0.50 | +1.86 | 68.5 | +0.37 | +0.51 |
| 2017-01-01 → 2026-07-24 | 146 | +1.24 | +1.27 | 61.6 | +1.52 | +1.17 |

