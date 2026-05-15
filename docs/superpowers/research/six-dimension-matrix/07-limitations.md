# 07 — Seven Limitations (七条限制)

> "矩阵不是水晶球 · 知道它在哪里失效。"

Each of the framework's seven named limitations is validated below against the academic literature. Reading order is preserved from slide IMG_4629.

---

## Limitation 01 — Dimensions are not independent (collinearity)

### Framework statement
> "维度不独立 · 多重共线性 (collinearity)
> Skew/VRP/Term/Move 多个仪表都来自 IV → 同一个 confirmation 重复显示 · 不是独立 confirmation"

### Why it's true

Skew, VRP, Term Structure, and Implied Move are **all derivatives of the implied-volatility surface**:

- Skew = IV(K_put) − IV(K_call) at fixed delta
- VRP = function(IV_30d, RV)
- Term = IV(T_short) − IV(T_long)
- Implied Move = function(IV_ATM, T)

When the IV surface shifts uniformly upward, **all four dimensions appear "vol-up" simultaneously** — but that is *one* confirmation, not four.

### Literature validation

The collinearity issue is not novel — it is the well-known consequence of the surface being driven by a small number of latent factors (typically 2–3 PCs). See:

- **Skiadopoulos, G., Hodges, S. & Clewlow, L. (1999)** — *The Dynamics of the S&P 500 Implied Volatility Surface* — Review of Derivatives Research 3: 263–282. (PCA on SPX IV surface — first 2 PCs explain ~95% of variation.)
- **Cont, R. & da Fonseca, J. (2002)** — *Dynamics of Implied Volatility Surfaces* — Quantitative Finance 2(1): 45–60. (More general framework; shows 2–3 PCs suffice.)

The Bekaert-Hoerova (2014) decomposition cited in [`06-vrp.md`](06-vrp.md) is the closest direct decomposition: VIX² splits into priced premium + conditional variance — the two are *not* independent measurements.

### Mitigation in the matrix

The framework's mitigation: **demand the 6 dimensions point the same direction**, but treat dimensions sharing IV-surface heritage as a *single* confirmation cluster.

| Confirmation cluster | Dimensions |
|---|---|
| IV-surface (collinear) | Skew · Term · VRP · Implied Move |
| Dealer-flow (collinear) | Vanna · Charm · Dealer Hedge footprint |
| Independent | Flow (directional whale, sweeps, dark pool) — when classified as Directional or Hedge footprint |

True 6-direction agreement requires *at least one* signal from each cluster — not 6 from the IV-surface cluster.

---

## Limitation 02 — Stress correlation breakdown

### Framework statement
> "压力时段历史相关性瞬间断裂
> Volmageddon / Covid / 2008 systemic shock 第一波 · 矩阵几乎失效 · 只有风控没有 alpha"

### Why it's true

The matrix's signal-generation relies on stable joint distributions of the six dimensions. During systemic shocks, those joint distributions undergo *regime breaks*:
- Volmageddon (Feb 5, 2018) — short-vol ETPs (XIV, SVXY) blew up; the very mechanism the matrix expects (dealer hedging stabilizes vol) was reversed by structured-product unwinds.
- COVID-19 (Feb–Mar 2020) — liquidity-type backwardation persisted weeks; vanna and charm flows were swamped by macro deleveraging.
- 2008 Q4 — VRP went sharply negative; "carry economics" was inverted for months.

### Literature validation

- **Augustin, P., Cheng, I.-H. & Van den Bergen, L. (2021)** — *Volmageddon and the Failure of Short Volatility Products* — Financial Analysts Journal 77(3): 35–55. Direct empirical study of the Feb 2018 event; documents the dealer-hedging-mechanism reversal.
- **Cheng, I.-H. (2019)** — *The VIX Premium* — Review of Financial Studies 32(1): 180–227. Shows VIX futures premia respond non-linearly to "fear" — embedding the regime-change risk that the matrix's correlation assumption fails to capture.
- **Acharya, V. V., Lochstoer, L. A. & Ramadorai, T. (2013)** — *Limits to Arbitrage and Hedging: Evidence from Commodity Markets* — Journal of Financial Economics 109(2): 441–465. Generalizes the broader phenomenon: arbitrage relationships break when dealers face constraints.
- **Adrian, T., Etula, E. & Muir, T. (2014)** — *Financial Intermediaries and the Cross-Section of Asset Returns* — Journal of Finance 69(6): 2557–2596. Documents how intermediary leverage cycles drive systematic shifts in priced risk — the macro analog of the matrix breakdown.

