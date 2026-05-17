# 04a — Quant Model Specification

Operationalization of [04-three-layer-architecture.md](./04-three-layer-architecture.md) as a quantitative trading model. Where 04 describes the conceptual layers, 04a specifies the model class at each layer, the training procedure, the backtest harness, and the online evaluation requirements that elevate the framework from research dashboard to quant signal.

---

## Framing: this is a quant model, not a research view

The decision to treat this as a quant model has concrete consequences. A quant model produces:

- Daily numerical predictions (expected return, position size, confidence)
- Backtested out-of-sample performance with standard metrics (Sharpe, Sortino, max drawdown, hit rate)
- Online evaluation infrastructure that compares predictions to realized returns
- A decay-detection mechanism that triggers retraining or model retirement

A research view produces interpretive panels, narrative posture statements, and informative charts — useful but not actionable without judgment.

Both are legitimate goals. This document specifies the model that the layered architecture produces when we commit to the quant-model framing.

---

## Architecture-to-model mapping

| Lens | Quant role | Model class | Training procedure | Output |
|---|---|---|---|---|
| **Lens 1 — Structural flow** | Regime classifier / posture descriptor | v1: rule-based / v2: HMM or Markov-switching | Regime labels from data; HMM fit on rolling window | Regime label + probability vector + transition probability |
| **Lens 2 — Cyclical** | Alpha predictor | v1: regularized linear with regime interactions / v2: Markov-switching or hierarchical Bayesian / v3: tree-based challenger / v4: partial-pooling across precious metals | Purged walk-forward CV with horizon-scaled embargo | Daily expected return + uncertainty estimate |
| **Lens 3 — Valuation** | Tail-risk overlay | Deterministic transformation | None (analytical) | Tail-risk flag in {Low, Moderate, High, Severe}. **Not a sizing input.** |
| **Composition** | Posture statement (v1) → trading signal (v2+) | Weighted combination with variance accounting (v2+) | Composed daily | v1: narrative posture per lens. v2+: numerical signal if backtest earns it. |

This is a standard quant decomposition: regime → alpha → risk overlay → posture. The lenses map onto it cleanly *despite* sharing variance, because the lens questions ("who's buying?", "what would the cyclical framework say?", "is gold expensive?") are distinct even when the underlying inputs overlap.

> **Lens 3 correction:** A previous draft used Lens 3 as a position-size multiplier (vol-scaler form). Per the Codex review and consistent with [07-valuation-overlay.md](./07-valuation-overlay.md), Lens 3 is a **tail-risk overlay only** until a backtest demonstrates that valuation-conditional sizing improves out-of-sample Sharpe. v1 surfaces it as a warning flag, not a multiplier.

---

## Layer 1 — Regime classifier

### v1: Rule-based classifier

The article's three-regime taxonomy implemented as a deterministic classifier:

```
def classify_regime(cpi_yoy, t5yifr, dfii10_60d_change):
    if cpi_yoy < 2.0 and t5yifr < 2.5:
        return "real_rate_driven"
    elif 2.0 <= cpi_yoy < 4.0 and t5yifr < 2.8:
        return "moderate_inflation_trap"
    elif cpi_yoy >= 4.0 and t5yifr >= 2.8:
        return "high_inflation_unanchored"
    else:
        return "transitional"
```

Plus the regime gauge:

```
def regime_gauge(rolling_252d_corr_gold_dfii10):
    if -1.00 <= corr <= -0.50:
        return "operative"
    elif -0.50 < corr <= -0.20:
        return "partial"
    else:
        return "suspended"
```

Threshold values are configurable per [10-open-research-questions.md](./10-open-research-questions.md) Q9.

### v2: HMM upgrade

Hidden Markov Model with the same three-state structure (real-rate-driven / moderate-trap / unanchored / transitional as a 4th state). Trained on rolling 5-year windows of CPI YoY, T5YIFR, DFII10 60d change. Outputs:

- Most-likely current state (Viterbi)
- Posterior probability over each state
- Transition probability (P[state_t+1 = X | state_t = Y])

HMM is the right upgrade because it gives **smoothed regime probabilities** rather than the v1 classifier's hard switches. Useful when the underlying signals are noisy near threshold boundaries.

