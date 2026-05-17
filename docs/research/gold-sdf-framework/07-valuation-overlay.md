# 07 — Valuation Overlay (Layer 3)

The always-on tail-risk layer. Captures Erb-Harvey's "real price of gold mean reverts" finding — one of the most robust empirical results in the gold literature, and the most important academic finding the source article omits.

---

## The Erb-Harvey finding

From Erb & Harvey (2013), *The Golden Dilemma*:

> "The real price of gold was currently high compared to history, and in the past, when the real price of gold was above average, subsequent real gold returns have been below average — consistent with mean reversion."

Two specific empirical claims:

1. **At elevated real-price percentiles, subsequent real gold returns are below average.** Not zero — below average. The relationship is statistically reliable but noisy on any individual time horizon.
2. **The mean-reversion timescale is long.** It does not predict next-week or next-month returns. It manifests over multi-year windows.

These are the empirical findings; the article omits them entirely.

---

## Why this layer exists

The article presents gold as a regime-driven asset where price level is irrelevant — what matters is which regime we are in and which channels are firing. The Erb-Harvey finding contradicts this in a specific way: **at elevated real prices, the regime-driven framework has a headwind it does not acknowledge.**

In current conditions this matters concretely. The CPI-deflated gold price is at or near all-time highs (well above the prior 1980 inflation-adjusted peak). The structural-flow buyer (Layer 1) is the only force keeping mean reversion from biting. If structural buying decelerates further, valuation matters.

**Implementation implication:** the valuation overlay is **always on** and is **never a sizing input** — it's a tail-risk flag that contextualizes Lens 1 and Lens 2 outputs. The dashboard says "regardless of what Lens 1 and Lens 2 say, gold is in the {X}th percentile of real-price history; mean-reversion risk = {Low / Moderate / High / Severe}."

> **Authoritative:** This file (07) is authoritative on the never-sizing-input rule. An earlier draft of [04a-quant-model-spec.md](./04a-quant-model-spec.md) used Lens 3 as a position-size vol-scaler; that draft contradicted this file and was wrong per the Codex review. 04a has been corrected to align with 07: until a backtest demonstrates that valuation-conditional sizing improves out-of-sample Sharpe, Lens 3 is a *warning overlay*, not a *mechanical scaler*. The vol-scaler form is deferred to [10-open-research-questions.md](./10-open-research-questions.md) Q22 as an open research question.

---

## Construction

### Primary signal: real price of gold

- **Input:** USD gold price (LBMA AM Fix preferred for academic alignment; GLD as substitute)
- **Deflator:** CPIAUCSL (US CPI All Urban) indexed to a base year
- **Output:** real gold price time series, expressed in {base year} dollars

### Historical baseline

Real gold prices are available back to 1900 with reasonable confidence. The 1971-present series is unambiguous (post-Bretton-Woods float). Pre-1971 is constructed from the official US gold price ($20.67/oz pre-1934, $35/oz from 1934-1971) deflated by CPI; the pre-float series has a different character (fixed nominal, varying real) but is still useful for long-horizon percentile context.

### Percentile output

For each historical date, compute the real-price percentile within the rolling 100-year (or full-history) window. Surface:

- **Current percentile** — single number, color-coded
- **Time spent at current-percentile-or-higher** — answers "how rare is this level historically"
- **Recent percentile trajectory** — 90-day sparkline

### Tail-risk flag

| Real-price percentile | Mean-reversion risk flag |
|---|---|
| < 50th | Low |
| 50-75th | Moderate |
| 75-90th | High |
| > 90th | **Severe — historical regime, structural support required** |

These bounds match Erb-Harvey's empirical risk gradient. We are currently in the >90th percentile zone.

---

## Alternative anchors

Real-price-of-gold is the most defensible academic anchor. Two alternatives are worth surfacing as supplementary, not as replacements:

### Gold / M2 ratio

