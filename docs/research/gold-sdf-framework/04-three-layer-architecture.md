# 04 — Three Lenses (Architecture)

The synthesized model the implementation should follow. Built from the cross-validation findings: the article's framework, the apparent post-2022 regime break, the four structural-flow inputs added during research, and Erb-Harvey's valuation overlay. Replaces the article's single-framework approach.

> **Naming note:** the filename retains "three-layer" for cross-reference stability, but the framework's preferred name is **three lenses** or **three signal families.** The earlier "orthogonal layers" framing was wrong — the lenses share variance materially (see "Shared variance" below). Layered/orthogonal language overstates how independent the signals are.

---

## Why three lenses

A single-framework gold model fails for one of two reasons:

- **Macro-only models** (article's two-force, viviennaBTC's 8-factor) fit the pre-2022 data but currently appear to track noise on gold returns. The Gold ↔ TIPS correlation collapse described in [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) is the prima facie evidence; internal replication is still required.
- **Flow-only models** (central bank tracking, ETF monitoring) describe the current dominant buyer but ignore the conditions under which the macro framework reasserts. They have no story for "what happens when the structural bid pauses."

A multi-lens model accommodates both. Each lens answers a distinct question, even though the underlying inputs are not independent:

| Lens | Question it answers | Current state |
|---|---|---|
| **1. Structural flow** | Who is the marginal buyer and what are they doing? | Apparently dominant 2022-present |
| **2. Cyclical** | What would gold be doing if the pre-2022 framework were operative? | Gated on correlation gauge |
| **3. Valuation overlay** | Is gold expensive relative to its long-run real-price anchor? | Always-on tail-risk flag, never a sizing input |

The dashboard surfaces all three. **Posture descriptions** draw from whichever lens is most informative under current conditions. Numerical position sizing is *not* a v1 deliverable — see [04a-quant-model-spec.md](./04a-quant-model-spec.md).

---

## Shared variance: the lenses are not orthogonal

A previous version of this document framed the lenses as "orthogonal layers." That framing was wrong. The lenses overlap in meaningful ways:

- **Central-bank buying** is partly a geopolitical-risk and USD-reserve-confidence factor → overlaps with **GPR, DXY, TIPS, and inflation expectations** (all Lens 2 inputs).
- **ETF holdings** are Western institutional flow → that is exactly the channel where real-rates and DXY used to express themselves (Lens 2).
- **Local-currency gold pricing** is FX stress combined with USD gold → overlaps with DXY, inflation, and regional risk (Lens 2).
- **Valuation (Lens 3)** is endogenous to Lens 1: if central-bank flow lifts gold into the 90th real-price percentile, the valuation percentile is partly a transformed consequence of structural flow, not an independent input.
- **Gold-GDX divergence (F13)** sits between structural flow, equity risk, energy/mining costs, and risk appetite.

This is fine for a **research cockpit** that presents posture statements from each lens for narrative coherence. It is **dangerous for a quant model** that would use them as if they were independent inputs — any sizing scheme that aggregates lens outputs without variance accounting will overstate confidence by double-counting the same macro shock under different names.

**Implications for implementation:**

- If/when this becomes a model with composed sizing, **add variance accounting**: correlation matrix between lens inputs, hierarchical clustering, VIF, PCA / partial residuals, regime-conditional feature importance.
- Position sizing should **assume correlated signals** until proven otherwise. Combine via shrinkage, not naive addition.
- Dashboard copy should **not claim independence** between lens views.

---

## Lens 1 — Structural-flow signals (apparently dominant 2022-present)

The set of signals that captures the current marginal-buyer dynamic. Detailed in [05-structural-flow-factors.md](./05-structural-flow-factors.md).

