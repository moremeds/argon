# Dimension 06 — VRP (Variance Risk Premium · carry 经济学)

> "VRP 是几十年平均 · 某一年可以转负 · short-vol 普遍承压。"

**Role in the matrix**: long-horizon (4–12 weeks) carry-state thermometer. Reads whether *selling vol* is paid for (positive VRP) or punished (negative VRP) on a horizon-averaged basis.

---

## 1. Definition

### Formal — strict VRP

### Sign convention warning

The literature uses **two opposite sign conventions** for VRP. Choose one and stick with it:

- **Convention A (Q − P, "seller's premium")**: VRP = E^Q[var] − E^P[var]. Equity VRP is **positive** (~15–20 monthly variance points on SPX). Used by BTZ (2009), Bekaert-Hoerova (2014), and most modern textbooks. Matches the framework's "温度计偏正/thermometer-positive" intuition: higher number = better carry for the seller.

- **Convention B (P − Q, "buyer's premium")**: VRP = E^P[var] − E^Q[var]. Equity VRP is **negative**. Used by Carr-Wu (2009). The phrase "*highly negative variance risk premium*" in Carr-Wu's abstract corresponds to a *positive* premium under Convention A.

**This document uses Convention A throughout.** When quoting Carr-Wu (2009)'s "negative risk premium" language, the sign is reversed relative to our formula.

### Definition under Convention A

The **strict** Variance Risk Premium is the risk-neutral expected variance minus the physical expected variance over the same horizon:

$$\text{VRP}_{t,\,T} \;=\; \mathbb{E}^{Q}_{t}\!\left[\int_{t}^{T} \sigma_s^2 \, ds\right] - \mathbb{E}^{P}_{t}\!\left[\int_{t}^{T} \sigma_s^2 \, ds\right]$$

In practice estimated as:

$$\widehat{\text{VRP}}_{t,\,30d} \;=\; \text{VIX}_t^2 \;-\; \text{RV}^2_{t \to t+30}$$

where $\text{VIX}_t^2$ is the model-free risk-neutral 30-day variance (via Britten-Jones–Neuberger 2000 / Bakshi-Madan 2000 spanning) and $\text{RV}^2_{t \to t+30}$ is the *subsequent* realized variance.

### Practitioner / proxy VRP

A common shortcut — and the one currently computed in `uw_scan` — uses **trailing** realized vol instead of *subsequent* realized vol:

$$\widehat{\text{VRP}}^{\text{proxy}}_{t} \;=\; \text{IV}_{t,\,30d} \;-\; \text{RV}^{\text{trailing}}_{t-30 \to t}$$

This is **NOT** the strict VRP — it is a *carry thermometer* that approximates the dealer's instantaneous P&L of a delta-hedged short-straddle position. Useful as a real-time signal, but mismeasures the priced premium.

The framework's slide IMG_4622 explicitly distinguishes the two definitions (Episode 9 framing — "严格 vs proxy 口径"):

> 实时监控 = VIX_t 对 trailing 30d RV · 严格 VRP = VIX_t 对 subsequent (t→t+30) RV

The matrix uses VRP for **long-horizon (4–12 weeks)** carry positioning — the strict definition is needed for that horizon, not the proxy.

### Intuition

VRP is the *long-run insurance premium* paid by buyers of options to sellers of options. The framework's central philosophical claim (Takeaway #01) is:

> "期权不是散户 vs 散户。是长期卖保险 vs 长期买保险。VRP 就是这份保险费的长期平均。"

Three independent academic sources explain why VRP exists and is persistent:

1. **Insurance demand / hedging premium** — investors are willing to overpay for left-tail protection.
2. **Fat-tail (jump) risk premium** — variance increases discontinuously during crises; sellers demand compensation for that conditional skewness.
3. **Risk aversion** — Epstein-Zin / long-run-risks preferences make variance shocks particularly painful and command compensation.

These three sources are *not* mutually exclusive — they are the modern consensus decomposition.

---

## 2. The framework's reading (slide IMG_4622)