### Mitigation

> "矩阵几乎失效 · 只有风控没有 alpha"

The framework's mitigation is *operational, not analytical*: when the matrix breaks, **stop seeking alpha; switch to risk management**. The four-step decision tree's Step 4 (mandatory invalidation) functions during stress as the *only* tradeable rule. Scenario C's prescription ("不 sell-vol, 不抄底直到至少两维 stabilize") is the operational answer.

---

## Limitation 03 — Data lag

### Framework statement
> "数据延迟
> Flow 分类 / Skew / 严格 VRP 都需要时间窗 · 高频 / event-driven 信号可能已经过期"

### Why it's true

Each dimension has a *minimum window* before the signal stabilizes:
- Flow footprint classification: needs 3+ trades to disambiguate Directional Whale from Dealer Hedge
- Skew acceleration: 5-day lookback minimum to distinguish noise from trend
- Strict VRP: requires 30 days of subsequent RV — by definition, *cannot* be computed in real time

By the time the signal is statistically clean, the event has often already passed.

### Literature validation

- **Andersen, T. G., Bollerslev, T., Diebold, F. X. & Labys, P. (2003)** — *Modeling and Forecasting Realized Volatility* — Econometrica 71(2): 579–625. Establishes the minimum sampling windows for stable RV estimation.
- **Aït-Sahalia, Y. & Jacod, J. (2014)** — *High-Frequency Financial Econometrics* — Princeton University Press. Comprehensive treatment of estimation lag in continuous-time finance — the entire field is a treatise on this trade-off.
- **Savickas-Wilson (2003)** — cited in [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) — accuracy of trade-classification rules drops below 70% in low-volume windows; the algorithm needs a minimum number of trades to converge.

### Mitigation

The decision tree's Step 3 (time-window check) is the explicit guard. Dimensions assigned to short windows (Vanna, Charm: 1–5 days) cannot be the *primary* driver for trades whose holding period exceeds the signal's stability window; VRP-driven long-horizon trades cannot rely on a 1-day VRP reading.

---

## Limitation 04 — Single stock vs index

### Framework statement
> "单股 vs 指数
> 矩阵主要语境 = SPX / SPY / QQQ · 单股 idiosyncratic 路径可以偏离大盘矩阵"

### Why it's true

The matrix's mechanisms are all *index-pricing-pressure phenomena*:
- VRP is an index-priced premium (Bollerslev-Tauchen-Zhou 2009 on aggregate market)
- Vanna/charm flow assumes dealer-wide net positions (Gârleanu-Pedersen-Poteshman 2009)
- Skew baseline post-1987 (Bates 1991, Rubinstein 1994) is an *index* phenomenon
- Term structure backwardation regimes assume the broad market vol surface

Single-name options have:
- Lower OI density and dealer concentration
- Different baseline skew (Bakshi-Kapadia-Madan 2003: single-names are far less negatively skewed)
- Earnings discontinuities that dominate the path
- Aggressor-side classification accuracy dropping to ~70% in illiquid contracts (Savickas-Wilson 2003)

### Literature validation

The single-name vs index distinction is the most empirically documented limitation in the framework:

- **Bakshi, G., Kapadia, N. & Madan, D. (2003)** — *Stock Return Characteristics, Skew Laws, and the Differential Pricing of Individual Equity Options* — RFS 16(1): 101–143. The canonical paper on the distinction.
- **Driessen, J., Maenhout, P. J. & Vilkov, G. (2009)** — *The Price of Correlation Risk: Evidence from Equity Options* — Journal of Finance 64(3): 1377–1406. Shows that the *correlation* premium — the difference between index and basket variance — is itself priced; explains why index VRP > sum of single-name VRPs.
- **Buss, A. & Vilkov, G. (2012)** — *Measuring Equity Risk with Option-Implied Correlations* — Review of Financial Studies 25(10): 3113–3140. Companion paper.

### Mitigation

Scope the matrix to SPX / SPY / QQQ (and possibly liquid sector ETFs: XLF / XLE / XLK / SMH). For single-name analysis, flag deviations explicitly per-dimension as documented in each dimension doc's "Single-name caveats" section.

---

## Limitation 05 — Flow classification is not ground truth

### Framework statement
> "Flow 分类不是 ground truth
> aggressor side 算法标记 · 流动性差 strike / 大型 block trade 错误率显著上升"

### Why it's true

Aggressor-side classification (Lee-Ready 1991 + variants) is a *statistical inference* from quote+trade time series, not a direct observation of trader intent.

### Literature validation — error rates are quantified

