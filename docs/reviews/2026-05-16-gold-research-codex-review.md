# Gold Quant Signal Research Foundation - Codex Adversarial Review

Date: 2026-05-16
Scope: pre-spec methodology review of `docs/research/gold-sdf-framework/`
Reviewer stance: skeptical. This is not a source-validation pass; it is a design-break pass.

## 1. Methodology Survival Report

### Claim: post-2022 real-yield regime break

**Verdict: survives directionally, but the headline is too load-bearing as currently written.**

The `-84% -> -3%/-7%` collapse is probably pointing at something real. The surrounding facts are hard to wave away: gold rallied while GLD/ETF holdings fell, central-bank buying stayed historically elevated, and the marginal-buyer story changed after the 2022 reserve-freeze shock. That is enough to justify a regime-gated dashboard.

What breaks is the confidence level attached to the exact number. The research currently treats the RBC statistic like a measurement, not a clue. Before this becomes a product claim, we need to replicate it internally and pin down:

- Price level correlation vs return correlation.
- Gold spot, LBMA fix, GLD, or futures proxy.
- TIPS level vs TIPS change.
- Daily, weekly, monthly frequency.
- Window endpoint sensitivity.
- Whether the pre-2022 period is one long non-stationary macro regime rather than a stable law.

A level correlation from 2005-2021 can look spectacular because both series trend through QE, disinflation, and falling real yields. That does not automatically mean the relation was tradable. Conversely, a 2022-present near-zero correlation can be exaggerated by a short window with violent inflation and reserve-flow shocks. The break may be real and still be overstated by the statistic.

**What I would change:** downgrade the phrasing from "not sampling noise" to "large enough to require regime-gating unless our replication rejects it." Add a short replication requirement: rolling and expanding correlations, level and return specs, 60d/126d/252d/504d windows, and at least one formal break test. The dashboard can ship the gauge; the research note should stop implying the RBC number is already our measured truth.

### Claim: three-layer architecture is orthogonal

**Verdict: the architecture survives as a narrative decomposition, not as orthogonal factors.**

The layers are not orthogonal. They share plenty of variance:

- Central-bank buying is partly a geopolitical-risk and USD-reserve-confidence factor, which overlaps with GPR, DXY, TIPS, and inflation expectations.
- ETF holdings are Western institutional flow, which is exactly where real rates and DXY used to express themselves.
- Local-currency gold prices are FX stress plus USD gold, so they overlap with DXY, inflation, and regional risk.
- Valuation is endogenous to Layer 1. If central-bank flow lifts gold into the 90th real-price percentile, Layer 3 is partly a transformed consequence of Layer 1.
- Gold-GDX divergence sits between structural flow, equity risk, energy/mining costs, and risk appetite.

This is fine for a cockpit. It is dangerous for a quant model. If the product presents "three independent layers," it will overstate confidence by double-counting the same macro shock under different names.

**What I would change:** call them "three lenses" or "three signal families," not orthogonal layers. If this becomes a model, add variance accounting: correlation matrix, hierarchical clustering, VIF, PCA/partial residuals, and regime-conditional feature importance. Position sizing should assume correlated signals until proven otherwise.

### Claim: T5YIFR > 2.8% means "unanchored"

**Verdict: not defensible as a hard shipped threshold. Defensible only as a configurable heuristic.**

The docs already admit the problem: no academic source pins 2.8% as the unanchoring boundary. External spot-check agrees. The Fed's own common-inflation-expectations work treats anchoring as a multi-indicator latent construct using surveys and market measures, not a single TIPS-forward cutoff. T5YIFR is useful, but it includes inflation risk premia, liquidity premia, oil sensitivity, and market microstructure noise.

Shipping a dashboard label that says "unanchored" at 2.8% would be too strong. A user will read it as a Fed-quality regime classification when it is actually article-derived folklore.

**What I would change:** ship the default as `article_unanchored_threshold = 2.8%`, label the state "article unanchored zone," and calibrate the production regime classifier empirically. At minimum, derive thresholds from the historical T5YIFR distribution and compare to a multi-indicator anchoring basket: T5YIFR, T10YIE, SPF long-run expectations, Michigan long-run expectations, and the Fed CIE concept.

### Claim: F10 IC = 0.73 is implausible

**Verdict: yes, dismiss it under any standard tradable IC definition.**

The critique is right. A single macro spread with IC 0.73 would be a market anomaly of absurd size. Under standard Pearson/Spearman IC against future returns, especially walk-forward, this should not survive.

There are a few constructions where `0.73` becomes arithmetically possible, but none rescue it as a trading signal:

- Correlation of levels rather than returns.
- Same-period or lag-wrong correlation.
- Correlation against smoothed 40d forward returns with overlapping labels and no purge.
- A sign-coded regime score rather than raw return prediction.
- In-sample selection after testing many candidate factors.

**What I would change:** keep F10, but add a "replication trap" note: the first replication pass should deliberately compute the wrong-but-plausible versions above. If one of them reproduces 0.73, we can explain exactly why the original claim was inflated.

