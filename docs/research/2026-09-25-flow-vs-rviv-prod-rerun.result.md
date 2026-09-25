> **Prod re-run, 2026-09-25, after the RV lookahead fix** (v0.13.11, `vrp_daily`
> rebuilt on trailing RV; see `docs/research/2026-09-24-uw-rv-forward-lookahead/`).
> Supersedes `2026-07-07-flow-vs-rviv-verdict`. Reproduce: run
> `scripts/research/flow_vs_rviv_verdict.py --out-prefix docs/research/2026-09-25-flow-vs-rviv-prod-rerun`
> with `UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard` (prod, read-only).
>
> **Read the tables, not the prose.** The `NEGATIVE` gate result is computed: no flow
> residual clears |t|≥3, stays sign-stable across horizons, and beats matched RV-IV. The
> Verdict and "Bottom line" paragraphs below are fixed text written for the July
> local run. Their numbers ("~11-21 days", "100-330 bps", "~128 vs ~122 bps", "~826 bps")
> are NOT from this run, and neither is "typically ~15-29" under Coverage.
>
> What this run actually shows (prod, 117 flow days / 198 exposure days / 344 RV-IV days):
> - **RV-IV alone no longer predicts returns.** The decile L/S is −6.5 bps at 1d
>   (t −0.56) and −44 bps at 5d (t −1.56). The July run had +83 bps (t 2.1) and
>   +444 bps (t 4.6), and that edge came from the forward RV. So the July "flow is
>   subsumed by RV-IV" argument no longer applies: there is no RV-IV edge to be
>   subsumed by.
> - **The flow signals do not predict returns either.** Vanna and charm are flat
>   (|t| < 1 across all cells, n=179-183 days). Aggressor imbalance is ~0 at 1d. At
>   5d it is negative (3d residual −124 bps, t −2.79, n=87), but that is below the
>   |t|≥3 bar, and 5d t-stats are inflated by overlapping windows.
> - Conclusion: still NEGATIVE, now for a different reason. Neither flow nor RV-IV
>   carries a tradable cross-sectional stock-return signal in this window. The
>   5d aggressor sign (contrarian?) is the only thing worth a look if flow history grows.

# Flow vs RV-IV — does UW-native flow survive residualization? (#227)
**Verdict:** NEGATIVE / underpowered-clean — no residualized flow signal (aggressor imbalance, net vanna, net charm) clears a multiple-testing-aware bar (beats matched-window RV-IV, net of 20bps, |t|>=3, sign-stable across both horizons). Scattered single-cell |t|~2-3 hits are sign-inconsistent across horizons/signals and of implausible magnitude (100-330 bps) — the signature of small-sample noise on ~11-21 non-contiguous days, NOT a distinct tradable axis over RV-IV. Flow does not survive residualization here.