- **Lee, C. M. C. & Ready, M. J. (1991)** — *Inferring Trade Direction from Intraday Data* — JF 46(2): 733–746. Original method; documents the inside-spread problem.
- **Ellis, K., Michaely, R. & O'Hara, M. (2000)** — *The Accuracy of Trade Classification Rules: Evidence from Nasdaq* — JFQA 35(4): 529–551. Ground-truth check: Lee-Ready ~81%, EMO ~82%; inside-spread and at-quote trades systematically misclassified.
- **Savickas, R. & Wilson, A. J. (2003)** — *On Inferring the Direction of Option Trades* — JFQA 38(4): 881–902. **The directly relevant paper for UW data**: on options vs CBOE ground truth — **quote rule 83%, Lee-Ready 80%, EMO 77%, tick 59%**. Misclassification probability rises with trade size, OTM moneyness, and maturity; outside-quote and reversed-quote trades are systematically misclassified by all four rules.

These numbers are the **noise floor** for any flow-based dimension. The framework's flow-footprint classifier inherits this error rate.

### Mitigation

- Per-ticker liquidity-confidence flag — see `aggressor_label_confidence` in [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md)
- Treat aggressor labels as **probabilistic, not categorical** — derive the four footprints with confidence intervals
- For high-stakes flow-conditional decisions, **require corroboration from a non-flow dimension** (Vanna conditional readings already require this — three conditions must align)

---

## Limitation 06 — You are not the dealer

### Framework statement
> "你不是 dealer
> dealer 知道 inventory + hedge demand · 你只能公开数据推断 · 强制平仓 / 央行干预时信号滞后"

### Why it's true

The matrix's mechanisms (vanna, charm, dealer hedge flow) all infer dealer positioning from *public* observables (OI, aggregated trades, volume). The dealer's *true* state — current inventory, prime-broker margin pressure, principal positions on the firm's book — is unobservable to outsiders. Inference accuracy degrades during stress events (forced unwinds, central bank interventions) precisely when dealers behave most non-mechanically.

### Literature validation

- **Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009)** — *Demand-Based Option Pricing* — uses **proprietary CBOE data** that distinguishes end-user vs market-maker — the paper's identification strategy relies on the very data the matrix *cannot* access. The size of the wedge between identified and inferred is the implicit error bar.
- **Adrian, T. & Shin, H. S. (2010)** — *Liquidity and Leverage* — Journal of Financial Intermediation 19(3): 418–437. Documents how dealer balance-sheet constraints can drive seemingly irrational pricing — the constraint is invisible to external observers.
- **Brunnermeier, M. K. & Pedersen, L. H. (2009)** — *Market Liquidity and Funding Liquidity* — Review of Financial Studies 22(6): 2201–2238. Funding shocks force liquidations that violate naive flow-inference.

### Mitigation

Treat dealer-positioning inferences as **directional, not magnitude-precise**. Use vanna/charm signals to set *sign* of expected dealer flow but not *magnitude*. During known stress events (margin calls, FOMC surprises, geopolitical shocks), disable the matrix.

---

## Limitation 07 — 0DTE intraday hijacking

### Framework statement
> "0DTE 的日内劫持
> 尤其收盘前两小时 · CPI / FOMC / OPEX 事件日 0DTE 可能全天主导短线路径 · 不用周/月度矩阵"

### Why it's true

Zero-days-to-expiry options have grown from <5% of SPX option volume pre-2022 to a verified majority share across the entire Cockpit universe in 2025 (CBOE source data):

| Ticker | 0DTE share of options volume | Source |
|---|---|---|
| **SPX** | **59% (FY 2025)**; record 62.4% Aug 2025; 48% Oct 2024 → 56% Feb 2025 → 61% May 2025 trajectory | CBOE State-of-the-Options-Industry 2025; "SPX 0DTE Options Jump to Record 62% Share" |
| **SPY** | **~45% (2025)** — roughly 4–5M 0DTE contracts/day of ~10M total SPY contracts | Multiple practitioner sources (Cboe, SpotGamma, Databento) |
| **QQQ / NDX** | up to **78%** on peak days for Nasdaq 100 options (record) | CBOE-linked practitioner commentary |
| **IWM** | not separately disclosed; ETF baseline lower than SPX/NDX, generally < 40% | inferred — needs Phase 0 verification |
| All US-listed options (market-wide) | **24.1% (2025), up from 21.5% (2024)** | CBOE |