```
Lens 1 components
├── Per-country central bank reserves (monthly, IMF/WGC, ~1mo lag)
│   ├── Strategic accumulators (China, India, Russia, Turkey)
│   ├── Tactical defenders (Egypt, Kazakhstan)
│   └── Reserve diversifiers (Poland, Czechia, Singapore)
├── ETF holdings (daily)
│   ├── GLD, IAU, GLDM, PHYS
│   └── Aggregated weekly WGC total
├── Exchange inventories
│   ├── COMEX vault stocks (daily, CME)
│   ├── LBMA loco London (monthly)
│   └── SGE physical (daily, Shanghai)
├── Local-currency gold pricing (daily, computed)
│   └── XAU/CNY, XAU/INR, XAU/TRY, XAU/JPY
├── CFTC COT positioning (weekly, CFTC API/CSV)
│   ├── Managed-money net + percentile
│   ├── Commercials net + percentile
│   └── 4-week change
└── UW options stress (daily snapshots; persist v1, model v2)
    ├── GLD / GDX / IAU IV skew and put-call IV spread
    ├── Dealer gamma proxies
    └── Large-trade flow events
```

COT and UW-options-stress are new additions per the Codex review. COT is the largest single missing factor class in the original draft. UW options data is the repo's differentiated edge and should be persisted from v1 even if not yet a model input.

**Dashboard prominence:** primary panel. Lead chart is GLD holdings overlaid on gold price 2020-present — visually the cleanest evidence of the apparent regime change.

---

## Lens 2 — Cyclical signals (gated on correlation gauge)

The article's framework plus viviennaBTC's 8 factors. Detailed in [06-cyclical-factors.md](./06-cyclical-factors.md).

```
Lens 2 components
├── Article's three "regime zones" (CPI YoY, T5YIFR, DFII10 60d change)
│   └── Article-derived thresholds; NOT empirically calibrated. See 06.
├── Two-force narrative
│   ├── Discount-rate channel: DFII10
│   └── Hedge-demand channel: VIX + HY OAS + GPR
├── viviennaBTC's 8 factors
│   ├── F1 DXY, F4 BEI, F5 GPR, F6 GVZ
│   ├── F10 TIPS-BEI spread, F11 DXY momentum
│   ├── F13 Gold-GDX divergence, F14 GVZ momentum
└── Gating: rolling Gold ↔ DFII10 correlation gauge
```

**Correlation gauge mechanics (default thresholds, to be calibrated empirically):**

| Rolling 252d correlation | Cyclical lens treatment | Dashboard color |
|---|---|---|
| ≈ `[-1.00, -0.50]` | **Operative** — cyclical posture is the primary narrative | green |
| ≈ `[-0.50, -0.20]` | **Partial** — cyclical posture is one of two narratives, with structural flow | amber |
| ≈ `[-0.20, +1.00]` | **Suspended** — cyclical lens shown for context but not used to drive posture | red |

These default bounds are heuristic. They must be calibrated against the rolling-correlation distribution and structural-break tests required in [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) before being shipped as production thresholds.

Currently the gauge appears to be in the **suspended** range based on external estimates; internal replication pending.

---

## Lens 3 — Valuation overlay (always-on; never a sizing input)

Erb-Harvey's "real price of gold" mean-reversion signal, plus alternative valuation anchors. Detailed in [07-valuation-overlay.md](./07-valuation-overlay.md).

```
Lens 3 components
├── Real price of gold (CPI-deflated, USD)
│   └── Historical percentile (1900-present where available)
├── Alternative anchors
│   ├── Gold / M2 ratio
│   └── Gold / SPX ratio
└── Output: tail-risk flag — context overlay only, never a sizing multiplier
```

**Dashboard prominence:** side panel. Surface as risk context, never as a buy/sell signal and never as a position-size scaler. The framing is: "regardless of which lens dominates, gold is currently in the {X}th percentile of real-price history — mean-reversion risk = {Low / Moderate / High / Severe}."

> **Resolved contradiction:** An earlier draft of [04a-quant-model-spec.md](./04a-quant-model-spec.md) proposed using the valuation overlay as a position-size multiplier (vol-scaler form). That contradicted [07-valuation-overlay.md](./07-valuation-overlay.md), which explicitly says valuation is never a sizing input. Per the Codex review, 07 is correct: until a backtest demonstrates that valuation-conditional sizing improves Sharpe out-of-sample, Lens 3 is a warning overlay, not a mechanical scaler.