- **Input:** USD gold price ÷ US M2 money supply (FRED `M2SL`)
- **Rationale:** if gold is a hedge against monetary expansion, normalize by money supply rather than CPI
- **Trade-off:** more theoretically appropriate for the de-dollarization framing; but M2 has methodological revisions that make long-horizon comparisons less clean than CPI

### Gold / SPX ratio

- **Input:** gold price ÷ SPX level
- **Rationale:** a relative-value frame; gold cheap vs equities or expensive
- **Trade-off:** captures regime preference (real vs financial assets) rather than absolute mean reversion

Both are useful context. Neither replaces the primary real-price anchor.

---

## How the overlay interacts with Layers 1 and 2

The overlay does not contradict Layer 1 or Layer 2; it qualifies their outputs.

### Example dashboard line under each layer state

- **Layer 1 dominant + valuation at 92nd pct (current state):**
  "Structural bid intact. Central bank buying remains elevated. Valuation overlay flags severe tail-risk: if structural support fades, mean reversion could be substantial. Position B (tail hedge) remains warranted; sized appropriately for the asymmetric downside."
- **Layer 1 dominant + valuation at 40th pct (hypothetical):**
  "Structural bid intact. Valuation overlay flags low tail-risk. Both Layer 1 dynamics and valuation aligned for sustained gold appreciation."
- **Layer 2 operative + valuation at 85th pct (hypothetical past regime):**
  "Article's cyclical framework operative; A-position recommendation active. Valuation overlay flags high tail-risk — size A position with reduced confidence."

The overlay is the **honesty layer**. It ensures the dashboard never presents a gold-bullish posture without acknowledging the historical mean-reversion risk currently embedded in the real-price level.

---

## What this layer cannot do

The valuation overlay does **not** predict the timing of mean reversion. Erb-Harvey are explicit that the mean-reversion timescale is long and noisy. A 92nd-percentile reading is consistent with another year of gold strength followed by a multi-year correction; it is also consistent with a correction starting tomorrow. The flag is a risk gradient, not a timing signal.

This means the dashboard's positioning of Layer 3 should be:
- **Always visible** as risk context
- **Never the basis for an actionable signal** (no "valuation suspended" or "valuation operative" gating)
- **Sized appropriately in copy** — language of risk and tail, not language of prediction

---

## Implementation notes

### Data sources

- FRED `CPIAUCSL` (monthly, ~2-week lag) — primary deflator
- FRED `M2SL` (weekly) — alternative deflator for gold/M2 ratio
- massive.com gold OHLC (GLD as proxy; LBMA fix as enhancement)
- For pre-1971 historical context: hand-curated annual series from Officer & Williamson "The Price of Gold, 1257-Present" (free academic source) — only needed for the long-horizon percentile baseline

### Computation cost

Trivial. Daily real-price computation is one pandas line; historical percentile is a rolling expanding-window quantile. Pre-compute the historical series once; update daily incrementally.

### Caching

The historical baseline (pre-1971 annual + 1971-present daily real prices) should be cached as a single Parquet/CSV file regenerated weekly. The daily real-price percentile computation against this baseline is then near-instant.

---

## What this layer might miss

Two scenarios where the real-price-of-gold percentile is a misleading risk signal:

1. **Regime change in the long-run anchor itself.** If the marginal buyer truly has shifted from Western institutional (real-rate-sensitive) to EM central bank (de-dollarization-sensitive), the "fair" real price of gold may have shifted upward in a way that mean-reversion-to-historical-average fails to capture. Erb-Harvey wrote in 2013; their dataset ended pre-regime-change.
2. **Inflation regime change.** CPI is the deflator; if CPI itself becomes a poor measure of monetary debasement (e.g., asset inflation vs goods inflation diverging), real-price-of-gold becomes a worse anchor. The gold/M2 alternative is more robust here.

Neither of these scenarios invalidates the overlay; they argue for surfacing the alternative anchors alongside the primary, so the user can see whether all three (CPI-deflated, M2-deflated, SPX-relative) agree or disagree. When they agree, the signal is strong; when they diverge, the signal is contested and the user should weight Layer 1 more heavily.
