# Dimension 04 — Term Structure (节奏 · "Rhythm")

> "Term Structure 是 vol crush 是否立刻发生的预测器。"

**Role in the matrix**: idiosyncratic-vs-systemic classifier. Reads the *temporal pricing of variance* across expiries to distinguish a single-event vol bump from a systemic regime change.

---

## 1. Definition

### Formal

Term structure is the curve of implied volatility (or implied variance) across maturities at fixed moneyness (typically ATM). Convention: define the **slope** as back-month minus front-month:

$$\text{TS}(t,\,T_{\text{front}},\,T_{\text{back}}) \;=\; \text{IV}_{\text{ATM}}(t,\,T_{\text{back}}) \;-\; \text{IV}_{\text{ATM}}(t,\,T_{\text{front}}),\quad T_{\text{front}} < T_{\text{back}}$$

A **positive** slope (back > front) is *contango* — the healthy default. A **negative** slope (back < front) is *backwardation*.

For volatility *futures* (VX), the same construction applies on synthetic constant-maturity vol indices (VIX, VIX3M, VIX6M, VXV).

### Intuition

In a *calm* regime, the market prices longer-dated variance higher than near-dated — the *variance risk premium* embeds a permanent upward slope (contango). Departures from contango indicate one of two regimes:

1. **Event-type backwardation** — A *single-month bump* (typically the front month spanning an event date) without the rest of the curve moving. Localized: the event collapses; the curve reverts to contango within hours of the event.
2. **Liquidity-type backwardation** — The *entire curve* inverts. Systemic stress signal. Persists for *weeks*. Examples: Volmageddon (Feb 2018), COVID March 2020, October 2008.

The framework's "rhythm" metaphor: the term-structure shape tells you the *tempo* of the next vol move — whether vol-crush will happen *immediately* (event collapse) or *only after multi-week resolution* (liquidity unwind).

---

## 2. The framework's four-state classification (slide IMG_4620)

| State | Signature | Reading |
|---|---|---|
| **Contango** | Back-month IV > front-month IV | Healthy calm. Default regime. |
| **Event-type backwardation** | Single-point near-month IV bump; back-month flat | Event-driven; usually collapses to contango post-event |
| **Liquidity-type backwardation** | Entire curve inverted | Systemic stress; **vol crush will NOT revert quickly**; persists weeks |
| **Mixed** | Event single-point + flat full curve | Idiosyncratic + systemic overlap — **most dangerous** |

**Role in the matrix**: a vol-crush-timing predictor. *When* does the bumped IV collapse? Event-type → fast; liquidity-type → slow.

This dimension is the primary **idiosyncratic-vs-systemic discriminator** in the framework's Step 2 (local vs global check).

---

## 3. Academic and practitioner literature

### Expectations-hypothesis tests

> **Mixon, S. (2007)** — *The Implied Volatility Term Structure of Stock Index Options* — Journal of Empirical Finance 14(3): 333–354.

Tests the expectations hypothesis (EH) for ATM IV across maturities. URL: https://www.sciencedirect.com/science/article/abs/pii/S0927539806000715

Key finding: the slope of ATM IV across maturities *does* predict future short-dated IV, but **less than the EH would predict**. Persistent deviations from EH indicate a *term premium* — equivalent to a forward variance risk premium.

Direct support for the framework's distinction between event-type (collapses back to contango — EH-consistent in the local sense) and liquidity-type (persistent deviation — term-premium driven).

### VIX term structure risk premium

> **Johnson, T. L. (2017)** — *Risk Premia and the VIX Term Structure* — Journal of Financial and Quantitative Analysis 52(6): 2461–2490.

Cleanest empirical paper on the VIX term structure. URL: https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/risk-premia-and-the-vix-term-structure/56572D1F060448571BD8F597C732D9C3

Key result: one principal component ("Slope") of the VIX term structure predicts excess returns of S&P 500 variance swaps, VIX futures, and SPX straddles **at all maturities** — a clear rejection of the expectations hypothesis. The slope reflects the price of variance risk.

Direct support for: contango/backwardation as a *signal*, not just an information aggregator. The framework's "term structure as vol-crush predictor" claim has explicit empirical backing here.

### Demand-driven backwardation

> **Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009)** — *Demand-Based Option Pricing* — Review of Financial Studies 22(10): 4259–4299. URL: https://academic.oup.com/rfs/article-abstract/22/10/4259/1590158

Quote: demand pressure from end-users explains both the level of index option richness *and* skew patterns. The mechanism behind *liquidity-driven backwardation*: when dealers are inventory-constrained, the whole curve inverts because front-month demand cannot be hedged across expiries.

Direct support for the framework's "liquidity-type backwardation persists weeks" — the duration follows the speed of dealer inventory rebalancing, not the calendar of any single event.

### Foundational forward-variance pricing

> **Britten-Jones, M. & Neuberger, A. (2000)** — *Option Prices, Implied Price Processes, and Stochastic Volatility* — Journal of Finance 55(2): 839–866. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00228

Derives the model-free risk-neutral expected integrated variance as a portfolio of European calls — the formula underpinning VIX (post-2003 methodology) and the basis for cross-expiry forward variance comparison.

> **Bakshi, G. & Madan, D. (2000)** — *Spanning and Derivative-Security Valuation* — Journal of Financial Economics 55(2): 205–238.

The spanning result that powers model-free risk-neutral moments — including the construction of constant-maturity vol indices used in term-structure analysis.

### Practitioner reference

