# Dimension 03 — Skew (形状 · "Shape")

> "Skew 是形状。Baseline smirk 是常态 · 突然加速陡峭化才是信号。"

**Role in the matrix**: mid-horizon (2–8 weeks) risk-on/off thermometer. Reads the *tail-hedge demand* implied by the relative price of OTM puts vs OTM calls.

---

## 1. Definition

### Formal

Skew is most often parameterized as the **25Δ risk reversal**. **Sign-convention note**: practitioner conventions vary; UW (and most quote venues) store the value such that the SPX baseline is *negative*:

$$\text{RR}_{25\Delta}(T) \;=\; \text{IV}_{\text{call},\,25\Delta}(T) \;-\; \text{IV}_{\text{put},\,25\Delta}(T)$$

A *negative* risk reversal (the SPX baseline) indicates puts are richer than calls (`IV_put > IV_call ⇒ IV_call − IV_put < 0`) — the "smirk." This matches the UW `risk_reversal` field in `risk_reversal_skew_history` (TSLA, SPX et al. show baseline values around −0.05 to −0.10). The textbook treatment sometimes writes `IV_put − IV_call` with positive baseline; either convention is fine as long as the docs, the database column, and the §0.1 direction mapping all use the same one. **This doc set uses UW's convention (`call − put`, baseline negative) throughout.**

Alternative parameterizations include the 90/110 vol skew, the slope of IV vs log-moneyness near ATM, and the model-free risk-neutral skewness from Bakshi-Kapadia-Madan (see below).

### Intuition

Skew encodes the *risk-neutral asymmetry* of the implied return distribution. Buyers of OTM puts pay more than the symmetric Black-Scholes price would suggest, reflecting (i) demand for crash insurance, (ii) priced jump-risk, and (iii) priced asymmetry preferences.

The framework's "shape" metaphor distinguishes the **baseline shape** (a permanent smirk on indexes post-1987, not a directional signal) from **acceleration in the shape** (a real-time forward-looking risk-on/off signal).

---

## 2. The framework's reading (slide IMG_4619 — right column)

| Trigger | Reading |
|---|---|
| Long-term baseline | Smirk = default state; **NOT a signal** |
| Sudden accelerated steepening | Tail-hedge demand ↑ → forward-looking risk-off (leads 1–3 weeks) |
| Call-wing bid (right side firms) | Partial **reverse skew** — possible upside chase |
| Common misread | "Baseline smirk = bearish" — the index has been smirking for 35+ years; that's not a signal |

**Role in the matrix**: mid-horizon (2–8 weeks) risk-on/off early indicator. Most useful as a *delta detector* — what changed in the shape, not the shape itself.

---

## 3. Academic and practitioner literature

### Origin — "crashophobia" and the post-87 permanent smirk

> **Bates, D. S. (1991)** — *The Crash of '87: Was It Expected? The Evidence from Options Markets* — Journal of Finance 46(3): 1009–1044.

The foundational paper documenting that OTM puts on S&P 500 futures became unusually expensive *in the year before* October 1987. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1991.tb03775.x

Cite for: the empirical anchor that the persistent post-87 smirk is the *result* of priced jump/crash risk, not random.

> **Rubinstein, M. (1994)** — *Implied Binomial Trees* — Journal of Finance 49(3): 771–818 (AFA Presidential Address).

The Presidential Address that codified "post-1987 smile" as a stylized fact and introduced the implied-tree fitting methodology that recovers risk-neutral distributions without imposing log-normality. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1994.tb00079.x

Direct support for the framework's "smirk is permanent, not a signal."

### Skew structure — index vs single-name

> **Bakshi, G., Kapadia, N. & Madan, D. (2003)** — *Stock Return Characteristics, Skew Laws, and the Differential Pricing of Individual Equity Options* — Review of Financial Studies 16(1): 101–143.