**Implication for the Cockpit**: at FY 2025 share of 59% SPX / ~45% SPY / up to 78% QQQ, the *majority* of options volume on the v1 universe is in contracts with no relevance to matrix dimensions that operate on multi-day horizons (Vanna, Charm, Skew, Term Structure). 0DTE flows are *intraday* and dominated by dealer gamma scalping at very high frequencies. The framework's weekly/monthly dimensions are operating on multi-day timescales and are blind to intraday 0DTE-driven path effects.

This is the **single largest threat to v1 product viability**. Strategy 1 (short-vol on consistent vol-down) is most exposed; Strategy 4 (decision-tree compliance / NO-TRADE) is least exposed. Backtest must stratify by 0DTE-share regime — see [`09-backtest-plan.md`](09-backtest-plan.md) §6.5.

### Literature validation — recent papers

- **Dim, C., Eraker, B. & Vilkov, G. (2024)** — *0DTEs: Trading, Gamma Risk and Volatility Propagation* — SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190 — direct academic treatment of 0DTE dealer-gamma dynamics.
- **Brogaard, J., Han, J. & Won, P. Y. (2024)** — *Does 0DTE Options Trading Increase Volatility?* — SSRN. https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=4426358 — uses proprietary OMM position data to estimate dealer-gamma impact on index volatility.
- **CBOE white papers (2023–2024)** on 0DTE flows — vendor-published; cite with caveat.

### Mitigation