Decision criterion for v2 over v1: does the smoothed posterior produce more stable predictions in walk-forward backtest? If hard-switching at thresholds causes whipsaw, HMM resolves it. If thresholds are far enough apart that hard-switching is rare, v1 is sufficient.

---

## Layer 2 — Alpha predictor

### Feature set (17 cyclical + ~4 regime = 21 inputs)

The full input set combines viviennaBTC's 8 factors with the three daily-stationary derivatives of the structural-flow signals:

| # | Factor | Class | Source |
|---|---|---|---|
| F1 | DXY (DTWEXBGS) | Macro level | FRED |
| F4 | BEI (T10YIE) | Macro level | FRED |
| F5 | GPR (Caldara-Iacoviello) | Geopolitical | matteoiacoviello.com |
| F6 | GVZ | Vol level | FRED |
| F10 | TIPS-BEI Spread | Macro spread | computed |
| F11 | DXY 20d Momentum | Macro momentum | computed |
| F13 | Gold-GDX Divergence | Cross-asset | massive |
| F14 | GVZ 20d Momentum | Vol momentum | computed |
| F15 | GLD 30d net flow z-score | Structural derivative | SPDR + computed |
| F16 | COMEX registered 20d ROC | Inventory derivative | CME + computed |
| F17 | XAU/CNY premium over USD-gold | FX cross derivative | computed |
| **F18** | **COT managed-money net percentile** | **Positioning** | **CFTC** |
| **F19** | **COT commercials net percentile** | **Positioning** | **CFTC** |
| **F20** | **COT managed-money 4-week change** | **Positioning momentum** | **CFTC + computed** |
| **F21** | **GLD options 25Δ put-call IV spread (skew)** | **Options stress (v2 model input; v1 persist only)** | **UW** |
| R1-R4 | Regime indicators (rule-based labels v1; HMM posteriors v2) | Regime indicators | Lens 1 |

F18-F20 (CFTC COT positioning) were the largest single factor omission flagged by the Codex review and have been added. F21 (GLD options skew) leverages the repo's UW differentiated edge — for v1 it should be **persisted to Postgres from day one** even if not yet a model input, so that backtest history exists when we promote it in v2.

All 21 inputs are daily (COT is weekly, forward-filled with explicit release-date tracking), stationary after appropriate transformation (z-score, momentum, premium, percentile), and have data history sufficient for walk-forward CV.

### Model sequence

The model class is **earned, not chosen.** Each stage must beat its predecessor in out-of-sample walk-forward performance — measured by a basket of metrics, not a single Sharpe number — by a defined hurdle. We do not pre-commit to a model class. Per the Codex review, the order below was reshuffled: state-space / regime-switching models come **before** XGBoost, not after. The core thesis is a regime change in the pricing kernel; a regime-aware linear or Bayesian model is more aligned with that thesis than a boosted tree.

#### v1: Regularized linear baseline

- **Class:** Lasso or Elastic Net with regime × factor interactions
- **Specification:** `forward_return ~ α + Σ βi·Fi + Σ γij·Fi·Rj + ε`, where R is the regime indicator vector
- **Regularization:** Lasso α tuned via CV within each training fold
- **Why first:** smallest data hunger, most interpretable, native attribution via coefficients, no hyperparameter zoo
- **Hurdle to beat for v2:** the multi-metric basket below (Sharpe, deflated Sharpe, PBO, regime-conditional Sharpe, benchmark comparisons) must clear "marginally useful research signal" — see *Validation tests*

#### v2: State-space / regime-switching upgrade

- **Class:** Markov-switching regression, dynamic linear model (Kalman filter), or hierarchical Bayesian with regime priors
- **Why this slot before trees:** the research thesis is *regime change in the pricing kernel*. A regime-switching model is the theoretically aligned upgrade and gives us *smoothed* posterior regime probabilities for free, which the rule-based classifier does not.
- **Specification:** two- or three-state regression with factor loadings conditional on latent regime; expectation-maximization or HMC fit
- **Hurdle to beat v1:** statistically significant improvement (after multiple-testing correction) on the validation basket. See *Validation tests*.
- **Attribution:** smoothed regime posteriors per date, factor loading per regime, transition probabilities

#### v3 (challenger): Tree-based model

