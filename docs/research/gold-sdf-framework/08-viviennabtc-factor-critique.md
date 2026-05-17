# 08 — viviennaBTC 8-Factor Critique

Honest assessment of the 8-factor model from the viviennaBTC X.com post. Three findings: (1) all 8 factors are reproducible in this repo with $0 additional data cost; (2) the F10 IC claim is suspect and should not be replicated as-stated; (3) the factor set has material structural omissions that the layered architecture fixes.

---

## Reproducibility

All 8 factors are achievable in this repo. Mapping:

| # | Factor | What it is | Source | Already wired? |
|---|---|---|---|---|
| **F1** | DXY (Dollar Index) | Broad trade-weighted USD | FRED `DTWEXBGS` (or `UUP` ETF via massive) | ❌ needs new FRED client |
| **F4** | BEI (Breakeven Inflation Expectations) | 10-year breakeven | FRED `T10YIE` | ❌ needs new FRED client |
| **F5** | GPR (Geopolitical Risk Index) | Caldara-Iacoviello daily index | matteoiacoviello.com CSV | ❌ needs CSV ingestor |
| **F6** | GVZ (Gold ETF Volatility Index) | CBOE 30-day GLD IV | FRED `GVZCLS` | ❌ needs new FRED client |
| **F10** | TIPS-BEI Spread | DFII10 − T10YIE | FRED, computed | ❌ needs new FRED client |
| **F11** | DXY 20d Momentum | (DXY_t − DXY_t-20) / DXY_t-20 | Derived from F1 | trivial |
| **F13** | Gold-GDX Divergence | GLD return − GDX return | massive.com | ✅ already wired |
| **F14** | GVZ 20d Momentum | Derived from F6 | trivial | trivial |

**Engineering cost:** one new FRED client + one CSV ingestor + computed transforms. Total ≤ 3 days. Data cost: $0.

See [09-data-sources-catalog.md](./09-data-sources-catalog.md) for full source detail.

---

## The F10 IC anomaly

The post reports **F10 (TIPS-BEI Spread) Information Coefficient = +0.73**, calling it the highest-IC factor in the 8-factor set. This number is suspicious and should not be taken at face value.

### Why 0.73 is suspect

For context, in published equity quant literature:
- **IC ~0.05** is publishable and worth trading
- **IC 0.10-0.15** is considered excellent for a single macro factor
- **IC > 0.20** is rare and usually indicates one of: leakage, in-sample bias, level co-movement, or unusual data construction
- **IC 0.40+** in any peer-reviewed source — vanishingly rare; typically followed by a replication failure

An IC of 0.73 implies the factor explains roughly 53% of cross-sectional return variation. No published macro factor in gold or commodity literature achieves anything close. The closest analog — Erb-Harvey's -0.82 gold-real-rate correlation — is a **levels** correlation, not an IC.

### Likely explanations

In rough order of probability:

1. **Level co-movement, not return prediction.** If F10 is computed on price levels and "IC" is actually correlation between TIPS-BEI spread level and gold price level, then 0.73 is plausible because levels are often cointegrated. But this is not what IC means in factor literature, and it does not generate trading signal.
2. **In-sample IC** computed on the same data used to construct the factor. Walk-forward IC is typically half or less of in-sample IC.
3. **Long-horizon forward returns** (40+ days ahead). At 40-day horizons, macro factors do have stronger relationships than at daily horizons — but 0.73 is still implausible at any horizon for a single macro factor.
4. **A different definition of IC than Spearman or Pearson rank correlation** — possibly including signed magnitude, weighted by realized volatility, or normalized in some non-standard way.

### What we do about it

- **Include F10 in the dashboard** for transparency and continuity with the post's framework.
- **Do not weight F10 disproportionately** in any composite signal.
- **Attempt our own IC computation** as part of the empirical-claims validation pass (see [10-open-research-questions.md](./10-open-research-questions.md) Q6). Compute Pearson IC, Spearman IC, both in-sample and walk-forward, against multiple forward-return horizons. Surface our number, not the post's number.
- **Expect IC in the 0.05-0.20 range** under standard methodology. If our number comes back materially different, we have learned something about her construction.

### Replication-trap note (Codex review)

The first IC-replication pass should **deliberately compute the wrong-but-plausible versions** of the IC calculation as well, not only the disciplined version. The goal is to find which arithmetic path reproduces the 0.73 figure so we can pin down exactly what the original claim is measuring.

Specifically, run all of:

1. **Levels correlation** (gold price level vs F10 level) — likely high; not a tradable signal
2. **Same-period (lag-0) return correlation** (no forward shift) — likely high; not predictive
3. **Smoothed 40-day forward return with overlapping labels and no purge** — partial leakage; IC will be inflated
4. **Sign-coded regime score** (F10 binned into regime categories, scored vs binned realized return) — not the same as IC, but sometimes labeled IC
5. **In-sample best-of-N across multiple factor candidates** — survivorship bias in factor selection inflates apparent IC

If any of (1)-(5) reproduces ≈0.73, we have explained the original claim. The disciplined number (walk-forward Spearman IC of F10 against forward 10d/20d/40d returns, with purged folds and embargo) is the one we ship; the "trap" numbers should be **logged in the validation report** for transparency.