- Identify event days (CPI / FOMC / OPEX) ex-ante from a calendar
- On event days, **disable matrix-based trade signals during the last 2 hours of trading** (per framework's own prescription)
- For intraday operation in a 0DTE-heavy regime, build a separate intraday-gamma module distinct from the matrix

---

## Limitation 08 — Per-dimension credibility is uneven, and the joint 6-dim claim is unvalidated

### Framework statement

The framework presents the matrix as a unified 6-dimension reading whose joint consistency check ("all 6 same direction") is the primary trade-gate. This presentation implies the six dimensions deliver guidance of comparable credibility. **They do not** — neither in literature backing nor in v1 data plumbing.

### Why it's true

Two separate effects, often conflated:

**(a) Per-dimension credibility varies by literature depth.** Skew, term structure, and VRP each have decades of peer-reviewed empirical support for the *direction* of their signal (compressed skew → tail-hedge demand falling, contango → carry available, etc.). Vanna and Charm have solid academic support for the *mechanism* (dealer rebalance, OPEX pinning) but the framework's *direction-mapping rules* (the 4 conditional vanna readings, the pin-distance thresholds) are the framework author's synthesis of GPP 2009 + intraday flow data — not directly claimed by GPP. IM-event-percentile and 4-footprint Flow are operationally meaningful concepts but require infrastructure (event calendar, classifier) the framework assumes exists.

**(b) The joint claim is the framework author's contribution, not literature.** The specific assertion *"6 dimensions agreeing predicts forward returns better than any single dimension"* — including the §0.2 tolerance bands (5/6 + 1 neutral, 4/6 with cluster-coverage override) — does not appear in any cited paper. It is a reasonable hypothesis derived from the dimensions' partial collinearity (per Limitation #1) but it is **not validated**. Validation requires forward data the current UW subscription cannot supply historically (see `reviews/2026-05-15-uw-history-spike.md`).

### Literature validation

What is in the literature, dimension by dimension:

| Dim | Per-dim direction claim that holds | Joint-signal claim |
|---|---|---|
| Skew | Tail-hedge demand drives 25Δ RR; Bates 1991, BKM 2003 | Not claimed jointly |
| Term | Curve shape distinguishes idiosyncratic from systemic; Mixon 2007, Johnson 2017 | Not claimed jointly |
| VRP | Long-run positive premium; carry harvestable in mean; Carr-Wu 2009, BTZ 2009 | Not claimed jointly |
| Vanna | Dealer rebalance produces flow signature; GPP 2009 | The 4 conditional readings are synthesis, not literature |
| Charm | OPEX pinning is real; Ni-Pearson-Poteshman 2005, Baltussen 2021 | The pin classifier specifics are synthesis |
| IM | √(2/π) coefficient is real; Brenner-Subrahmanyam 1988 | Event-percentile interpretation is synthesis |
| Flow | Aggressor inference is studied; Easley-O'Hara-Srinivas 1998, Savickas-Wilson 2003 | 4-footprint taxonomy is synthesis |

The joint claim — *the matrix as a whole* — is unvalidated. Each per-dimension *direction* claim is well-supported individually.

### v1 plumbing gap compounds this

The v1 Cockpit (per plan `2026-05-15-cockpit-matrix-plan.md`) ships with:

- **High-credibility, fully plumbed**: Skew, Term, VRP (proxy). These deliver the academically-cited guidance directly.
- **Medium-credibility, simplified plumbing**: Vanna (EOD only, no intraday flow-color overlay), Charm (v1 proxy without OI-clustering refinement). These deliver direction labels but at lower confidence than literature mechanism alone implies.
- **Always `stale` in v1**: IM (no event calendar), Flow (no footprint classifier). These do not contribute to the consistency count.

**Effective dim count in v1: 5, not 6.** The matrix is honest about this — IM and Flow are labeled `stale`, not `neutral`. The consistency tier table evaluates against the fresh-dim denominator. The State tab displays "5 fresh dims, N agree", not "6/6". This is documented in the plan §"v1 dimensional coverage".

### Mitigation

The matrix is mis-read if interpreted as a *trade oracle* (the joint-claim framing). It is correctly-read as a *dashboard of market-state descriptors*, with these guarantees:

**What the product credibly delivers in v1**:

- *"Is tail-hedge demand expanding or compressing vs the 180-day window?"* — Skew, high confidence
- *"Is the curve pricing event risk or systemic risk?"* — Term 4-state classifier, high confidence
- *"Is short-vol carry available and within historical band?"* — VRP proxy + z-score, high confidence
- *"Where does dealer positioning concentrate for the nearest expiry?"* — Vanna/Charm strike profiles, medium confidence as visualization; lower confidence as classification
- *"Is there a high-OI strike near spot at OPEX?"* — Charm v1 proxy, medium confidence
- *"Are the available dimensions telling a consistent or conflicting story?"* — Joint consistency tier, **experimental**, read as "signal loudness" not "trade recommendation"

**What it does not credibly deliver in v1**:

- Position sizing or entry/exit triggers
- Intraday signals (Phase 1 cadence is EOD-only)
- Single-name guidance (universe is SPX/SPY/QQQ/IWM only per Limitation #4)
- Validated joint-6-dim edge claim — that question is open until month 6+ when ~125 trading days of `matrix_state_snapshots` exist and the pre-committed evaluation cells (plan Phase 6 §"Pre-committed evaluation cells") have power
- IM event-percentile guidance until the event calendar table is built
- Footprint-classified flow until the 4-footprint classifier is built

**Communication discipline**:

- State tab displays the consistency tier with explicit "experimental" labeling and a denominator showing fresh-dim count
- Cockpit AI (when built) is constrained to cite per-dim sources, never to claim "the matrix is bullish/bearish" as if the joint reading were validated
- Trade-plan generation is explicitly out of scope; the product offers no order tickets and no position sizing

This limitation is the most important one to internalize when reading the Cockpit: **per-dim guidance is credible; the joint reading is experimental.** Treat the product accordingly.

---

## Cross-cutting consequence

The eight limitations together imply a **specific operating envelope** for the matrix:

| Allowed | Disallowed / requires caution |
|---|---|
| SPX / SPY / QQQ trades | Single-name *without* per-dimension caveat application |
| Multi-day to multi-week horizons | Intraday (especially last 2h) on event days |
| Calm-to-elevated-vol regimes | Systemic shocks (Volmageddon / COVID / 2008-style first-wave) |
| Decision tree's mandatory invalidation rule | "Naked" matrix signals without invalidation lines |
| Flow signals corroborated by a non-flow dimension | Flow signals from low-liquidity strikes / multi-leg block trades |
| Dealer-flow inference for *sign* | Dealer-flow inference for precise *magnitude* |
| Per-dim guidance (skew / term / VRP especially) | Joint-6-dim consistency tier as a trade recommendation — read as experimental signal-loudness only (per Limitation #8) |

The matrix's takeaway #02 — *"true risk management = NO-TRADE when 6 conflict"* — is the meta-mitigation: the matrix is most useful as a *trade-blocker*, not a trade-generator. Limitation #8 sharpens this further: even the per-dim *guidance* the matrix produces is what credibly ships in v1; the joint reading is an unvalidated overlay.

---

## Cross-references

- Decision tree Step 4 (mandatory invalidation) is the operational manifestation of these limitations — [`00-overview.md`](00-overview.md)
- Per-dimension single-name caveats — each dimension doc's §5
- Scenario C operating mode (matrix in stress regime — risk management only) — [`00-overview.md`](00-overview.md)
- Backtest robustness tests must explicitly model these limitations as boundary conditions — [`09-backtest-plan.md`](09-backtest-plan.md)
