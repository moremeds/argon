# Flow vs RV-IV — does UW-native flow survive residualization? (#227)
**Verdict:** NEGATIVE / underpowered-clean — no residualized flow signal (aggressor imbalance, net vanna, net charm) clears a multiple-testing-aware bar (beats matched-window RV-IV, net of 20bps, |t|>=3, sign-stable across both horizons). Scattered single-cell |t|~2-3 hits are sign-inconsistent across horizons/signals and of implausible magnitude (100-330 bps) — the signature of small-sample noise on ~11-21 non-contiguous days, NOT a distinct tradable axis over RV-IV. Flow does not survive residualization here.

**Bottom line (the kill shot):** the one cell the naive gate flagged (aggressor_3d residual, 1d) is ~128 bps vs the MATCHED-window RV-IV benchmark of ~122 bps on the same 21 days — a tie, not a win; and at 5d the same flow residual (~340 bps) is DWARFED by matched RV-IV (~826 bps). The apparent flow spread is not orthogonal alpha — it is the flow signal partially re-capturing a high cross-sectional-dispersion window that plain RV-IV captures at least as well or far better. Residualizing against RV-IV does not leave a distinct tradable increment. This is Goyal-Saretto's collapse-to-RV-IV extending to aggressor flow and dealer vanna/charm — in a coverage-limited but directionally clean window.
Falsification test: residualize aggressor premium-imbalance / net vanna / net charm against RV-IV cross-sectionally, then decile-sort forward stock returns on the RESIDUAL. If the residual adds nothing over the RV-IV-only benchmark, the entire positioning-signal axis is subsumed by RV-IV (Goyal-Saretto's one-factor result extends to flow).
**Data source:** `127.0.0.1/option_wizard_local`. **COVERAGE-LIMITED** — see below.
## Coverage
- flow_events: 114 tickers x 31 flow-days (aggressor arm)
- exposures_summary: 115 tickers x 22 days (vanna/charm arm)
- vrp_daily (RV-IV): 116 tickers x 323 days

n(days) after decile alignment is reported per row below (typically ~15-29). This is FAR below a powered cross-sectional study; treat t-stats as underpowered sanity flags, effect sizes as directional. h5 t-stats are overlapping-window inflated.
## RV-IV-only benchmark (decile L/S on the raw factor)
| horizon | n_days | mean L/S (bps) | t | hit% |
|--|--|--|--|--|
| 1d | 90 | 83.2 | 2.116 | 52 |
| 5d | 86 | 443.8 | 4.645 | 67 |

## Flow signals — RAW, RESIDUAL (vs RV-IV), and MATCHED-window RV-IV benchmark
`rviv_matched` = the RV-IV-only decile L/S restricted to the SAME days as the residual row directly above it — the fair like-for-like benchmark (the full-history benchmark table earlier is measured over a different, longer window and is NOT a fair comparator for the flow signals).

| signal | kind | horizon | n_days | gross L/S (bps) | t | net@20bps | net@50bps | hit% |
|--|--|--|--|--|--|--|--|--|
| aggressor_3d | raw | 1d | 21 | 103.4 | 1.65 | 83.4 | 53.4 | 67 |
| aggressor_3d | raw | 5d | 18 | 105.5 | 0.867 | 85.5 | 55.5 | 56 |
| aggressor_3d | residual | 1d | 21 | 127.7 | 2.052 | 107.7 | 77.7 | 67 |
| aggressor_3d | residual | 5d | 18 | 339.6 | 2.574 | 319.6 | 289.6 | 67 |
| aggressor_3d | rviv_matched | 1d | 21 | 122.1 | 1.192 | 102.1 | 72.1 | 67 |
| aggressor_3d | rviv_matched | 5d | 18 | 826.3 | 2.971 | 806.3 | 776.3 | 78 |
| aggressor_1d | raw | 1d | 21 | 39.5 | 0.668 | 19.5 | -10.5 | 62 |
| aggressor_1d | raw | 5d | 18 | 178.6 | 1.443 | 158.6 | 128.6 | 56 |
| aggressor_1d | residual | 1d | 21 | 61.0 | 1.025 | 41.0 | 11.0 | 52 |
| aggressor_1d | residual | 5d | 18 | 247.3 | 2.073 | 227.3 | 197.3 | 56 |
| aggressor_1d | rviv_matched | 1d | 21 | 122.1 | 1.192 | 102.1 | 72.1 | 67 |
| aggressor_1d | rviv_matched | 5d | 18 | 826.3 | 2.971 | 806.3 | 776.3 | 78 |
| net_vanna | raw | 1d | 14 | 20.3 | 0.524 | 0.3 | -29.7 | 57 |
| net_vanna | raw | 5d | 11 | -138.4 | -1.046 | -158.4 | -188.4 | 36 |
| net_vanna | residual | 1d | 14 | 39.3 | 0.975 | 19.3 | -10.7 | 50 |
| net_vanna | residual | 5d | 11 | -303.2 | -2.59 | -323.2 | -353.2 | 27 |
| net_vanna | rviv_matched | 1d | 14 | 84.0 | 0.571 | 64.0 | 34.0 | 64 |
| net_vanna | rviv_matched | 5d | 11 | 525.4 | 1.254 | 505.4 | 475.4 | 64 |
| net_charm | raw | 1d | 14 | -12.7 | -0.277 | -32.7 | -62.7 | 36 |
| net_charm | raw | 5d | 11 | 332.2 | 3.905 | 312.2 | 282.2 | 91 |
| net_charm | residual | 1d | 14 | -34.1 | -0.707 | -54.1 | -84.1 | 36 |
| net_charm | residual | 5d | 11 | 329.8 | 3.097 | 309.8 | 279.8 | 100 |
| net_charm | rviv_matched | 1d | 14 | 84.0 | 0.571 | 64.0 | 34.0 | 64 |
| net_charm | rviv_matched | 5d | 11 | 525.4 | 1.254 | 505.4 | 475.4 | 64 |

## Confound checks (pooled cross-sectional)
| signal | corr(signal, RV-IV) | corr(signal, trail-5d ret) |
|--|--|--|
| aggressor_3d | 0.044 | 0.085 |
| aggressor_1d | 0.033 | 0.083 |
| net_vanna | -0.003 | -0.013 |
| net_charm | 0.007 | 0.098 |

## Multiple-testing / power note
There are ~24 residual/raw L/S cells across 4 signals x 2 kinds x (raw+residual) x 2 horizons; at |t|>=2 roughly one spurious hit is expected by chance. The residual hits are NOT sign-stable (e.g. net_vanna 5d is significantly NEGATIVE while net_charm 5d is significantly POSITIVE, and aggressor is positive at both horizons but with implausible 100-340 bps magnitudes on 18-21 days). A genuine orthogonal edge would be sign-stable across horizons and of sane magnitude. The verdict bar therefore requires |t|>=3, beating the MATCHED-window benchmark, net-of-cost positivity, AND sign-stability across both horizons.

## Cost note
Predicted return is the STOCK close-to-close move, so the reported L/S is a stock-decile spread; the net columns subtract an equity round-trip cost per rebalance. The task mandates the Goyal-Saretto **30% quoted-spread** haircut, which is the OPTION-implementation cost — categorically larger than any equity cost. We lead with GROSS predictive content: a residual that is not even a clean, significant GROSS improvement over the RV-IV benchmark is dead under any cost model, option or equity.

## Reproduce
```
uv run python scripts/research/flow_vs_rviv_verdict.py --out-prefix docs/research/2026-07-07-flow-vs-rviv-verdict
```