| State | Signature | Reading |
|---|---|---|
| **IV > trailing RV** | "温度计偏正" — thermometer positive | sell-vol *appears* to have carry; default in stable regimes |
| **IV < trailing RV** | "温度计偏负" — thermometer negative | "保费已经兜不住真实赔付率 · 连做市商都在流血" → DO NOT sell vol |
| **Long-run SPX VRP** | ≈ 3–5 vol points (variance points; see §3 below for exact magnitudes) | The baseline expectation |

> "矩阵角色: 长期 carry 状态 · short-vol / long-vol 整体仓位的大方向。"

**Role in the matrix**: not a real-time trade signal — a **portfolio-direction** indicator. Sets the *bias* (short-vol favored vs long-vol favored), refined by other dimensions for entry timing.

---

## 3. Academic literature

### Strict definition and seminal estimates

> **Carr, P. & Wu, L. (2009)** — *Variance Risk Premiums* — Review of Financial Studies 22(3): 1311–1341. DOI: 10.1093/rfs/hhn038.

The reference for rigorous risk-neutral measurement of VRP via model-free synthetic variance swap rate. Carr-Wu uses **Convention B** (P − Q, equivalently realized minus synthetic) and reports a **large, negative** average VRP for the S&P 500 and four other indices — which under our **Convention A** (Q − P) corresponds to a large, *positive* sellers' premium.

> "evidence of a common stochastic variance risk factor in the stock market that demands a highly negative risk premium" (Abstract — under Carr-Wu's convention)

URL: https://academic.oup.com/rfs/article-abstract/22/3/1311/1581057

### VRP predicts stock returns

> **Bollerslev, T., Tauchen, G. & Zhou, H. (2009)** — *Expected Stock Returns and Variance Risk Premia* — Review of Financial Studies 22(11): 4463–4492.

VRP (`IV² − RV²`) **predicts post-1990 quarterly aggregate returns** and dominates P/E, default spread, and consumption-wealth ratio at the quarterly horizon. URL: https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787

Cite for: VRP-as-return-predictor. Predictability is strongest at **intermediate quarterly horizon** — direct support for the framework's "4–12 weeks" time window assignment.

### Three sources — fat tail

> **Bollerslev, T. & Todorov, V. (2011)** — *Tails, Fears, and Risk Premia* — Journal of Finance 66(6): 2165–2211. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2011.01695.x

Disaster/tail-jump compensation accounts for a "large fraction" of average equity and variance risk premia. Introduces an "Investor Fears" index from short-dated OTM options vs intraday jump tails.

> "Cite for: jump/tail premium as a primary source of VRP."

### Three sources — long-run risk / risk aversion

> **Drechsler, I. & Yaron (2011)** — *What's Vol Got to Do with It?* — Review of Financial Studies 24(1): 1–45.

Long-run risks model with jumps in volatility/long-run growth generates a *time-varying* VRP that reflects investor attitudes toward economic uncertainty. URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1081236

### Three sources — demand pressure

> **Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009)** — *Demand-Based Option Pricing* — Review of Financial Studies 22(10): 4259–4299. URL: https://academic.oup.com/rfs/article-abstract/22/10/4259/1590158

End-user demand pressure on index options explains both the level of option richness and skew patterns — the *insurance-demand* source of VRP, complementing the fat-tail and risk-aversion sources above.

### Operational decomposition

> **Bekaert, G. & Hoerova, M. (2014)** — *The VIX, the Variance Premium and Stock Market Volatility* — Journal of Econometrics 183(2): 181–192.

Decomposes VIX² into conditional variance + variance premium. **The premium predicts returns; the conditional variance predicts real activity and financial instability.** URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407614001110

Cite for: clean operational decomposition. **VRP ≠ VIX**. VRP is the *priced* part. Critical for the framework's "thermometer" framing — a high VIX does not mean VRP is high; the priced premium can be flat or negative even when VIX is elevated.

### Foundational forward-variance pricing

