# Macro Short-Vol — Two-Layer $50k Capital-Utilisation Verdict (2026-06-23)

**Question.** Run the deployed Sharpe-1.65 macro short-vol winner as an always-eligible
**base** (ramp+ vrp-z-sized bull put spread) plus a **binary overlay** (extra set when
`vrp_z >= rich_threshold`) on ONE shared **$50,000** account across SPY/QQQ/IWM. What is
the annualised return, and how hard does the capital work?

**Method.** New dollar ledger `reports/vrp_capital_account.py` (reuses the validated
flat-vol pricing + `_settle` + `load_index_vol` + `WINNER` sizing). Integer contracts
floored to a risk-% of $50k; a rung opens only if its margin fits remaining buying power
(else skipped, logged). Idle cash earns rf 4% → P&L is excess, gross = excess + rf.
Window: `min_date` 2009-01-01, so entries run **2009-01-05 → 2026-05-14** (17.33 years).
SPY trades from the 2009-01-05 gate (VIX proxy + lake spot); VXN/RVX begin 2009-09 and a
252-day vrp-z warmup delays the first QQQ rung to 2010-10-22 (IWM similar). Per-name
filled rungs at the 0.05/×1/1.0 cell: SPY 427, IWM 397, QQQ 390. Reproduce:
`uv run python scripts/research/vrp_capital_sweep.py`. Full trace:
`capital-sweep-results.csv`. Reconciliation: SPX base-only uncapped ledger Sharpe
**1.834** vs `backtest_laddered` **1.834** (Δ **0.000**, 0 skips, util_peak 0.300) — the
dollar ledger is a faithful, scale-invariant wrapper of the validated ROR engine.

## Headline

**Read the geometric CAGR, not the arithmetic figure.** The two diverge enormously here
because the account does not compound (each rung risks a fixed % of the *original* $50k):
the best gross cell prints **60.5% arithmetic** annualised but only **15.3% geometric
CAGR**. The 60% is `mean_monthly × 12` on a constant base; the 15% is what actually
compounds. Quoting the 60% as "the return" would be a 4× overstatement.

- **Best base+overlay by raw return:** base_risk_pct **0.10**, overlay_mult **2.0**,
  rich_threshold **0.5** → gross annualised **0.605** (arith; excess 0.565; **geometric
  CAGR gross 0.153**), Sharpe **1.05**, maxDD **−1.012** of $50k (−$50,591), mean
  utilisation **0.713**, peak **1.000**, skip-rate **0.342**.
- **Best base+overlay by risk-adjusted return (Sharpe):** base_risk_pct **0.05**,
  overlay_mult **2.0**, rich_threshold **1.5** → Sharpe **1.18**, gross annualised
  **0.340** (CAGR gross **0.120**), maxDD **−0.692**, mean utilisation **0.369**,
  skip-rate **0.007**. The overlay here fires only in genuinely rich vol (z ≥ 1.5), so it
  rarely competes for capital.
- **Best base-only cell:** base_risk_pct **0.10** → gross annualised **0.474** (CAGR
  **0.139**), Sharpe **1.06**, mean utilisation **0.571**, skip-rate **0.083**.
- **Conservative base-only cell:** base_risk_pct **0.03** → gross annualised **0.152**
  (CAGR **0.082**), Sharpe **0.86**, maxDD **−0.400**, mean utilisation **0.169**,
  skip-rate **0.000** — the $50k is two-thirds idle (earning rf), no rung ever skipped.

- **Does the overlay earn its capital?** **No — it is leverage of the same bet, not
  additive edge.** Stacking the maximum overlay on the most aggressive base lifts gross
  return from 0.474 (best base-only) to 0.605 (+0.131 arith; +0.014 CAGR, 0.139→0.153),
  but Sharpe is flat-to-down (1.06 → 1.05) and maxDD deepens past the entire base
  (−0.844 → −1.012). The extra set buys raw return strictly in proportion to the extra
  risk it deploys. The only place the overlay nudges *risk-adjusted* return is gated
  tight (rich_threshold 1.5), where it lifts Sharpe 1.06 → 1.18 by doubling up rarely and
  only in true vol spikes. The dominant lever remains **base_risk_pct** (how much of the
  $50k each rung risks): 0.03 → 0.10 takes CAGR 0.082 → 0.139 on its own.