The canonical model-free risk-neutral skewness paper. Quote: single-name risk-neutral distributions are "far less negatively skewed" than the index's; decomposes risk-neutral skewness into systematic + idiosyncratic components. URL: https://academic.oup.com/rfs/article-abstract/16/1/101/1615098

Direct support for the framework's Limitation #4 ("matrix primary context = SPX/SPY/QQQ"): index skew and single-name skew are *structurally different*. Single-name "lack of smirk" is not bullish — it's a different priced-risk structure.

### Skew as a forward-looking signal

> **Pan, J. (2002)** — *The Jump-Risk Premia Implicit in Options* — Journal of Financial Economics 63(1): 3–50.

Joint time-series estimation of SPX + near-the-money short-dated options identifies a large, state-dependent jump-risk premium that rises with market volatility. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304405X01000885

Cite for: skew steepening as a forward-looking jump/tail-risk indicator — the framework's "突然加速陡峭化 → tail hedge demand ↑" reading has direct empirical backing in this paper.

### Skew is global, structural

> **Foresi, S. & Wu, L. (2005)** — *Crash-O-Phobia: A Domestic Fear or a Worldwide Concern?* — Journal of Derivatives 13(2), Winter 2005.

Documents that skew/smirk is global across major equity indices and *steepens with maturity* (1m → 5y) — implying ever-more-negative risk-neutral skew at longer horizons. URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=598182

Cite for: skew is structural / permanent post-87, not US-specific. Reinforces "baseline smirk is not a signal."

### Demand pressure mechanism

> **Bollen, N. P. B. & Whaley, R. E. (2004)** — *Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?* — Journal of Finance 59(2): 711–753. URL: https://doi.org/10.1111/j.1540-6261.2004.00647.x

Quote: index-put buying pressure moves the index implied-volatility-function; single-name call pressure moves the single-name IVF. Direct empirical evidence that dealer hedging of customer net demand drives observable skew. This is the mechanism behind the framework's "accelerated steepening = tail-hedge demand" reading.

### Demand-based framework

> **Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009)** — *Demand-Based Option Pricing* — Review of Financial Studies 22(10): 4259–4299. URL: https://academic.oup.com/rfs/article-abstract/22/10/4259/1590158

End-user demand pressure on options explains both the level of index option richness and skew patterns. The theoretical sister to Bollen-Whaley (2004) — see [`01-vanna.md`](01-vanna.md) for the parallel application to vanna/gamma flow.

### Practitioner / textbook references

