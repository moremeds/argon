# 06 — Cyclical Factors (Layer 2)

The article's macro framework plus viviennaBTC's 8 factors, sitting inside the layered architecture as the **cyclical** input — gated on regime applicability. Currently suspended per [03-post-2022-regime-break.md](./03-post-2022-regime-break.md), surfaced on the dashboard for context but not for action.

---

## What survives from the article

Three pieces of the article's framework survive cross-validation:

1. **The SDF interpretation** — gold priced by covariance with bad times; M weighs bad-times returns highly. Theoretically clean, drawn from Cochrane (2005). Informs the entire architecture, not just Layer 2.

2. **The three-regime taxonomy** — low-inflation, moderate-inflation-trap, high-inflation-unanchored. Useful classification of the cyclical state. The threshold values (CPI 2-4% / T5YIFR 2.5-3.0%) are heuristic; expose as configurable.

3. **The A/B position split** — A as cyclical (real-rate-driven), B as structural/tail. The split maps cleanly to layered execution: A lives in Layer 2 (gated), B lives across Layer 1 (structural) and Layer 3 (valuation tail risk).

---

## The article's "regime zones" (heuristic, not validated)

The article's three regimes, with the signals that classify into each. **These thresholds are article-derived folklore, not empirically calibrated.** The Codex review flagged that no academic source pins T5YIFR > 2.8% as an "unanchored" boundary. The Fed's own common-inflation-expectations work treats anchoring as a latent multi-indicator construct (TIPS forwards, SPF surveys, Michigan surveys), not a single T5YIFR cutoff. Treat the labels below as **article zones**, not as authoritative regime classifications.

| Article zone | CPI YoY | T5YIFR | Article's prescription |
|---|---|---|---|
| **"Real-rate-driven" zone** | < 2% | < 2.5% | Article sizes A on DFII10 change; B persistent |
| **"Moderate-inflation-trap" zone** | 2-4% | 2.5-2.7% | Article zeros A; B persistent |
| **"Article unanchored" zone** | > 4% | > 2.8% | Article goes full A + B; we do **not** ship this as a "regime" label |

**Inputs (all FRED, daily/monthly):**

- `CPIAUCSL` — CPI All Urban (monthly, ~2-week lag)
- `T5YIFR` — 5-year 5-year forward inflation expectations (daily)
- `DFII10` — 10-year TIPS yield (daily), 60-day change as cyclical-posture signal

**Dashboard output:** current zone label (with explicit "article zone" framing), current value of each input, distance to next zone threshold. The dashboard should clearly indicate the threshold values are configurable defaults, not validated boundaries. **Configurability:** at minimum, expose all three thresholds (T5YIFR low/mid/high, CPI low/mid/high) as runtime-configurable parameters.

**Calibration TODO:** before any threshold value is shipped as a production input, derive thresholds empirically from the historical T5YIFR distribution (e.g., quartile-based) and compare against a multi-indicator anchoring basket (T5YIFR, T10YIE, SPF long-run expectations, Michigan long-run expectations, Fed CIE index). Tracked in [10-open-research-questions.md](./10-open-research-questions.md) as the threshold-calibration question.

**Critical gating:** all of this is **gated** on the correlation gauge from [03-post-2022-regime-break.md](./03-post-2022-regime-break.md). The zone classifier and signals are computed and surfaced regardless; the article's *cyclical posture* is only the primary narrative when the gauge says operative or partial. Under suspended-gauge conditions, the article-zone label is shown as context with a clear "framework suspended" badge.

---

## The two-force model

The article's claim that gold responds to two same-direction forces — discount-rate channel (real-rate change) and hedge-demand channel (safe-haven flows) — survives as a useful conceptual frame. Operationally:

| Force | Observable | Cross-check |
|---|---|---|
| Discount-rate channel | DFII10 daily change, 60-day change | DGS10 if breakdown needed |
| Hedge-demand channel | VIXCLS daily, BAMLH0A0HYM2 (HY OAS) | GVZCLS |

Both forces firing simultaneously and in the same direction is the strongest cyclical signal. Pre-2022 this combination produced the cleanest gold rallies (e.g., 2019-2020 COVID era). Post-2022 it has not produced predictable gold response (e.g., 2022 risk-off was contemporaneous with gold weakness, not strength).

---

## viviennaBTC's 8 factors as cyclical inputs

The 8 factors from the X.com post live in Layer 2 alongside the article's framework. They are reproducible in this repo (see [08-viviennabtc-factor-critique.md](./08-viviennabtc-factor-critique.md)) and serve as additional cyclical inputs rather than replacement signals.

