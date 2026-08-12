# Fundamental time-series test — within-ticker deterioration vs own drawdown

250 tickers, 16,857 scored observations. Unit of observation is the ticker; t-stat runs across tickers.

`_dm` = de-marketed (knowledge-quarter mean removed). **Lead with those** —
the raw t-stats share a macro driver across tickers and are inflated.

16 hypotheses were tested on one dataset. Bonferroni threshold is p < 0.0031 (|t| > ~3.0); the Benjamini-Hochberg column is the less conservative check.

| signal | outcome | mean IC | t | p | tickers | share > 0 | BH | Bonf |
|---|---|---:|---:|---:|---:|---:|---|---|
| level | ret_1q | -0.0239 | -2.61 | 0.0091 | 250 | 0.436 | pass | — |
| level | dd_1q | -0.0009 | -0.08 | 0.9378 | 250 | 0.46 | — | — |
| level | ret_1q_dm | +0.0032 | +0.35 | 0.7233 | 250 | 0.496 | — | — |
| level | dd_1q_dm | +0.0258 | +2.34 | 0.0191 | 250 | 0.6 | — | — |
| level | ret_2q | -0.0396 | -3.41 | 0.0006 | 250 | 0.392 | pass | pass |
| level | dd_2q | -0.0137 | -1.10 | 0.2731 | 250 | 0.432 | — | — |
| level | ret_2q_dm | -0.0047 | -0.41 | 0.6796 | 250 | 0.492 | — | — |
| level | dd_2q_dm | +0.0176 | +1.51 | 0.1298 | 250 | 0.56 | — | — |
| change | ret_1q | -0.0213 | -2.35 | 0.0188 | 249 | 0.442 | — | — |
| change | dd_1q | +0.0021 | +0.22 | 0.8235 | 249 | 0.506 | — | — |
| change | ret_1q_dm | +0.0048 | +0.52 | 0.6059 | 249 | 0.522 | — | — |
| change | dd_1q_dm | +0.0150 | +1.61 | 0.1065 | 249 | 0.522 | — | — |
| change | ret_2q | -0.0326 | -3.04 | 0.0023 | 249 | 0.41 | pass | pass |
| change | dd_2q | -0.0030 | -0.29 | 0.7695 | 249 | 0.474 | — | — |
| change | ret_2q_dm | -0.0000 | -0.00 | 0.9992 | 249 | 0.506 | — | — |
| change | dd_2q_dm | +0.0093 | +0.88 | 0.3789 | 249 | 0.518 | — | — |
