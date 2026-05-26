# Dimension 05 — Implied Move + Flow (资金流动 · "Market Expectation + Capital Intent")

> "Implied Move ≈ 0.8 × Straddle / Spot. 高 ≠ 高估。"

**Role in the matrix**: real-time market-expectation + capital-intent decoder. Reads (a) the *expected* magnitude of the next move and (b) the *footprint* of who is paying for it.

This dimension fuses two related but mechanically distinct readings: **Implied Move (IM)** as a forward-looking distribution proxy, and **Flow** as a real-time aggressor-tagged transaction log.

---

## 1. Implied Move

### Formal — what "Implied Move ≈ 0.8 × Straddle / Spot" actually means

For an ATM call under Black-Scholes (Brenner & Subrahmanyam 1988), the value can be approximated by:

$$C_{\text{ATM}} \;\approx\; S \cdot \sigma \cdot \sqrt{T/(2\pi)}$$

Therefore the ATM straddle (call + put, where the put is approximately equal in value) is:

$$\text{Straddle}_{\text{ATM}} \;\approx\; 2 \cdot S \cdot \sigma \cdot \sqrt{T/(2\pi)} \;=\; S \cdot \sigma \cdot \sqrt{T} \cdot \sqrt{2/\pi}$$

Dividing by spot:

$$\frac{\text{Straddle}_{\text{ATM}}}{S} \;\approx\; \sigma\sqrt{T} \cdot \sqrt{2/\pi} \;\approx\; 0.7979 \cdot \sigma\sqrt{T}$$

This is the same as the **expected absolute return** under a log-normal distribution: $\mathbb{E}[|R_T|] = \sigma\sqrt{T} \cdot \sqrt{2/\pi}$. So:

$$\boxed{\frac{\text{Straddle}_{\text{ATM}}}{S} \;\approx\; \mathbb{E}[|R_T|] \;\approx\; 0.7979 \cdot \sigma\sqrt{T}}$$

The framework's **"Implied Move ≈ 0.8 × Straddle / Spot"** therefore reads as:

> Implied Move ≈ 0.8 × (Straddle/S) ≈ 0.8 × E[|R_T|]

— a slightly deflated proxy for the **expected absolute return**, *not* the 1σ band. If you want the 1σ band proper, it is:

$$1\sigma \text{ move (as fraction of spot)} \;=\; \sigma\sqrt{T} \;\approx\; \frac{\text{Straddle}_{\text{ATM}}}{S} \cdot \sqrt{\pi/2} \;\approx\; 1.2533 \cdot \frac{\text{Straddle}_{\text{ATM}}}{S}$$

(About 25% larger than the raw straddle / spot.)

> **Brenner, M. & Subrahmanyam, M. G. (1988)** — *A Simple Formula to Compute the Implied Standard Deviation* — Financial Analysts Journal 44(5): 80–83. https://www.jstor.org/stable/4479153

Practitioner shorthand worth knowing:

| Quantity | Approximation |
|---|---|
| Raw straddle / spot | ≈ 0.7979 × σ√T = **E[\|R\|]** |
| 1σ move (fraction of spot) | ≈ 1.2533 × straddle/spot ≈ σ√T |
| 85% band (one-sided) | ≈ 0.85 × straddle/spot — practitioner heuristic, no clean derivation |
| Framework's "Implied Move" | ≈ 0.8 × straddle/spot — slightly deflated E[\|R\|], not 1σ |

**Operational implication**: when the framework compares "Implied Move" to a historical event distribution, it is comparing an *expected-absolute-return* proxy to the realized absolute-return distribution. Make sure the historical distribution is constructed as absolute returns, not signed.

### Intuition

Implied Move is the *risk-neutral expected absolute return* implied by ATM IV — a 1σ band one expiry forward. It is a **point estimate of a distribution**, not a forecast of magnitude. The framework's "高 ≠ 高估" caveat: a high IM does not imply IV is over-priced — the realized event distribution could be wider.