| # | Factor | Cyclical role |
|---|---|---|
| F1 | DXY (DTWEXBGS) | Dollar regime — gold's price-level inverse driver |
| F4 | BEI (T10YIE) | Inflation-expectations component of T5YIFR |
| F5 | GPR (Caldara-Iacoviello) | Hedge-demand channel, surviving post-2022 |
| F6 | GVZ (GVZCLS) | Hedge-demand channel, gold's own implied vol |
| F10 | TIPS-BEI Spread (DFII10 − T10YIE) | Composite real-rate signal; treat IC=0.73 claim skeptically |
| F11 | DXY 20d momentum | Derived from F1 |
| F13 | Gold-GDX divergence | Cross-asset miners signal |
| F14 | GVZ 20d momentum | Derived from F6 |

**F5 (GPR) and F13 (Gold-GDX divergence) are the two factors whose signal value plausibly survived the 2022 break** — GPR because geopolitical tail risk became a *more* dominant driver post-2022; F13 because miners-vs-physical-gold divergence captures positioning shifts orthogonal to real rates.

---

## How Layer 2 is presented on the dashboard

Three components, all visible regardless of regime gauge state:

### Component A: Regime classifier

Top section. Three-card display:
- Current CPI YoY (value, threshold band, regime classification)
- Current T5YIFR (value, anchoring status)
- Current DFII10 60-day change (value, A-position direction if operative)

### Component B: Two-force indicator

Side panel. Two arrows (discount-rate channel direction, hedge-demand channel direction) with current readings. Annotation when both arrows align same-direction.

### Component C: 8-factor grid

Lower section. Z-scores or 52-week percentile for each of F1, F4, F5, F6, F10, F11, F13, F14, with miniature sparklines.

### Posture layer (conditional)

The cyclical-posture statement lives **below** the components, with a banner that reflects the correlation gauge state. v1 uses **posture / risk / scenario language**, not numerical position recommendations — see [04-three-layer-architecture.md](./04-three-layer-architecture.md) on why recommendation language is deferred until backtest validation exists.

- **Operative gauge:** "Cyclical posture (article framework): {real-rate-driven / moderate-trap / article-unanchored zone}. Discount-rate channel direction: {…}. Hedge-demand channel direction: {…}." Posture-level statement, not a sizing recommendation.
- **Partial gauge:** "Cyclical posture at partial confidence. Article framework would say {…}, but correlation gauge is in the partial band. Structural posture (Lens 1) is co-primary."
- **Suspended gauge:** "Cyclical posture suspended (correlation gauge at {value}, below operative band). Article framework informative but not actionable. See Lens 1 for current structural posture."

---

## Implementation notes

### Data sources

All FRED. See [09-data-sources-catalog.md](./09-data-sources-catalog.md) for full list. Plus:

- GPR daily series from matteoiacoviello.com (free CSV)
- GLD and GDX OHLC from massive.com (already wired)

### Signal computation

The cyclical layer is **the simplest layer in the architecture**:
- Threshold-based regime classification: ~20 lines of Python
- 60-day rolling changes: pandas one-liners
- Factor z-scoring / percentile: pandas rolling windows

No ML, no XGBoost. The article's framework + viviennaBTC's factors are deterministic given the inputs.

### Gating logic

The regime gauge (252-day rolling Gold ↔ DFII10 correlation) lives in a separate computation module and feeds both the dashboard banner and the A-position recommendation gate. Compute daily; cache 252-day window.

### What we explicitly do NOT do (v1)

- Train any ML model on the 8 factors in v1. Per the Codex-recommended Option A-prime, v1 is a research cockpit with audit scaffold, not a fitted predictor. The model sequence (linear → state-space → trees challenger → partial pooling) belongs to Phase A3. See [04a-quant-model-spec.md](./04a-quant-model-spec.md) and [10-open-research-questions.md](./10-open-research-questions.md) Q13 / R5.
- Pool pre-2022 and post-2022 history for regression-based weighting until the [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) replication is complete.
- Surface F10 with its claimed IC=0.73 weight. Include it as a transparent input, but do not let any sizing logic depend on the high-IC claim. See [08-viviennabtc-factor-critique.md](./08-viviennabtc-factor-critique.md).
- Ship the article-zone labels (especially "unanchored") as if they were validated regime classifications. They are heuristics with article-derived thresholds; the dashboard should reflect that.