This replication-trap approach was explicitly recommended by the Codex review and protects us from being criticized for dismissing the 0.73 number without showing what construction produces it.

---

## Structural omissions

The 8-factor set is **macro-only**. None of the 8 factors capture:

| Omitted signal class | Why it matters | Where we capture it instead |
|---|---|---|
| Central bank reserve flows | Post-2022 dominant driver | Layer 1 — see [05-structural-flow-factors.md](./05-structural-flow-factors.md) |
| ETF holdings | Daily proxy for Western institutional demand; cleanest regime-identification signal | Layer 1 |
| Exchange inventories | Physical demand and arbitrage detection | Layer 1 |
| Real-price-of-gold mean reversion | Tail-risk overlay (Erb-Harvey finding) | Layer 3 — see [07-valuation-overlay.md](./07-valuation-overlay.md) |
| Gold options dealer gamma / skew | Local microstructure (UW edge) | Future research, v2 |

These omissions are not minor. The first three are the very factors that survived the 2022 regime break. A factor model that does not include them was implicitly built for the pre-2022 regime.

---

## Factor-by-factor signal robustness assessment

For each of the 8 factors, our assessment of pre-2022 vs post-2022 signal value:

| # | Factor | Pre-2022 signal | Post-2022 signal | Verdict |
|---|---|---|---|---|
| F1 | DXY | Strong inverse | Weakened | Useful but degraded |
| F4 | BEI | Strong positive | Weakened | Useful but degraded |
| F5 | GPR | Modest positive | **Strengthened** | The geopolitical channel intensified post-2022 |
| F6 | GVZ | Modest positive | Modest positive | Stable; gold's own implied vol is concurrent indicator |
| F10 | TIPS-BEI Spread | Reported IC=0.73 (suspect) | Broken | Skeptical of pre-2022 reading; degraded post-2022 |
| F11 | DXY Momentum | Standard 20d ROC | Standard 20d ROC | Useful; derived from F1 |
| F13 | Gold-GDX Divergence | Useful, intuitive | **Robust** | Captures positioning shifts orthogonal to macro |
| F14 | GVZ Momentum | Useful | Useful | Vol regime transitions are timing signals |

**F5 (GPR) and F13 (Gold-GDX Divergence) are the two factors whose signal value plausibly survived or strengthened post-2022.** These deserve enhanced weighting in any composite signal.

---

## Recommendation for v1

### Include with standard treatment

- F1, F4, F6, F11, F14 — standard macro/momentum/vol factors. Useful, well-understood, computable. Display as z-scores or 52-week percentiles on the cyclical-factor grid (Layer 2 dashboard component).

### Include with elevated weighting

- F5 (GPR), F13 (Gold-GDX Divergence) — the two factors that work post-2022. If we compute any composite cyclical signal, these should carry more weight than F1/F4/F10. We do not formally optimize the weighting in v1 — instead, surface these two more prominently in the UI.

### Include with skepticism

- **F10 (TIPS-BEI Spread)** — include for transparency but explicitly mark with a tooltip noting our skepticism of the reported IC. Compute our own IC for the dashboard. Do not let F10's reported magnitude drive any sizing logic.

### Defer to v2

- **An ML model trained on the 8 factors** — explicitly rejected. Sample size is too small, regime break too recent, and the framework's value is interpretive, not predictive. See [10-open-research-questions.md](./10-open-research-questions.md) R5.

---

## What viviennaBTC's work adds that's worth keeping

The post is not academic-quality, but it does several useful things:

1. **F13 (Gold-GDX Divergence)** as an explicit factor — this is a clever cross-asset signal not in the academic literature. The "miners-as-leading-indicator" effect is well-known among traders; making it explicit in a factor framework is a useful contribution.
2. **F14 (GVZ Momentum)** as a vol-regime-change signal — also not academic, also useful.
3. **Multi-scale 10d/20d/40d horizons** — the recognition that macro factors operate at different timescales than equity factors is correct and worth preserving in the dashboard's horizon presentation (e.g., showing 20-day and 60-day signal direction side-by-side).

The 8-factor set is a reasonable starting menu of cyclical inputs. It is not, however, a complete model — and the post's framing as if XGBoost on these 8 produces actionable trading signal should be treated with the same skepticism as the F10 IC claim.

---

## What the post gets wrong

A consolidated list:

1. **F10 IC = 0.73** is implausibly high; do not replicate the weight.
2. **XGBoost on 8 factors with N < 2000 obs** is the classical overfitting setup. Her IC-pruning + Granger + VIF rituals exist because of this; a linear regime-conditional model would skip the need.
3. **"Multi-scale ensemble"** as presented has no out-of-sample validation in the post. The claimed Sharpe / hit rate are not shown.
4. **"SHAP attribution"** solves a problem a linear regime-conditional model wouldn't have. SHAP is necessary because XGBoost is a black box; with linear regression on regime-interacted factors, attribution is built-in.
5. **No structural-flow factors** — the post's framework has no signal for the dominant 2022-present gold driver.
6. **No valuation overlay** — no acknowledgment of Erb-Harvey mean-reversion risk.

None of these are reasons to dismiss the post; they are reasons to use it as one of several inputs in a layered framework, not as the model itself.