---

## How the lenses combine into posture statements

The v1 dashboard does **not** produce a single "buy/sell" output and does **not** produce numerical position sizes. It produces three posture statements:

1. **Structural posture (from Lens 1).** "Central bank buying remains elevated, ETF outflows are stabilizing, COMEX inventory is rising — structural bid intact." (descriptive, not prescriptive)
2. **Cyclical posture (from Lens 2, conditional on correlation gauge).** "Cyclical framework suspended. If reactivated, current macro inputs would map to article's *unanchored zone*." (descriptive, with explicit gauge state)
3. **Valuation risk (from Lens 3).** "Real gold price in the 92nd percentile of post-1900 history — mean-reversion risk: High." (tail-risk context, not a signal)

A user reading these three statements can form an informed view. The dashboard's job is honesty about which lens inputs are firing and which are not, not to compress them into a single recommendation that hides the underlying state.

### Posture vs recommendation language

Until backtest validation exists, v1 uses **posture, risk, and scenario language** — not "recommendation," "position size," or "trade." This is a deliberate constraint per the Codex review: shipping recommendation language without out-of-sample evidence overstates confidence. The v1 product is a *cockpit* that describes state; it is not a *signal* that prescribes action.

The cyclical-lens posture is presented under explicit gauge-state copy:

> *Cyclical posture description suspended. The 252-day Gold ↔ TIPS correlation gauge currently reads {value}, below the operative band of approximately -0.5. The article's framework is informative but not actionable under current correlation conditions.*

### The B position split

The article's "B position" was conceptually muddled — sometimes safe-haven tail hedge, sometimes structural CB-bid context, sometimes permanent allocation. Per the Codex review, these are different trades with different horizons. v1 splits them:

- **Strategic allocation context** — long-horizon structural exposure rationale, informed by Lens 1 (CB bid intact, ETF flows turning, etc.). Persistent.
- **Event hedge context** — short-horizon tail-hedge framing per Baur & Lucey (2010), whose original finding was ~15 trading days of safe-haven duration. Context-bounded.

These are surfaced as **separate panels** with different copy, not collapsed into a single "B position" recommendation.

---

## Where this departs from the article

The article presents a single framework with three regimes inside it. This architecture presents three frameworks (structural / cyclical / valuation), with the article's two-force model living inside the cyclical layer as one component among several.

**The article's strongest claims survive in Layer 2.** Specifically:
- The three-regime taxonomy (low-inflation / moderate-trap / unanchored) is a useful classification of the cyclical state
- The A/B position split is a defensible operational frame for cyclical and structural exposure respectively
- The SDF interpretation is theoretically sound and informs the entire architecture

**The article's weaker claims are corrected here:**
- The implicit assumption that the gold-real-rate channel is stationary is dropped (regime gauge gates Layer 2)
- The omission of structural-flow factors is fixed (entire Layer 1 added)
- The omission of valuation risk is fixed (entire Layer 3 added)
- The treatment of B position as a permanent strategic hold is qualified (Baur-Lucey 15-day finding surfaced)

---

## Implementation reading map

| Lens | Spec section | Data sources |
|---|---|---|
| Lens 1 | [05-structural-flow-factors.md](./05-structural-flow-factors.md) | WGC, SPDR, BlackRock, CME, LBMA, SGE, FRED FX, CFTC COT, UW options |
| Lens 2 | [06-cyclical-factors.md](./06-cyclical-factors.md) | FRED (DFII10/T5YIFR/CPIAUCSL/T10YIE/DTWEXBGS/BAMLH0A0HYM2/VIXCLS/GVZCLS), GPR, massive.com (GLD/GDX) |
| Lens 3 | [07-valuation-overlay.md](./07-valuation-overlay.md) | FRED (CPIAUCSL, M2SL), massive.com (gold) |

Full source catalog with costs and cadences in [09-data-sources-catalog.md](./09-data-sources-catalog.md). Review-response history: [CHANGELOG.md](./CHANGELOG.md).