## 2. Quant-Model Spec Critique

### Keep

- **Linear baseline first.** This is correct. With ~2,000 daily observations and a major regime break, interpretability beats model theater.
- **Regime interactions.** The core economic claim is regime dependence, so factor x regime terms belong in v1.
- **Purged walk-forward validation.** This is not optional if forward-return labels overlap.
- **Point-in-time data requirement.** CPI releases, WGC lag, ETF close timing, COT release timing, and options snapshots all need explicit decision-time availability.
- **Online decay monitoring.** Good instinct. It should exist even for the research view as prediction audit rows, not just for a future ML model.

### Change

- **Do not make "multi-task" the thing that buys XGBoost legitimacy.** It does not quadruple N. IAU is nearly a duplicate of GLD. GDX is a miner equity basket with equity beta, energy/labor/cost-curve exposure, and management risk. Silver has industrial demand. Pooling these can help, but it introduces target heterogeneity. If used, frame it as partial pooling or transfer learning, not sample-size magic.

- **Move state-space/regime switching earlier than XGBoost.** The most important hypothesis is a regime switch in the pricing kernel. A Markov-switching regression, dynamic linear model, or Bayesian hierarchical model is more aligned with the research thesis than a boosted tree. I would test:
  1. Elastic net with regime interactions.
  2. Markov-switching or HMM-gated linear model.
  3. GAM or monotonic gradient boosting only if the first two leave clear nonlinear residual structure.

- **Treat XGBoost as a challenger, not the roadmap.** It can be useful, but the current spec still sounds eager to graduate into trees. A gold cockpit should prefer a boring model with honest uncertainty over a black box with SHAP ornaments.

- **Sharpe hurdles are under-specified.** `0.5` after costs is acceptable for a research signal, but thin for a tradable model. `+0.2` to advance to trees is plausible. `+0.1` for v3 is too low unless it is statistically significant after multiple-testing adjustment and does not worsen drawdown, turnover, or calibration. Use confidence intervals, deflated Sharpe, probability of backtest overfitting, and regime-conditional performance. A one-number Sharpe hurdle will be gamed by accident.

- **The embargo spec is internally inconsistent.** File 04a says a 5-trading-day embargo in the CV section, while the open decisions discuss 10 days. For 40d forward-return labels, the purge must remove all overlapping labels. The embargo should be additional and should scale with measured serial dependence and feature lookbacks. Ten days may be fine after a proper 40d purge; it is not a universal default.

- **Expanding window is not obviously right.** The spec says expanding windows retain all regimes. But if 2022 is a genuine pricing-kernel break, preserving old data may dilute current behavior. Compare expanding, rolling 5y/8y, and regime-weighted training. Do not choose expanding for narrative neatness.

### Missing

- **Release-calendar modeling.** Monthly/quarterly structural data must be lagged to publication date, not observation date.
- **Non-synchronous close handling.** FRED daily series, GLD close, futures settlement, ETF holdings, UW options snapshots, and global gold prices do not share a clock.
- **Feature-selection leakage.** The vivienna factor list and the "survivor" factors were selected after looking at the same market history. The backtest needs a clear distinction between pre-registered factors and discovered factors.
- **Overlapping multi-horizon labels.** A 10d/20d/40d ensemble creates highly correlated labels. Report each horizon separately before ensembling.
- **Target-definition risk.** GLD returns, spot gold, LBMA fix, and GC futures returns are not interchangeable once costs, tracking error, and close times matter.
- **Turnover and capacity.** A high Sharpe with constant churn is fake for this product unless costs and execution rules are explicit.
- **Kelly fragility.** Kelly-lite still amplifies estimation error. Cap position size first; treat Kelly as a diagnostic, not a default sizing engine until the model is proven.
- **Benchmark comparisons.** Require comparisons to buy-and-hold GLD, vol-targeted GLD, trend/momentum, real-yield-only, and no-trade. A model with Sharpe 0.6 that fails to beat a simple 12-month trend rule is not a quant win.

## 3. Missing Factor Classes

### Gold lease rate / GOFO

**Add, but not as clean v1 unless using modern proxies.**

GOFO itself is officially discontinued after January 2015, so a direct GOFO factor is not viable for current daily production. The underlying concept is important: physical tightness, forward/spot basis, and lease stress. For v1, use observable proxies already closer to the data stack: COMEX/LBMA inventory, futures basis/backwardation if massive supports GC futures curves, and SGE premium if/when scraped. Add a v2 research item for lease-rate proxies rather than pretending GOFO is an available current feed.

### GLD options skew / dealer positioning

**Add earlier than the docs currently imply.**

This repo's differentiated edge is UW options data. GVZ is already an options-implied-vol input, but it is only level volatility. Skew, put/call IV spread, dealer gamma, and large-trade flow can identify stress demand and hedging flows that macro data misses. I would not make it load-bearing for v1 alpha, but I would add a v1 "options stress" panel and persist the data from day one. It becomes a v2 model feature after enough history accumulates.