### Event distribution benchmarking

> **Patell, J. M. & Wolfson, M. A. (1979, 1981)** — Seminal evidence that Black-Scholes IV rises into earnings and collapses immediately after. https://doi.org/10.1016/0165-4101(79)90003-X · https://www.jstor.org/stable/2490873

The empirical basis for "event IV is a distribution of post-event move, not a point forecast."

> **Dubinsky, A., Johannes, M., Kaeck, A. & Seeger, N. J. (2019)** — *Option Pricing of Earnings Announcement Risks* — Review of Financial Studies 32(2): 646–687. https://doi.org/10.1093/rfs/hhy091

Decomposes ATM straddle price into a "jump" (earnings-day) plus diffusive component and benchmarks the *implied jump* against the empirical distribution of *realized* earnings moves. This is the direct support for the framework's "必须跟历史同类 event 分布对比 · 看中位数 + top-decile + 样本数" prescription.

**Operative rule for the matrix**: Implied Move > 30% above the median realized move of *historically comparable* events → "over-priced suspect." Cross-checked with: Term Structure (event-type backwardation), VRP (carry positive), Skew (smirk not accelerating). If all four align → Scenario A candidate.

---

## 2. Flow — the four footprints (slide IMG_4621)

Flow is read through *aggressor side classification* — buyer-initiated (at-ask) vs seller-initiated (at-bid) — bucketed into four named footprints:

| # | Footprint | Definition | Trade-intent reading |
|---|---|---|---|
| 1 | **Directional Whale** | Single large directional bet (call-side OR put-side, predominantly one-direction) | Short-horizon directional signal — informed flow proxy |
| 2 | **Hedge Flow** | Counter-direction hedging (put-buying while long stock; call-buying while short stock) | **Defensive**, NOT directionally bearish — "↑ hedge flow ≠ ↑ bearishness" |
| 3 | **Dealer Hedge** | Mechanical Δ-hedging by market makers — visible as repeated near-spot rebalancing | **Reveals dealer net-gamma regime**, not directional view |
| 4 | **Gamma Scalper** | Long gamma (RV > IV) vs short gamma (collecting θ) — same trade tag, opposite risk direction | Splits by RV-vs-IV regime; risk side determines whether scalper is paying or receiving |

The framework's caveat: "Flow 分类是推断 · 不是 ground truth · aggressor side 算法标记不 100% 可靠" — see §5 below.

---

## 3. Academic and practitioner literature

### Option flow as informed flow

> **Easley, D., O'Hara, M. & Srinivas, P. S. (1998)** — *Option Volume and Stock Prices: Evidence on Where Informed Traders Trade* — Journal of Finance 53(2): 431–465.

Foundational paper showing option flow is informative about future stock prices. "Positive" (buy calls / sell puts) and "negative" option volume Granger-cause stock returns. URL: https://doi.org/10.1111/0022-1082.194060

Cite for: Directional Whale as the *empirically validated* informed-flow proxy.

> **Pan, J. & Poteshman, A. M. (2006)** — *The Information in Option Volume for Future Stock Prices* — Review of Financial Studies 19(3): 871–908.

The canonical paper. Open-buy put/call ratios predict next-day returns by ~40bp and >1% over a week; the effect concentrates in *opening, non-firm-proprietary* volume — exactly the "Directional Whale" footprint. URL: https://academic.oup.com/rfs/article-abstract/19/3/871/1646711

### Volatility (vs directional) information

> **Ni, S. X., Pan, J. & Poteshman, A. M. (2008)** — *Volatility Information Trading in the Option Market* — Journal of Finance 63(3): 1059–1091.

Non-market-maker *vega-weighted* net demand predicts future *realized volatility* (not direction); price-impact of vol demand jumps ~40% pre-earnings. URL: https://doi.org/10.1111/j.1540-6261.2008.01352.x