> **Sinclair, E. (2013)** — *Volatility Trading*, 2nd ed., Wiley. ISBN 9781118347133.

Chapter on dynamics of realized vs implied volatility and trading the variance premium. Includes practitioner rules for trading contango vs backwardation around events (e.g. VX1/VX2 ratio thresholds for short-vol entry). https://www.wiley.com/en-us/Volatility+Trading

### 0DTE caveat — front-month IV decoupling

> **Dim, C., Eraker, B. & Vilkov, G. (2024)** — *0DTEs: Trading, Gamma Risk and Volatility Propagation* — SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190

0DTE has materially altered the front of the term structure. In a 0DTE-heavy regime, the very near front (0d–1d) can decouple from the rest of the curve due to intraday dealer-gamma dynamics — see [`07-limitations.md`](07-limitations.md) Limitation #7.

---

## 4. Single-dimension misreadings (from slide IMG_4617 #03)

> "Term Structure backwardation = 危机? 不一定。可能只是单股财报临近 (event-type) · 大盘远月还是 contango"

**Named misreading**: reading any backwardation as a systemic warning. Single-stock earnings creates event-type backwardation on *that name* without the index curve inverting. The framework's four-state classifier is precisely the antidote to this misreading.

**Additional failure mode**: **mixed regime** (event single-point + flat curve) is the most dangerous of the four. It looks like event-type at the front but the back of the curve is already showing stress — the event's impact will be amplified by systemic pressure.

---

## 5. Single-name caveats

1. **Single-name term structure is event-driven by construction**. Earnings on date `e`, OPEX on date `o`, ex-div on date `d` — each creates a discrete bump. Single-name term-structure shapes look like a series of event-type backwardations; the *index* analog (liquidity-type) is structurally rare.
2. **Liquidity gradient**. Single-name back-month options are far less liquid than index back-month. IV estimation for `T_2` ≥ 90 days on a single-name often has wide bid-ask spreads → noisy term-structure measurement → spurious "backwardation" readings.
3. **Vol of vol differs**. Per Foresi-Wu (2005) on cross-country skew steepening with maturity — see [`03-skew.md`](03-skew.md) — the rate of term-structure change is structurally different on single-names vs indexes. Universal thresholds for "backwardation detected" do not transfer.

---

## 6. Mapping to current `uw_scan` data

### What we have

| Layer | Status | Location |
|---|---|---|
| UW endpoint | ✅ | `/api/stock/{T}/volatility/term-structure` |
| Fetcher | ✅ | `fetch_term_structure` — `src/uw_scan/sources/uw.py:137` |
| Persistence | ✅ | (term structure rows persisted; check `repository.py` for table) |
| Report assembler | ✅ | `_build_term_structure` — `src/uw_scan/reports/volatility_series.py:268` |
| API | ✅ | Volatility tab v2 includes term structure |
| UI | ✅ | Volatility tab renders term structure curve |

### What's missing

| Layer | Gap | Effort |
|---|---|---|
| Four-state classifier | The framework's contango / event-back / liquidity-back / mixed classification is **not** computed. Currently we render the curve; the user must visually classify. | medium |
| Persistent classification | The classification should be persisted per ticker per market date (and labeled with the *reason* — single-point bump location, full-curve slope, etc.) for backtest replay | small (once classifier exists) |
| Slope PC ("Johnson Slope") | Per Johnson 2017, the first PC of VIX-style term-structure ranks vol-crush probability — useful as a single-scalar regime indicator | small |
| Event-type collapse predictor | Given event-type backwardation, model the expected post-event collapse time (typically <24 hours) — for short-vol entry timing | medium |

---

## 7. Concrete derivations the matrix needs

| Metric | Formula | Window | Purpose |
|---|---|---|---|
| `ts_state` | classifier → {contango, event_back, liquidity_back, mixed} based on curve shape | t | Primary state label feeding Step 2 of decision tree |
| `front_back_spread` | IV_atm(3m) − IV_atm(1m) (back minus front; positive = contango) | t | Continuous regime indicator |
| `single_point_bump_pct` | (IV_atm(closest_event_expiry) − interpolated_baseline_IV) / baseline_IV | t | Event-type bump magnitude |
| `full_curve_slope_pct` | slope of regression IV_atm ~ ln(T) across all available expiries | t | Liquidity-type signal (negative slope across all T) |
| `ts_johnson_slope_pc1` | first PC of (IV_atm(1m), IV_atm(2m), IV_atm(3m), IV_atm(6m)) over rolling 252d | rolling | Vol-crush probability proxy |
| `event_back_collapse_eta` | expected hours-to-contango-revert given event-type classification | t | Entry-timing aid for short-vol trades |

`ts_state` is the **primary output** — it directly feeds the decision tree's Step 2. The continuous metrics are inputs to the classifier and useful for backtest as features.

---

## 8. Cross-references

- Skew (jointly classifies event vs liquidity stress) — [`03-skew.md`](03-skew.md)
- VRP (term structure shape ↔ carry economics) — [`06-vrp.md`](06-vrp.md)
- Implied Move (event-type backwardation ↔ over-priced event IM) — [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md)
- Scenario A (idiosyncratic vs systemic — primary application) — [`00-overview.md`](00-overview.md)
- Limitation #2 (stress correlation breakdown — Volmageddon, Covid, 2008) — [`07-limitations.md`](07-limitations.md)
- Limitation #7 (0DTE-altered front of curve) — [`07-limitations.md`](07-limitations.md)