> **Bakshi, G. & Madan, D. (2000)** — *Spanning and Derivative-Security Valuation* — Journal of Financial Economics 55(2): 205–238. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304405X99000501

The spanning result that the characteristic function of the underlying spans derivative payoffs. The theoretical engine behind model-free risk-neutral variance/skewness/kurtosis used in VRP estimation.

> **Britten-Jones, M. & Neuberger, A. (2000)** — *Option Prices, Implied Price Processes, and Stochastic Volatility* — Journal of Finance 55(2): 839–866. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00228

Derives the model-free risk-neutral expected integrated variance as a portfolio of European calls — the formula underpinning the post-2003 VIX methodology and any rigorous VRP estimate.

### Practitioner reference

> **Sinclair, E. (2013)** — *Volatility Trading*, 2nd ed., Wiley. ISBN 9781118347133.

Practitioner reference. 2nd edition adds chapters on the dynamics of realized vs implied volatility and trading the variance premium. Useful for desk-level rules around VRP-based positioning. https://www.wiley.com/en-us/Volatility+Trading

---

## 4. The "3–5 vol point" SPX VRP claim

The framework cites *"SPX 长期 IV − RV ≈ 3-5pp"* on slide IMG_4615. **This is a practitioner shorthand and must be unpacked carefully**:

- The underlying Carr-Wu (2009) and Bollerslev-Tauchen-Zhou (2009) tables report VRP in *variance* units, not vol points. SPX monthly VRP is typically **15–20 variance points** (i.e. IV² − RV² ≈ 15–20).
- Translated to volatility points, this is roughly equivalent to **3–4 vol points** for typical regime VIX levels — consistent with the framework's "3–5pp" but the conversion is *not linear*.
- Numbers vary by sample period, frequency (daily/weekly/monthly), and RV estimator (close-to-close vs Yang-Zhang vs Garman-Klass).

**Operative rule for the matrix**: cite the *direction* of the claim (positive long-run SPX VRP) confidently. Cite the *magnitude* (3–5pp) as approximate and recompute from current data before quoting in a research output.

---

## 5. Single-dimension misreadings (from slide IMG_4617 #05)

> "VRP 厚 = 一定 sell-vol? 不一定。VRP 是几十年平均 · 某一年可以转负 · short-vol 普遍承压"

**Named misreading**: thick long-run VRP guarantees current sell-vol carry. Reality: VRP is a multi-decade mean; *individual years* can flip negative (Volmageddon Feb 2018, Q1 2020, etc.) and during those periods even well-hedged sell-vol books bleed.

**Two further failure modes**:
1. **Conflating VIX level with VRP** — Bekaert-Hoerova (2014) explicitly: VRP is the *priced* part of VIX², distinct from conditional variance. A high VIX during a vol regime change can coincide with a *low* or *negative* VRP.
2. **Strict vs proxy mismeasure** — Episode 9 framing — using trailing RV instead of subsequent RV biases VRP estimates positive in steady regimes and negative during regime breaks. Both biases are wrong.

---

## 6. Single-name caveats

1. **Single-name VRP is mostly noise**. Per Bakshi-Kapadia-Madan (2003 — see [`03-skew.md`](03-skew.md)), single-name risk-neutral distributions are far less negatively skewed than the index's. The variance risk premium on single-names is smaller, noisier, and dominated by idiosyncratic factors.
2. **Earnings overlay**. Pre-earnings single-name IV is dominated by event-driven expansion, not steady-state VRP. The "thermometer" reading does not transfer to single-name pre-earnings windows.
3. **VRP averaging requires depth**. Annualized estimates on individual stocks require ~5 years of data to be stable; for newly-listed names, the VRP reading is unreliable.

VRP is **fundamentally an index-level concept** for trading purposes; single-name extensions are research-grade but not directly tradable through the matrix.

---

## 7. Mapping to current `uw_scan` data

### What we have