**Bottom line (the kill shot):** the one cell the naive gate flagged (aggressor_3d residual, 1d) is ~128 bps vs the MATCHED-window RV-IV benchmark of ~122 bps on the same 21 days — a tie, not a win; and at 5d the same flow residual (~340 bps) is DWARFED by matched RV-IV (~826 bps). The apparent flow spread is not orthogonal alpha — it is the flow signal partially re-capturing a high cross-sectional-dispersion window that plain RV-IV captures at least as well or far better. Residualizing against RV-IV does not leave a distinct tradable increment. This is Goyal-Saretto's collapse-to-RV-IV extending to aggressor flow and dealer vanna/charm — in a coverage-limited but directionally clean window.
Falsification test: residualize aggressor premium-imbalance / net vanna / net charm against RV-IV cross-sectionally, then decile-sort forward stock returns on the RESIDUAL. If the residual adds nothing over the RV-IV-only benchmark, the entire positioning-signal axis is subsumed by RV-IV (Goyal-Saretto's one-factor result extends to flow).
**Data source:** `100.66.147.98/option_wizard`. **COVERAGE-LIMITED** — see below.
## Coverage
- flow_events: 186 tickers x 117 flow-days (aggressor arm)
- exposures_summary: 187 tickers x 198 days (vanna/charm arm)
- vrp_daily (RV-IV): 171 tickers x 344 days

n(days) after decile alignment is reported per row below (typically ~15-29). This is FAR below a powered cross-sectional study; treat t-stats as underpowered sanity flags, effect sizes as directional. h5 t-stats are overlapping-window inflated.
## RV-IV-only benchmark (decile L/S on the raw factor)
| horizon | n_days | mean L/S (bps) | t | hit% |
|--|--|--|--|--|
| 1d | 343 | -6.5 | -0.56 | 46 |
| 5d | 339 | -44.4 | -1.564 | 42 |

## Flow signals — RAW, RESIDUAL (vs RV-IV), and MATCHED-window RV-IV benchmark
`rviv_matched` = the RV-IV-only decile L/S restricted to the SAME days as the residual row directly above it — the fair like-for-like benchmark (the full-history benchmark table earlier is measured over a different, longer window and is NOT a fair comparator for the flow signals).

| signal | kind | horizon | n_days | gross L/S (bps) | t | net@20bps | net@50bps | hit% |
|--|--|--|--|--|--|--|--|--|
| aggressor_3d | raw | 1d | 91 | 1.6 | 0.069 | -18.4 | -48.4 | 44 |
| aggressor_3d | raw | 5d | 87 | -119.5 | -2.574 | -139.5 | -169.5 | 39 |
| aggressor_3d | residual | 1d | 91 | -13.1 | -0.537 | -33.1 | -63.1 | 45 |
| aggressor_3d | residual | 5d | 87 | -124.2 | -2.79 | -144.2 | -174.2 | 38 |
| aggressor_3d | rviv_matched | 1d | 91 | -27.4 | -1.15 | -47.4 | -77.4 | 42 |
| aggressor_3d | rviv_matched | 5d | 87 | -133.4 | -2.333 | -153.4 | -183.4 | 38 |
| aggressor_1d | raw | 1d | 91 | -11.5 | -0.525 | -31.5 | -61.5 | 43 |
| aggressor_1d | raw | 5d | 87 | -74.9 | -1.605 | -94.9 | -124.9 | 44 |
| aggressor_1d | residual | 1d | 91 | -10.4 | -0.447 | -30.4 | -60.4 | 45 |
| aggressor_1d | residual | 5d | 87 | -97.3 | -2.048 | -117.3 | -147.3 | 41 |
| aggressor_1d | rviv_matched | 1d | 91 | -27.4 | -1.15 | -47.4 | -77.4 | 42 |
| aggressor_1d | rviv_matched | 5d | 87 | -133.4 | -2.333 | -153.4 | -183.4 | 38 |
| net_vanna | raw | 1d | 183 | -2.0 | -0.196 | -22.0 | -52.0 | 50 |
| net_vanna | raw | 5d | 179 | 4.0 | 0.155 | -16.0 | -46.0 | 52 |
| net_vanna | residual | 1d | 183 | -2.9 | -0.277 | -22.9 | -52.9 | 52 |
| net_vanna | residual | 5d | 179 | -23.9 | -0.881 | -43.9 | -73.9 | 46 |
| net_vanna | rviv_matched | 1d | 183 | 11.4 | 0.67 | -8.6 | -38.6 | 48 |
| net_vanna | rviv_matched | 5d | 179 | 43.7 | 1.03 | 23.7 | -6.3 | 46 |
| net_charm | raw | 1d | 183 | 2.2 | 0.153 | -17.8 | -47.8 | 45 |
| net_charm | raw | 5d | 179 | 10.6 | 0.333 | -9.4 | -39.4 | 55 |
| net_charm | residual | 1d | 183 | 2.6 | 0.192 | -17.4 | -47.4 | 46 |
| net_charm | residual | 5d | 179 | 14.1 | 0.466 | -5.9 | -35.9 | 49 |
| net_charm | rviv_matched | 1d | 183 | 11.4 | 0.67 | -8.6 | -38.6 | 48 |
| net_charm | rviv_matched | 5d | 179 | 43.7 | 1.03 | 23.7 | -6.3 | 46 |

## Confound checks (pooled cross-sectional)
| signal | corr(signal, RV-IV) | corr(signal, trail-5d ret) |
|--|--|--|
| aggressor_3d | -0.043 | 0.044 |
| aggressor_1d | -0.045 | 0.04 |
| net_vanna | 0.017 | -0.005 |
| net_charm | -0.015 | 0.037 |

## Multiple-testing / power note
There are ~24 residual/raw L/S cells across 4 signals x 2 kinds x (raw+residual) x 2 horizons; at |t|>=2 roughly one spurious hit is expected by chance. The residual hits are NOT sign-stable (e.g. net_vanna 5d is significantly NEGATIVE while net_charm 5d is significantly POSITIVE, and aggressor is positive at both horizons but with implausible 100-340 bps magnitudes on 18-21 days). A genuine orthogonal edge would be sign-stable across horizons and of sane magnitude. The verdict bar therefore requires |t|>=3, beating the MATCHED-window benchmark, net-of-cost positivity, AND sign-stability across both horizons.

## Cost note
Predicted return is the STOCK close-to-close move, so the reported L/S is a stock-decile spread; the net columns subtract an equity round-trip cost per rebalance. The task mandates the Goyal-Saretto **30% quoted-spread** haircut, which is the OPTION-implementation cost — categorically larger than any equity cost. We lead with GROSS predictive content: a residual that is not even a clean, significant GROSS improvement over the RV-IV benchmark is dead under any cost model, option or equity.

## Reproduce
```
uv run python scripts/research/flow_vs_rviv_verdict.py --out-prefix docs/research/2026-07-07-flow-vs-rviv-verdict
```