### Mining cost-curve dynamics

**Defensible omission for v1. Add to valuation/long-cycle v3, not trading v1.**

Cost curves matter for miners and long-run supply response, but gold supply reacts slowly. They are more relevant for GDX and producer margins than for next-20d GLD returns. If added, use as an explanatory overlay for Gold-GDX divergence and valuation, not as a daily alpha factor.

### Indian wedding-season seasonality

**Add as a small deterministic v1 calendar/context factor, not a core driver.**

India is a real physical-demand market, and the docs already mention XAU/INR. Wedding/festival seasonality is cheap to encode and useful context. But it should be bounded: seasonality can be overwhelmed by import duties, INR moves, local price levels, and substitution. Add as a calendar badge or low-weight seasonal prior.

### COT positioning on GC futures

**Add to v1 or early v2. This is the biggest omission in the provided list.**

CFTC COT data is free, weekly, long-history, exportable/API-accessible, and directly measures futures positioning. It is not perfect: categories are coarse, reporting is delayed, and crowded spec longs can be trend-following rather than contrarian. Still, a gold cockpit without managed-money/commercial positioning is missing a standard commodity signal. Add managed-money net position percentile, commercial net position percentile, and 4-week change.

### BIS gold swap activity

**Defensible omission for v1. Add as stress context only if data can be made reliable.**

BIS gold swaps are relevant to sovereign/liquidity plumbing, but they are opaque, lagged, and hard to map into daily signals. Mention them in structural-flow caveats. Do not put them in v1 scoring.

## 4. Q13 Vote

**My vote: Option A-prime, not Option A as written and not Option B.**

Option B is too much hidden work before user feedback. A 12-18 week one-shot quant build risks producing a beautiful backtest harness around the wrong product shape, wrong data cadence, or wrong cockpit semantics. For this repo, that is a bad bet.

But Option A as written is too loose. "No backtest harness, no walk-forward CV" is fine. "No quantitative audit scaffold" is not. If the research view ships without time-travel discipline, publication lags, persisted raw inputs, and at least deterministic replay tests, it can contaminate the later quant model.

I recommend:

1. **Phase A1, 5-7 weeks:** ship the research cockpit and data pipeline, but include a minimal replay/audit scaffold. Persist raw input snapshots, as-of timestamps, transformed factors, regime labels, and explanatory posture rows to Postgres. Build no ML model. Add deterministic historical playback for the regime gauge and structural posture, not a full tradable backtest.
2. **Phase A2, 2-3 weeks:** run a "model readiness" pass: PIT lag validation, correlation-break replication, threshold calibration, COT/options inclusion decision, and benchmark definitions.
3. **Phase A3, 6-10 weeks:** build the full quant model and walk-forward harness only after the cockpit tells us which signals are stable and worth modeling.

This preserves the interim deliverable while avoiding the trap of building a pretty research dashboard that cannot graduate into a quant system.

## 5. Anything Else Worth Flagging

- **Stop using recommendation language until validation exists.** The docs oscillate between "research view" and "position recommendation." For the first shipped artifact, use "posture," "risk," and "scenario," not "recommendation" or "position size."

- **The 2025 central-bank demand claim should be source-pinned.** WGC's FY2025 page supports the framing that demand remained resilient but below the prior three years' 1,000t pace. Put the exact tonne number and source in the bibliography before making it a threshold input.

- **Layer 3 should not be a volatility scaler in v1.** File 04a maps valuation to a position-size multiplier, but file 07 says valuation is never a sizing input. I agree with file 07. Until a backtest proves otherwise, valuation should be a warning overlay, not a mechanical scaler.

- **The B position is conceptually muddled.** Sometimes B is safe-haven/tail hedge, sometimes structural central-bank bid, sometimes permanent allocation. Those are different trades with different horizons. Split B into "strategic allocation context" and "event hedge context" before building UI copy.

- **The data-lag problem is bigger than the docs suggest.** WGC central-bank data, CPI, COT, LBMA vaults, and some ETF holdings are all delayed or after-close. The cockpit needs "as of" labels everywhere and the model needs release-time joins.

- **If one missing factor enters v1, make it COT. If two, make them COT and GLD options skew.** Those are more directly actionable than adding another macro transform.

## External Spot-Check Sources

- LBMA: GOFO discontinued after 2015: https://www.lbma.org.uk/articles/discontinuation-of-gofo-wef-30-january-2015
- CFTC: COT historical reports and API/export access: https://www.cftc.gov/es/node/128971
- Federal Reserve: common inflation expectations use many measures, including TIPS forwards and surveys: https://www.federalreserve.gov/econres/notes/feds-notes/index-of-common-inflation-expectations-20200902.html
- World Gold Council FY2025 central-bank discussion: https://www.gold.org/ja/goldhub/research/gold-demand-trends/gold-demand-trends-full-year-2025/central-banks
- CBOE/GVZ contract description via SEC filing: https://www.sec.gov/file/exhibit-3-16