| Layer | Status | Location |
|---|---|---|
| IV | ✅ | `interpolated_iv` endpoint → DB |
| Realized vol | ✅ | `realized_volatility` endpoint → DB; supplemented by `_fill_rv_from_price` in `reports/volatility_series.py` |
| Proxy VRP | ✅ | `build_vrp` at `src/uw_scan/reports/single_stock.py:181`; actual `vrp = vol.iv - vol.rv` at line 184 (IV − RV with ±0.05 cutoffs) |
| Proxy VRP time series | ✅ | `src/uw_scan/reports/volatility_series.py:116` |
| API | ✅ | Volatility tab v2 includes VRP |
| UI | ✅ | Volatility tab renders VRP block |

### What's missing — strict VRP

| Layer | Gap | Effort |
|---|---|---|
| Strict VRP estimator | `VIX_t` (or `IV_30d` proxy) compared against **subsequent** $RV_{t \to t+30}$ — requires holding `IV_t` snapshot and waiting 30 days before comparison | medium |
| Realized variance estimator choice | Currently close-to-close RV. Could optionally implement Yang-Zhang or Garman-Klass for lower estimation noise | small (optional) |
| Long-run regime classifier | Rolling 252d-, 504d-, 1260d-window mean and z-score of strict VRP | small |
| VRP-sign-flip detector | Flag when VRP crosses zero (regime change) | small |
| Decomposition (advanced) | Following Bekaert-Hoerova (2014), decompose VIX² into conditional variance + premium — needs a GARCH-style conditional variance estimator | medium |

### Required pipeline changes

To compute strict VRP we need a **30-day-lagged comparison** — not currently in pipeline. Two options:
1. Compute strict VRP for *historical* t values (t < today − 30d) on each rollup pass. Easiest.
2. Maintain a `vrp_30d_settlements` table: insert `IV_30d(t)` at `t`, then update with `RV_subsequent` at `t + 30d`. Cleaner; matches the strict definition.

Recommend option 2 for backtest fidelity. See [`09-backtest-plan.md`](09-backtest-plan.md) for backtest implications.

---

## 8. Concrete derivations the matrix needs

| Metric | Formula | Window | Purpose |
|---|---|---|---|
| `vrp_proxy_t` | IV_30d(t) − RV_30d_trailing(t) | t | Currently computed; real-time thermometer |
| `vrp_strict_t-30` | IV_30d(t−30) − RV_subsequent(t−30 → t) | t−30 (computed at t) | The "real" VRP per Carr-Wu / BTZ |
| `vrp_30d_long_run_mean_252d` | rolling 252d mean of `vrp_strict` | rolling | Regime baseline |
| `vrp_zscore_252d` | (vrp_strict − rolling_mean) / rolling_std | rolling | Relative-to-baseline thermometer |
| `vrp_sign_flip_30d` | TRUE if `vrp_strict` crossed zero in last 30 days | rolling | Regime-change alarm |
| `vrp_proxy_minus_strict` | `vrp_proxy_t` − `vrp_strict_t-30` | t | Diagnostic — measures the bias from using trailing-RV proxy |

The thermometer reading the framework references is `vrp_strict`-based; we currently surface only `vrp_proxy`. Backtest design (see [`09-backtest-plan.md`](09-backtest-plan.md)) requires `vrp_strict` for any conclusion about whether short-vol carries.

---

## 9. Cross-references

- Term Structure (curve shape ↔ VRP magnitude — both encode forward variance pricing) — [`04-term-structure.md`](04-term-structure.md)
- Skew (skew + VRP → jump-risk-premium decomposition) — [`03-skew.md`](03-skew.md)
- Limitation #1 (collinearity — VRP/skew/term/move all derive from IV — see misreading #02) — [`07-limitations.md`](07-limitations.md)
- Scenario A.2 (systemic + event — VRP near zero is a primary signature) — [`00-overview.md`](00-overview.md)
- Scenario C (VRP flips negative → sell-vol forced unwind, reflexive) — [`00-overview.md`](00-overview.md)
- Implementation gaps — [`08-implementation-gaps.md`](08-implementation-gaps.md)