- **Capital utilisation reality:** the ramp+ base sits idle (rf only) when vol is cheap,
  so at a moderate base_risk_pct 0.05 mean utilisation is just **0.314** base-only — the
  $50k is ~two-thirds uninvested on average, the price of the vrp-z gate. Pushing
  base_risk_pct or adding the overlay raises mean utilisation toward **0.71** but
  saturates (peak 1.000, skip-rate 0.34) — the $50k becomes too small for the desired
  size a third of the time. There is no config that is simultaneously high-utilisation,
  high-Sharpe, and shallow-drawdown; the gate enforces a floor of idleness in exchange
  for the 1.6-Sharpe base edge.

**Bottom line.** On $50k, the honest deployable number is a **13–14% gross CAGR** from the
base alone at moderate sizing (base_risk_pct ~0.08–0.10, Sharpe ~1.06, ~57% mean
utilisation, −84% maxDD), or a steadier **~12% CAGR at Sharpe 1.18** if you keep sizing
moderate (0.05) and gate the overlay to rich_threshold 1.5. The maximum-leverage cell's
60% arithmetic print is a constant-base accounting artefact, not a compounding return, and
it carries a worse-than-total-capital drawdown. The overlay is a leverage knob, not an
edge; the real dial is base_risk_pct against your drawdown tolerance.

## Caveats

- **Two return views, never conflated.** Arithmetic `ann_return_*` (mean monthly × 12,
  constant non-compounding base) vastly exceeds geometric `cagr_*` (in the CSV) — 0.605
  vs 0.153 at the top cell. The constant-$50k base does not compound into sizing, so the
  arithmetic figure is a per-month-risk rate, not a wealth growth rate. The CAGR is the
  number to deploy against.
- Flat-vol BS ignores skew → the put-spread credit is a conservative floor (real put-skew
  credit ≥ modeled). No real-fill NBBO yet — modeled credits, not executed fills.
- maxDD is on the cumulative **dollar** P&L curve ÷ $50k. A reading past −100% (e.g.
  −101.2%) means a peak-to-trough loss exceeding the starting capital in dollar terms,
  drawn down from a much higher banked-equity peak — a genuine ruin-risk flag for the
  aggressive cells, not an arithmetic glitch.
- Same-date entries rotate priority by date ordinal (no alphabetical bias); when $50k
  binds, the skip lands unbiased-on-average across names, not pro-rata — per-name
  attribution is therefore noisy by design (see `skip_rate` / `fill_rate`).
- Capital frees at expiry (same-day reuse); T+1 settlement not modeled → slightly
  optimistic on the subset of entries landing on an expiry date.
- `skip_rate` = fully-skipped rungs (couldn't afford 1 contract) ÷ desired rungs;
  `fill_rate` = contracts filled ÷ desired (captures partial fills). At low
  `base_risk_pct` a name whose one-contract margin exceeds the per-rung budget would
  never trade — here all three names trade at every swept base_risk_pct (SPY 427 / IWM
  397 / QQQ 390 rungs at 0.05), so no name is silently absent.
- SPX is reference-only (one contract ≈ $16k margin, too lumpy for $50k); the tradeable
  S&P vehicle here is SPY (same VIX-driven signal). SPX is used only as the reconciliation
  anchor against `backtest_laddered`.
- **SPY lake data quirk:** SPY's equity-lake parquet carries ~73% null-`trade_date` rows
  (an alternate-schema partition); the loader now skips them, leaving the clean 8,379-bar
  daily series (1993–2026, validated: SPY $92.96 on 2009-01-02, $239.85 on 2020-03-16).
- Window: `min_date` 2009-01-01, so the study includes the 2011/2015/2018/2020/2022
  stress episodes but **excludes 2008** (the worst tail) — a real limit on the drawdown
  read. The QQQ/IWM sleeves only reach full breadth ~Oct 2010 after the VXN/RVX warmup.