- **Class:** XGBoost or LightGBM
- **Status:** *challenger*, not default roadmap. The cockpit should prefer a boring model with honest uncertainty over a black box with SHAP ornaments. Only build this if v1 or v2 leave clear *nonlinear* residual structure that a regime-conditional linear model cannot capture.
- **Specification:** single model per horizon (test 10d, 20d, 40d separately before any ensembling — multi-horizon labels are highly correlated and should be reported individually first)
- **Regularization:** `max_depth ≤ 4`, `min_child_weight ≥ 5`, `subsample = 0.8`, `colsample_bytree = 0.8`, strong shrinkage (`learning_rate ≤ 0.05`), early stopping on validation basket
- **Monotonic constraints:** for factors with known sign (e.g., F1 DXY should have negative effect on gold), apply XGBoost monotonic constraints to prevent the model from fitting noise
- **Hurdle to beat v1/v2:** statistically significant improvement on the validation basket *plus* deflated Sharpe is not destroyed by complexity penalty
- **Attribution:** SHAP values per prediction

#### v4 (partial-pooling expansion)

- **Class:** Same v1 or v3 model class, but partially pooled across the precious-metals complex (gold, silver, GDX, IAU)
- **Why:** post-2022 dominant signals (CB buying, ETF flows) affect the whole precious-metals complex, so structure is shared. **This does NOT quadruple effective sample size.** IAU is nearly a duplicate of GLD. GDX is a miner equity basket carrying equity beta, energy/labor/cost-curve exposure, and management risk. Silver has industrial demand drivers. Pooling can help by *partial information sharing*, not by *literal N multiplication*. The right framing is hierarchical / partial-pooling / transfer-learning, not "buys XGBoost legitimacy at N~2000."
- **Specification:** hierarchical Bayesian with asset-level random effects, OR multi-task neural with shared embedding, OR fitted-on-pooled-then-shrunk-to-gold
- **Hurdle to beat v3:** statistically significant improvement on the *gold-specific* validation basket. Pooled gains on silver/miners are not credit; we are building a gold model.

#### v5 (optional): Bayesian uncertainty

- **Class:** Gaussian Process regression or Bayesian Additive Regression Trees (BART)
- **Why:** native uncertainty estimates, principled small-N behavior, smoother predictions near regime boundaries
- **Trade-off:** less industry-standard, harder to explain, slower training
- **Decision:** only build if v2 / v3 / v4 underperform on uncertainty calibration

### Cross-validation scheme

**Purged k-fold with horizon-scaled embargo**, the de facto standard for time-series financial ML per López de Prado (2018):

- **Splits:** 5-fold (10-fold to be evaluated empirically; see Q21 in [10-open-research-questions.md](./10-open-research-questions.md))
- **Purge:** remove from the training set any observation whose label overlaps the validation window. For a 40d forward return, purge a 40 trading-day band on each side of every validation fold.
- **Embargo (horizon-scaled):** additional gap *after* the purge to handle serial dependence of residuals and any feature-lookback overlap. **The embargo length must scale with the horizon being modeled** — a fixed 5 or 10-day default is wrong as a universal rule. Suggested starting point: embargo = max(10, 0.25 × horizon) trading days, then tuned against measured residual autocorrelation.
- **No data leakage:** all factor transformations (z-scoring, percentile, momentum) computed using only data available at point-in-time. Per [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) replication requirements, this includes CPI vintages via FRED ALFRED and explicit release-date joins for monthly/quarterly inputs.

**Rolling vs expanding window — open question, do not pre-commit:**

The original draft said "use expanding window because gold has gone through enough structural change that the model needs to retain memory of all regimes." Per the Codex review this is too neat: if 2022 is a genuine pricing-kernel break, preserving old data may *dilute* current behavior rather than help. The right approach is to **test multiple training-window schemes in walk-forward**:

- expanding window
- rolling 5-year
- rolling 8-year
- regime-weighted training (down-weight pre-2022 observations)

Pick the scheme that produces the most stable validation-basket performance, not the one that fits a narrative.

### Multi-horizon labels

A 10d/20d/40d ensemble produces highly correlated labels — they overlap by construction. **Report and validate each horizon separately before any ensembling.** Per the Codex review, ensembling correlated labels can mask which horizon is actually informative and inflates effective sample size in misleading ways.

If multi-horizon ensembling survives single-horizon validation:

```
weight_h = max(0, rolling_252d_IC[horizon_h])
predicted_return = Σ weight_h × prediction_h / Σ weight_h
```

…but only after each horizon has its own pass-or-fail decision on the validation basket.

---

## Lens 3 — Valuation overlay (NOT a sizing input)

Deterministic transformation, **no training and no sizing role**. Per [07-valuation-overlay.md](./07-valuation-overlay.md), the valuation overlay is a **tail-risk flag**, not a position-size multiplier. An earlier draft of this file proposed a `vol_scaler()` function that conflated valuation with vol-targeting and used real-price percentile as a position multiplier; that draft contradicted file 07 and was wrong. Per the Codex review, file 07 is authoritative.

What Lens 3 emits:

```
def valuation_flag(real_price_percentile):
    if percentile < 50:  return "Low"
    if percentile < 75:  return "Moderate"
    if percentile < 90:  return "High"
    return "Severe"  # historical extreme; structural support required
```

This flag appears in the dashboard as a side-panel risk badge and as narrative copy ("real gold price in the 92nd percentile of post-1900 history — mean-reversion risk: High"). It does not multiply any position size in v1.

**If/when a future backtest demonstrates** that valuation-conditional sizing improves out-of-sample Sharpe, **then** a vol_scaler-style transformation can be introduced — but only with empirical justification, not by default. This deferral is explicitly logged as [10-open-research-questions.md](./10-open-research-questions.md) Q22.

Vol-targeting (separately from valuation) is a legitimate risk-management technique that may still appear in v2 sizing logic when sizing is introduced — but it is *not* the same thing as Lens 3 and should not be confounded with valuation.

---

## Posture composition (v1) and sizing composition (v2+)

### v1: posture composition (no numerical positions)

The v1 dashboard composes the three lens outputs into **narrative posture statements**, not numerical position sizes. Per [04-three-layer-architecture.md](./04-three-layer-architecture.md):

- **Structural posture:** Lens 1 narrative — what the marginal-buyer evidence says today
- **Cyclical posture:** Lens 2 narrative — what the article's framework would say IF the correlation gauge is in the operative band; suspended copy otherwise
- **Valuation posture:** Lens 3 narrative — tail-risk flag with context

No position sizes. No A/B numerical recommendations. Posture / risk / scenario language only, per the Codex flag that shipping recommendation language without backtest validation overstates confidence.

### v2+: sizing composition (only after the v1 backtest harness validates a model)

Once Lens 2 has a model that clears the validation basket, **and** the lens shared-variance accounting is in place, sizing composition can be introduced. Default shape:

```
cyclical_size = gauge_factor × layer_2_predicted_return × kelly_haircut
strategic_size = strategic_allocation_context_constant   # see B-position split in 04
event_hedge_size = event_hedge_context_decay              # Baur-Lucey 15-day duration
```

Notes:
- `gauge_factor`: 1.0 / 0.5 / 0.0 from the correlation gauge, with thresholds calibrated empirically per file 03 replication requirement
- `kelly_haircut`: ⅓ Kelly default per López de Prado parameter-uncertainty argument
- The "B position" has been split per the Codex review into a *strategic-allocation context* (long-horizon) and an *event-hedge context* (Baur-Lucey 15-day decay). They are surfaced as separate panels, not combined into one B number.

Kelly fragility caveat: Kelly amplifies estimation error in μ and σ. Even Kelly/3 can be aggressive when the underlying μ̂ is noisy. v2 sizing should **cap position size with a hard maximum first**, then treat Kelly as a *diagnostic* rather than the sole sizing engine. Promotion to "Kelly-driven sizing" requires the v1 backtest harness to demonstrate stable, low-turnover, low-drawdown behavior across regimes.

---

## Backtest harness requirements

The backtest harness is the single most important engineering deliverable for the quant-model framing. Without it, we have a chart.

### Mandatory features

1. **Point-in-time data**
   - CPI vintages via FRED ALFRED API
   - T5YIFR uses point-in-time market data (already PIT in FRED)
   - All factor transformations computed only with data available at decision time
   - **Release-calendar modeling:** monthly and quarterly inputs (CPI, WGC CB reserves, LBMA vault, COT) must be lagged to actual publication date, not observation date. Each input has its own release-date column in the backtest store.