- **Sinclair, E. (2013)** — *Volatility Trading*, 2nd ed., Wiley. ISBN 9781118347133. Chapter on skew dynamics. https://www.wiley.com/en-us/Volatility+Trading
- **Bennett, C. (2014)** — *Trading Volatility, Correlation, Term Structure and Skew* — practitioner reference, widely circulated. (Available on the author's site; not a peer-reviewed source.)

---

## 4. Single-dimension misreadings (from slide IMG_4617 and IMG_4619)

| # | Misreading | Reality |
|---|---|---|
| A | "Baseline smirk = bearish" | The SPX has been smirking continuously since October 1987 (Bates 1991, Foresi-Wu 2005). It's structural, not a signal. |
| B | "OTM put expensive = short-vol candidate" (slide IMG_4617 #02) | Skew may steepen further; "the more expensive it gets, the more vulnerable to tail blow-up." This is the framework's most-warned-against misreading and was made tradeable by 2018 Volmageddon. |
| C | "Call wing bid = bullish breakout" | May only be partial-reverse-skew — incomplete signal. Cross-check with Implied Move (IM ratio above historical?) and Flow (call-heavy aggressor?). |

---

## 5. Single-name caveats

1. **Different baseline shape**. Per Bakshi-Kapadia-Madan (2003), single-names have much weaker (or even positive) risk-neutral skewness than the index. A "smirk" on a single name is not the baseline — it's worth investigating.
2. **Earnings overlay**. Pre-earnings, single-name skew is dominated by event-driven IV expansion, not tail-hedge demand. Acceleration in single-name skew before earnings is *not* the framework's mid-horizon risk-off signal — it's the binary-event mechanic.
3. **Liquidity floor**. 25Δ skew estimation on a single name requires sufficient OTM strike density. Below ~$5b market cap, 25Δ-based risk-reversal estimation becomes noisy; switch to 10Δ/40Δ or interpolated-IV-based slopes.

---

## 6. Mapping to current `uw_scan` data

### What we have — **fully integrated end-to-end**

| Layer | Status | Location |
|---|---|---|
| UW endpoint | ✅ | `/api/stock/{T}/historical-risk-reversal-skew` |
| Fetcher | ✅ | `fetch_skew` — `src/uw_scan/sources/uw.py:151` |
| Persistence | ✅ | `risk_reversal_skew_history` (time series) + `watchlist_cards.skew_25d_30dte` (rollup) — migrations/001:195, 003:49 |
| Repository read | ✅ | repository.py:1438 |
| API | ✅ | `SkewBlock.rr25d_30dte` (watchlist), `VolMetrics.skew_25d` (stock detail) |
| UI | ✅ | `web/components/watchlist/SkewBlock.tsx`, `web/components/stock/panels/VolMetricsCard.tsx`, full `.skew-chart` SVG on stock page |

**Skew is the reference implementation pattern** for "single rolled-up metric with DB → API → UI → SVG chart" — see [`08-implementation-gaps.md`](08-implementation-gaps.md). Other dimensions should mirror this.

### What's missing

| Layer | Gap | Effort |
|---|---|---|
| Acceleration detector | Slope of `skew_25d` over time (e.g. 5d, 10d, 20d derivatives) — currently we have the level, not the **rate of change** | small |
| Regime classifier | "Smirk vs accelerated-smirk vs crash-smile" — needs thresholds derived from rolling distribution of `skew_25d` | small |
| Term structure of skew | Skew at multiple expiries (1w / 1m / 3m / 6m) — currently we sample one expiry only (next-Friday default) | medium (multi-expiry fetcher already exists; just need to persist multiple per ticker per day) |
| Single-name skew threshold guard | Per Bakshi-Kapadia-Madan, single-name baselines differ; need per-ticker baseline rather than universal threshold | medium |
| Conditional-with-flow reading | Skew acceleration coincident with hedge-flow surge = "tail-hedge demand confirmed"; skew acceleration alone = ambiguous | medium |

---

## 7. Concrete derivations the matrix needs

| Metric | Formula | Window | Purpose |
|---|---|---|---|
| `skew_25d_5d_change` | skew_25d(t) − skew_25d(t−5d) | 5d | "Sudden acceleration" detector — primary trigger |
| `skew_25d_zscore_180d` | (skew_25d(t) − μ_180) / σ_180 | 180d rolling | Regime-relative position — distinguishes baseline smirk from extreme |
| `skew_term_structure` | skew_25d(1w) − skew_25d(3m) | t | Distinguishes near-term tail demand from chronic risk-off |
| `crash_smile_flag` | TRUE if put-wing IV rises faster than ATM IV by > 1.5× over 1-day | t | Scenario C confirmation — extreme regime |
| `skew_flow_concordance` | sign(skew_25d_5d_change) × sign(hedge_flow_5d_sum) | t | Confirms tail-hedge attribution to real demand vs surface artifact |

---

## 8. Cross-references

- Vanna (skew shifts trigger dealer vanna flow) — [`01-vanna.md`](01-vanna.md)
- Term Structure (skew + term jointly classify event vs liquidity backwardation) — [`04-term-structure.md`](04-term-structure.md)
- Limitation #1 (collinearity — skew, term, VRP all derive from IV; one IV move shows up in all four) — [`07-limitations.md`](07-limitations.md)
- Implementation gaps — [`08-implementation-gaps.md`](08-implementation-gaps.md)