Direct support for distinguishing **Directional Whale** (directional bet) from **Gamma Scalper** (vol bet) — they have different trade tags but very different predictive content.

### Put-call parity violations as directional signal

> **Cremers, M. & Weinbaum, D. (2010)** — *Deviations from Put-Call Parity and Stock Return Predictability* — Journal of Financial and Quantitative Analysis 45(2): 335–367.

Call-IV minus put-IV (same K, T) predicts ~50bp/week cross-sectional return spread; effect strongest when options are liquid and stocks illiquid. URL: https://doi.org/10.1017/S002210901000013X

Supports IV-skew-from-flow as a directional signal — links the **Directional Whale** footprint to skew dynamics.

### Net buying pressure → IVF shape

> **Bollen, N. P. B. & Whaley, R. E. (2004)** — *Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?* — Journal of Finance 59(2): 711–753. URL: https://doi.org/10.1111/j.1540-6261.2004.00647.x

Index-put buying pressure moves index IVF; single-name call pressure moves single-name IVF. Direct empirical evidence for the **Dealer Hedge** footprint mechanism: dealer hedging of customer net demand is observable in IVF shape.

### O/S ratio as informed-flow signal

> **Roll, R., Schwartz, E. & Subrahmanyam, A. (2010)** — *O/S: The Relative Trading Activity in Options and Stock* — Journal of Financial Economics 96(1): 1–17. https://doi.org/10.1016/j.jfineco.2009.11.003

O/S spikes pre-earnings, and post-announcement |return| scales with pre-announcement O/S. Supplementary support for the Directional Whale footprint, framed at the *ratio* level rather than absolute volume.

### Demand identification beyond aggressor

> **Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009)** — *Demand-Based Option Pricing* — Review of Financial Studies 22(10): 4259–4299. https://doi.org/10.1093/rfs/hhp005

Uses *proprietary* CBOE end-user vs market-maker tagging to bypass aggressor classification noise. Shows that the *meaningful* split is **customer-vs-dealer**, and that aggressor side is merely a noisy proxy. This is the academic basis for the framework's "aggressor side ≠ ground truth" caveat.

---

## 4. Aggressor classification — the noise floor

### Original quote-tick rule

> **Lee, C. M. C. & Ready, M. J. (1991)** — *Inferring Trade Direction from Intraday Data* — Journal of Finance 46(2): 733–746. https://doi.org/10.1111/j.1540-6261.1991.tb02683.x

Original quote+tick rule. Documents quote-reporting lag and the inside-spread problem — the foundation everyone cites and the source of known classification noise.

### Ground-truth error rates

> **Ellis, K., Michaely, R. & O'Hara, M. (2000)** — *The Accuracy of Trade Classification Rules: Evidence from Nasdaq* — JFQA 35(4): 529–551. https://doi.org/10.2307/2676254

Ground-truth check against Nasdaq order data: Lee-Ready ~81%, EMO rule ~82%. Trades *inside the spread* and *at-quote* are systematically misclassified. Quantifies the noise rate any aggressor metric inherits.

### Options-specific error rates

> **Savickas, R. & Wilson, A. J. (2003)** — *On Inferring the Direction of Option Trades* — JFQA 38(4): 881–902. https://doi.org/10.2307/4126723

**Directly relevant** to UW aggressor labels. Specifically tests four rules on options vs ground-truth CBOE data:

| Rule | Accuracy |
|---|---|
| **Quote rule** | **83%** |
| **Lee-Ready** | **80%** |
| **EMO (Ellis-Michaely-O'Hara)** | **77%** |
| **Tick rule** | **59%** |

Documents that options-specific frictions (wide spreads, infrequent quotes, multi-leg trades, outside-quote / reversed-quote trades) erode classifier accuracy — and that misclassification probability rises with trade size, moneyness, and maturity.

> "Outside-quote and reversed-quote trades are highly misclassified by all four rules. The probability of such trades is related to trading frequency, trade size, moneyness, and maturity."

This is the academic basis for the framework's Limitation #5 ("Flow 分类不是 ground truth · aggressor side 算法标记 · 流动性差 strike / 大型 block trade 错误率显著上升") — see [`07-limitations.md`](07-limitations.md).

---

## 5. Microstructure foundations

> **Kyle, A. S. (1985)** — *Continuous Auctions and Insider Trading* — Econometrica 53(6): 1315–1335. https://doi.org/10.2307/1913210

The reference informed/noise/MM model. Defines λ (price impact) and the "noise as camouflage" intuition.

> **Glosten, L. R. & Milgrom, P. R. (1985)** — *Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders* — Journal of Financial Economics 14(1): 71–100. https://doi.org/10.1016/0304-405X(85)90044-3

Sequential-trade model: bid-ask spread arises purely from adverse selection. Theoretical basis for treating aggressor side as a noisy informed-flow signal.

> **Hasbrouck, J. (2007)** — *Empirical Market Microstructure* — Oxford University Press. ISBN 978-0195301649.

Standard textbook. Ch. 5 (sequential trade), Ch. 6 ("Order Flow and the Probability of Informed Trading"), Ch. 7 (strategic trade / Kyle).

> **Foucault, T., Pagano, M. & Röell, A. (2013)** — *Market Liquidity: Theory, Evidence, and Policy* — Oxford University Press. ISBN 978-0199936243.

Modern synthesis. Anchor text for "Dealer Hedge" as a mechanical-flow regime distinct from informed flow.

---

## 6. Single-dimension misreadings (from slide IMG_4617 #04)

> "Implied Move 高 = 短期 vol 被高估? 不一定。也许真实波动比 implied 还大 · 必须跟历史同类 event 分布对比"

**Named misreading**: high IM means short-term IV is over-priced. Reality: realized move may exceed implied. The Dubinsky et al. (2019) machinery is the direct prescription — benchmark IM against the historical distribution of *comparable* events (same earnings type, same sector, same regime).

**Flow-specific misreadings**:
1. **Hedge Flow = bearish** — wrong; hedge flow is *defensive*, indicates an existing long position needs protection, not a new bearish view.
2. **Big call buy = bullish** — only if classified Directional Whale, not Dealer Hedge or Gamma Scalper (long-gamma scalpers buy calls + sell stock continuously).
3. **High volume = high information** — high O/S (per Roll-Schwartz-Subrahmanyam) carries information; high *absolute* volume in a quiet market may just be a single large block routing.

---

## 7. Single-name caveats

1. **Aggressor classification accuracy degrades materially on illiquid contracts**. Per Savickas-Wilson (2003), the best single-rule baseline on options is the quote rule at ~83% on liquid CBOE data; Lee-Ready (the more commonly used rule) is ~80%. Misclassification probability rises with trade size, OTM moneyness, and maturity — exactly the regions where flow signals are most needed. On thin single-names the four-footprint classification becomes unreliable.
2. **Earnings dominate**. Single-name pre-earnings flow is overwhelmingly Directional Whale (or hedge-driven Hedge Flow). The four-state framework still applies but is event-locked.
3. **No dealer-pricing pressure**. Single-names lack the index-wide dealer net-gamma regime that makes Dealer Hedge identifiable. On single-names, what looks like "Dealer Hedge" is often a single counterparty hedging a single OTC structure — see the limit case discussed in Gârleanu-Pedersen-Poteshman (2009).

---

## 8. Mapping to current `uw_scan` data

### What we have

| Layer | Status | Location |
|---|---|---|
| Flow alerts | ✅ | `fetch_flow_alerts` → DB → `FlowAlert` model |
| Aggressor labels | ✅ | UW provides `total_ask_side_prem`, `total_bid_side_prem`, `has_sweep` per row |
| Flow assembler | ✅ | `src/uw_scan/reports/single_stock.py:48-101` aggregates ask/bid premium |
| Dark pool | ✅ | Dark pool prints + notional in `FlowSnapshotGrid` |
| FlowTab UI | ✅ | `web/components/stock/tabs/FlowTab.tsx` — dedicated tab |
| Top alerts table | ✅ | `TopAlertsTable.tsx` shows ranked alerts |
| OI movers | ✅ | `OiMoversTable.tsx` with aggressor classification per project memory `project_aggressor_classification_semantics.md` |
| Implied Move | ⚠️ | ATM IV is in `interpolated_iv` / `volatility_stats`; **the 0.8 × straddle/spot deriver is not currently computed and persisted** |

### What's missing

| Layer | Gap | Effort |
|---|---|---|
| Implied Move deriver | Compute `implied_move_expected_abs = 0.7979 × ATM_straddle_mid / spot` per ticker per expiry; persist. (No extra √T multiplier — `straddle/spot` already encodes σ√T per §1.) | small |
| Historical-event benchmarking | For each `ticker × event_type` (earnings / FOMC / CPI), store the realized post-event 1d/3d/5d return distribution. Compute IM-vs-distribution percentile. | medium |
| Four-footprint flow classifier | Currently we surface raw flow alerts; the **Directional Whale / Hedge Flow / Dealer Hedge / Gamma Scalper** taxonomy is not labeled | medium |
| Single-name accuracy guard | Per Savickas-Wilson, label confidence should be `liquid` vs `illiquid` per ticker — currently unlabeled | small |

---

## 9. Concrete derivations the matrix needs

| Metric | Formula | Window | Purpose |
|---|---|---|---|
| `implied_move_expected_abs` | 0.7979 × ATM_straddle_mid / spot for nearest expiry | t per expiry | **E[\|R\|] proxy** per §1 (Brenner-Subrahmanyam). Despite older naming-convention sloppiness in the industry, this is NOT the 1σ band — the 1σ band is `1.2533 × straddle/spot ≈ σ√T`. Persist this column under the name that matches the math; alias the 1σ derived value if needed. |
| `implied_move_event_percentile` | percentile of `implied_move_expected_abs` within historical-event distribution for same ticker × event_type (distribution must also be constructed as **absolute** returns) | t | Detects over/under-priced events |
| `flow_footprint_label` | classifier → {directional_whale, hedge_flow, dealer_hedge, gamma_scalper} per alert | per alert | The "4 colors" reading |
| `directional_imbalance_3d` | (Σ ask-side call_prem − Σ bid-side call_prem) − (Σ ask-side put_prem − Σ bid-side put_prem) over last 3 days | 3d | "Flow color" — feeds Vanna conditional reading |
| `hedge_flow_intensity_5d` | put-buying premium / (long-position open-interest growth in same window) | 5d | Hedge-flow concentration |
| `aggressor_label_confidence` | per-ticker liquidity-based confidence score | static per ticker | Per Savickas-Wilson — quality guard |

The `directional_imbalance_3d` metric is the **explicit input** to Vanna's conditional readings — see [`01-vanna.md`](01-vanna.md) §7.

---

## 10. Cross-references

- Vanna (consumes `directional_imbalance_3d` from this dimension as "flow color") — [`01-vanna.md`](01-vanna.md)
- Charm (consumes OI clustering near spot — substrate of Flow) — [`02-charm.md`](02-charm.md)
- Limitation #5 (flow classification not ground truth — primary caveat for this dimension) — [`07-limitations.md`](07-limitations.md)
- Limitation #6 ("you are not the dealer" — most binding for Dealer Hedge footprint) — [`07-limitations.md`](07-limitations.md)
- Scenarios A and B (rely on `implied_move_event_percentile` and `flow_footprint_label` directly) — [`00-overview.md`](00-overview.md)