2. **Non-synchronous close handling**
   - FRED daily series, GLD close, futures settlement, ETF holdings disclosures, UW options snapshots, and global gold prices do not share a single clock. The backtest harness must record the **as-of timestamp** for every input and only feed observations whose as-of is strictly earlier than the decision time.

3. **Realistic transaction costs**
   - GLD bid-ask spread (typical ~1-2 cents on a ~$200 ETF = ~0.005-0.01%)
   - Slippage assumption: 50% of bid-ask for retail size, 25% for institutional
   - Commission: $0.00 for retail, $0.005/share institutional
   - Total round-trip cost assumption: 5-15 bps
   - **Turnover and capacity reporting:** average daily turnover, annualized turnover, max position-size as % of GLD ADV. A high-Sharpe signal with constant churn is fake for this product unless costs and execution rules are explicit.

4. **Target-definition discipline**
   - GLD returns, spot gold, LBMA AM fix returns, and GC=F front-month returns are not interchangeable once costs, tracking error, and close times matter. The backtest fixes a single target definition per run, documents which it is, and reports any rebenchmarking transparently.

5. **Feature-selection leakage controls**
   - viviennaBTC's 8-factor list and the "survivor" factors were selected after looking at the same market history we now want to backtest. The backtest must distinguish:
     - **Pre-registered factors** (F1-F17 as defined in this spec, fixed at backtest start)
     - **Discovered factors** (any added after seeing 2022-present performance)
   - Discovered factors get held-out validation only; they do not get to enter the in-sample window of any walk-forward run that crosses their discovery date.

6. **Multi-metric validation basket** (replaces single Sharpe hurdle)
   - Annualized return (geometric, after costs)
   - Annualized Sharpe
   - **Deflated Sharpe Ratio** (López de Prado / Bailey) — adjusts for multiple testing and finite-sample bias
   - **Probability of Backtest Overfitting (PBO)** — Bailey-López de Prado combinatorially symmetric CV
   - Sortino (downside vol only)
   - Maximum drawdown
   - Calmar (return / max drawdown)
   - Hit rate (% of trades positive)
   - Average win / average loss ratio
   - **Turnover-adjusted Sharpe** (net of realistic execution costs)
   - **Regime-conditional Sharpe** (separate for operative / partial / suspended gauge states; separate for pre-2022 / post-2022)
   - **Held-out year robustness:** drop one year at a time from training, performance should not depend on any single year
   - **Calibration:** for any model emitting probabilities or uncertainty estimates, reliability diagrams and Brier-score-style calibration metrics

7. **Benchmark comparison panel** (mandatory, not optional)
   - Buy-and-hold GLD
   - Vol-targeted GLD (10% annualized target)
   - 12-month trend / momentum rule
   - Real-yield-only signal (DFII10 change, no other inputs)
   - No-trade (cash) — establishes whether the model adds anything at all
   A model with Sharpe 0.6 that fails to beat a simple 12-month trend rule is not a quant win. The benchmark panel is the honesty check.

8. **Walk-forward simulation**
   - Refit every 60 trading days (~quarterly)
   - Out-of-sample period only — no in-sample equity curve
   - Robust to retrain failures (skip retraining if data quality issues)

### Validation tests

Before any model is considered shipped, the multi-metric basket above must clear:

- **Net-of-cost Sharpe** materially above buy-and-hold and 12-month trend benchmarks (target ≥ 0.5 after costs, but the *delta vs benchmarks* matters more than the absolute number)
- **Deflated Sharpe** statistically significant after multiple-testing correction
- **PBO** below 0.5 (preferably below 0.3)
- **Max drawdown** ≤ 30%
- **Sharpe in suspended-gauge subset** ≥ 0 (model doesn't lose money when the cyclical lens is off)
- **Hit rate** ≥ 50%
- **Turnover** within capacity envelope for GLD execution
- **Held-out year robustness** holds — no single-year dependence

A model that passes one metric and fails three is *not* shipped. The basket is the gate.

---

## Online evaluation infrastructure

Once the model ships, it generates predictions daily. The evaluation infrastructure compares predictions to realized returns over rolling windows:

| Metric | Window | Alarm threshold |
|---|---|---|
| Rolling 252d IC | 252 days | < 0.02 (degraded) |
| Rolling 60d hit rate | 60 days | < 45% (degraded) |
| Rolling 252d Sharpe | 252 days | < 0 (broken) |
| Regime classification accuracy | quarterly | regime gauge no-confidence on >30% of days |
| Prediction-realized residuals | continuous | systematic positive or negative bias > 1σ |

When alarms fire, the response is graduated:
1. **First alarm:** log and continue
2. **Second alarm within 90 days:** flag for manual review
3. **Third alarm or sustained breach:** automatically retrain on extended window
4. **Sustained post-retrain breach:** retire model, fall back to v1 baseline

This is the difference between a backtested chart and a quant model that survives in production.

---

## Decisions still open

These need resolution before implementation. See [10-open-research-questions.md](./10-open-research-questions.md) for tracking status.

1. **Single-horizon or multi-horizon?** viviennaBTC uses 10d/20d/40d ensemble. v1 baseline could pick one (say 20d) for simplicity. Decision: probably start single-horizon, add multi-horizon in v2.
2. **Kelly fraction:** ⅓ Kelly is standard. ½ Kelly is more aggressive but increases drawdown. Decision: configurable, default ⅓.
3. **Multi-task targets:** Gold-only, gold+silver, gold+silver+GDX, or all four. Decision: defer to v3, evaluate which combination produces best gold Sharpe.
4. **Embargo length:** López de Prado recommends embargo = serial correlation horizon. For daily gold ~5-10 days is typical. Decision: 10 days as default.
5. **CV fold count:** 5 standard, 10 more robust but slower. Decision: 5 for v1, evaluate.
6. **Regime probability as features:** Soft probabilities (HMM posteriors) or hard labels? Decision: hard for v1, soft for v2 if HMM is implemented.

---

## What v1 does NOT include

To control scope (especially under the Option A-prime path):

- **No trained ML model.** v1 is a research cockpit with audit scaffold, not a fitted predictor.
- **No numerical position sizing.** v1 emits posture / risk / scenario language, not buy/sell signals.
- **No XGBoost, no neural networks, no boosted trees.** State-space / regime-switching is the *first* model upgrade after v1 linear, not trees.
- **No multi-task / partial-pooling.** v1 is single-target gold posture; pooling is v4 at earliest.
- **No HMM regime classifier.** v1 uses the rule-based classifier; HMM is v2.
- **No automated retraining.** v1 does not have a model to retrain.
- **No multi-asset extension.** Gold only; silver/GDX/IAU enter only at v4 partial-pooling stage.
- **No options-based hedging or execution.** UW options data is *persisted from v1* but not consumed as model input until v2.
- **No real-money trading hooks.** Paper posture only in v1.
- **No valuation-based position sizing.** Lens 3 is a tail-risk overlay, not a multiplier.

These deferrals follow the Option A-prime path. The audit scaffold *is* in v1; the model is not.

---

## Scope and timeline

| Component | Engineering days |
|---|---|
| Data pipeline (Layer 1 + 2 + 3 inputs) | 8-12 |
| Layer 1 rule-based classifier + regime gauge | 3-5 |
| Layer 2 v1 baseline (Lasso linear) | 4-6 |
| Layer 2 walk-forward CV harness | 8-12 |
| Layer 3 valuation overlay | 2-3 |
| Position-sizing composition | 3-5 |
| Backtest harness (PIT data, costs, metrics, reporting) | 12-18 |
| Online evaluation infrastructure | 5-8 |
| API surface (read-only over computed results) | 3-5 |
| Dashboard UI | 8-12 |
| **Total v1** | **~56-86 days = 12-17 weeks** |

This is meaningfully more than the "research view" framing (~5-7 weeks). The difference is the backtest harness, online evaluation, and proper CV — all of which are mandatory for the quant-model framing.

---

## Relationship to viviennaBTC's approach

This spec is what viviennaBTC's post described, done with greater discipline:

| Aspect | viviennaBTC's approach | This spec |
|---|---|---|
| Factors | 8 (F1-F14 selected from 15) | 21 (F1-F17 + COT F18-F20 + UW options F21) |
| Model | XGBoost multi-scale ensemble | Linear → state-space → trees (challenger) → partial pooling — each stage must earn its place |
| Validation | Implicit; post doesn't show OOS Sharpe | Walk-forward purged k-fold with horizon-scaled embargo, multi-metric validation basket including deflated Sharpe and PBO |
| Attribution | SHAP | Coefficient inspection (linear), smoothed regime posteriors (state-space), SHAP (trees only if reached) |
| Position sizing | Kelly + ATR stops + drawdown circuit breaker | v1 has no numerical sizing (posture language only). v2+ Kelly-lite with hard caps, capacity-aware, treating Kelly as diagnostic |
| Regime awareness | Implicit ("HMM state" mentioned, no detail) | Explicit Lens 1 + correlation gauge gating Lens 2 + state-space upgrade path |
| Sample size handling | Single-target, ~2000 obs | Partial pooling across precious metals (v4) — *information sharing, not literal N multiplication* |
| F10 IC claim (0.73) | Asserted | Treated skeptically; replication-trap note in [08-viviennabtc-factor-critique.md](./08-viviennabtc-factor-critique.md); expected to land in 0.05-0.20 range under standard methodology |
| Backtest | None shown | Mandatory with documented multi-metric basket and benchmark comparisons |
| Online evaluation | None mentioned | Required infrastructure |
| Decay detection | None mentioned | Graduated alarm-and-retrain protocol |
| Benchmarks | None | Mandatory (buy-and-hold, vol-targeted, 12m trend, real-yield-only, no-trade) |

The post is a good *menu* of factors and a reasonable model-class direction. This spec turns it into a defensible research-first quant track.

---

## What this enables

When this is built and ships:

- Daily numerical signal: A position size, B position size, confidence
- Out-of-sample Sharpe and drawdown — known numbers, not asserted ones
- Regime-conditional attribution: in which conditions does the model work
- Decay detection: the model retires itself when it stops working
- Compositional explanation: every signal decomposes into Layer 1 (regime), Layer 2 (alpha), Layer 3 (risk)
- Reproducibility: the entire model is deterministic given inputs, factor transformations, and random seed

This is the difference between "a dashboard that shows gold context" and "a quant signal you could actually trade off." Both are valid products. This document specifies the latter.

---

## Open decision: Option A, B, or A-prime

Two original paths plus the Codex-recommended variant:

- **Option A — Research first, quant model second:** Ship the lens-based research dashboard (no walk-forward CV, no backtest harness, no online evaluation, no audit scaffold) in ~5-7 weeks. Then commit to the full quant model in ~6-10 weeks more. Total ~11-17 weeks with an interim deliverable. **Risk per Codex review:** if v1 ships without point-in-time discipline, persisted raw inputs, or replay tests, it can contaminate the later quant model — bugs in the cockpit data path become invisible defects in the eventual backtest.
- **Option B — Quant model directly:** Build the full backtest harness alongside the data pipeline. Single ~12-18 week deliverable. No interim. **Risk:** 3-4 months of hidden work before user feedback, with the chance of building a beautiful backtest harness around the wrong product shape, wrong data cadence, or wrong cockpit semantics.
- **Option A-prime (Codex-recommended) — Research cockpit with audit scaffold, then model:** Three phases.
  1. **Phase A1 (5-7 weeks):** Ship the research cockpit and data pipeline, *with a minimal replay/audit scaffold*. Persist raw input snapshots, as-of timestamps, transformed factors, regime labels, and lens posture rows to Postgres from day one. Build no ML model. Add deterministic historical playback for the correlation gauge and structural posture — a "time-machine" version of the cockpit that anyone can audit. No full tradable backtest yet.
  2. **Phase A2 (2-3 weeks):** Run a "model readiness" pass: PIT lag validation, internal correlation-break replication (per [03-post-2022-regime-break.md](./03-post-2022-regime-break.md)), correlation-gauge threshold calibration, COT/options inclusion decision, benchmark-comparison definitions, target-definition lock-in.
  3. **Phase A3 (6-10 weeks):** Build the full quant model and walk-forward harness only after Phase A1 + A2 tell us which signals are stable and worth modeling.

  Total: ~13-20 weeks across three phases.

**Recommendation (revised after Codex review):** Option A-prime. The audit scaffold in Phase A1 is the difference between "a research cockpit that traps us into a parallel quant build later" and "a research cockpit that promotes into a quant signal cleanly." Option A as originally written omitted this scaffold; Option B omitted the user-feedback loop.

Decision belongs to the user. Logged as [10-open-research-questions.md](./10-open-research-questions.md) Q13.
