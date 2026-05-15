# 6-Dimension Options Matrix — Overview

**Source**: FutureAlpha podcast Season 02 Episode 10 finale (the framework's authoritative reference)
**Captured**: 2026-05-14
**Status**: research idea — to be validated against literature, cross-referenced with current `uw_scan` setup, and proposed for backtest

## Product direction

This framework will ship as a dedicated **Cockpit** section in the web app (`/cockpit/[ticker]`), separate from the stock-detail page. Scoping decision (2026-05-14):

- **Universe**: SPX (European cash, academic reference subject) · SPY (American ETF, dealer-flow regime) · QQQ (tech beta) · IWM (small-cap beta). Four tickers. Single-name extensions are explicitly out-of-scope for v1 per Limitation #4.
- **AI report scope**: The stock-detail AI report (`reports/trade_insights_ai.py`) **keeps** the `"vanna"/"charm"` blacklist at line 965 — single-name AI does not reason over these dimensions. A *separate* index-only AI report (`reports/cockpit_ai.py`) consumes the matrix; it is a different codepath with a different prompt.
- **UI structure**: 5 tabs grouped by collinearity cluster (see [§7 mapping table](#7-cross-reference-with-current-uw_scan-setup-summary) and [`08-implementation-gaps.md`](08-implementation-gaps.md)):
  - **State** — consistency check, decision tree status, signal heatmap
  - **Dealer** — Vanna + Charm, conditional readings
  - **Surface** — Skew + Term Structure, 4-state classifier
  - **Flow + IM** — 4-footprint classifier, IM vs historical event distribution
  - **VRP** — carry thermometer, strict VRP, sign-flip detector

**Scope**: Index-level only per the framework's own Limitation #4. Single-name caveats remain inline in each dimension doc as research notes — they document *why* the matrix is restricted to indexes, not how to extend it.

### Note on the AI blacklist scope (vanna / charm / skew)

The product decision is to **keep vanna and charm out of stock-detail AI** and route them only through the Cockpit AI. **Skew is treated differently**: it stays on the stock-detail page (already integrated as the reference implementation) *and* remains available to the stock-detail AI.

The asymmetry is intentional:

- **Vanna / charm** — these are *index-level dealer-flow phenomena* (Gârleanu-Pedersen-Poteshman 2009, Ni-Pearson-Poteshman 2005). The mechanism only holds when dealer-wide net positions exist; on single names, the inference is too noisy to license AI reasoning over. Blacklist at `reports/trade_insights_ai.py:965` stays.
- **Skew** — has academic precedent on single names (Bakshi-Kapadia-Madan 2003 explicitly studies single-name skew, with a different baseline). Single-name skew is a legitimate signal in its own right, not a degraded index inference. Stays available to stock-detail AI.

**Decision (user-confirmed)**: option (a) — keep skew available to stock-detail AI. No change to `trade_insights_ai.py:965`. If a future decision reverses this, adding `"skew"` to the blacklist tuple at that line only blocks the AI; the on-page chart and `VolMetrics.skew_25d` field remain and would also need to be addressed for full removal.

---

## 0. Operational definitions (needed before backtest or Cockpit-AI build)

### 0.1 Direction mapping — converting each dimension to {vol_up, vol_down, neutral}

The decision tree's Step 1 ("all 6 same direction") requires a deterministic mapping from each raw dimension reading to a directional label. Without this, "consistency_label" is not computable.

| Dim | Vol-down reading (carry-favoring) | Vol-up reading (risk-off) | Neutral / no-signal |
|---|---|---|---|
| **Vanna** | Conditional reading #1 (IV↓ + put-heavy prior flow + dealer pre-sold) → grind-up; **OR** reading #2 (IV↓ + call-heavy prior flow + dealer pre-bought) → reverse sell-off (vol crushes both ways; spot bias differs but vol direction is the same) | Conditional reading #3 (IV↑ + spot↓ + dealer net-short gamma) → reflexivity | Reading #4 (IV jitter + range-bound); also: any case where the three trigger conditions (net-gamma sign, prior flow color, pre-hedge state) are ambiguous |
| **Charm** | Pin-regime active: `\|pin_distance_sigma\| < 1.0` AND `IV_30d < median_90d` AND τ ≤ 5d | High-vol breaks the pin: `IV_30d > p70_90d` **paired with** at least one of (a) `ts_state ∈ {liquidity_back, mixed}` (b) skew z < −1 (c) `\|pin_distance_sigma\| > 2.0` | τ > 5d, pin candidate doesn't satisfy the vol-down rule, or `\|pin_distance_sigma\| > 2.0` alone without the high-vol pairing (means "no operative pin", not "risk-off") |
| **Skew** | `skew_25d_zscore_180d > +1.0` (compressed: UW value more positive than 180d mean → puts relatively less rich) OR `skew_25d_5d_change > 0` (smirk relaxing) | `skew_25d_zscore_180d < −1.0` (extreme negative: puts richer than usual) OR `skew_25d_5d_change < −2σ` (accelerated steepening) | z-score in (−1, +1) and 5d change in (−2σ, +2σ) |
| **Term Structure** | `ts_state ∈ {contango}` — systemic carry; **OR** `ts_state == event_back` — *idiosyncratic event-type* (the framework's Scenario A.1 short-vol setup explicitly relies on event_back; treating it as neutral would block Strategy 1 from ever reaching 6/6) | `ts_state ∈ {liquidity_back, mixed}` | None — every classifier state is mapped. The distinction between contango (systemic carry-down) and event_back (idiosyncratic carry-down) is preserved in `MatrixState.ts_state` for Scenario A.1 vs A.2 discrimination |
| **Implied Move** | `implied_move_event_percentile > 0.7` (event over-priced relative to history → IV likely to mean-revert downward) | `implied_move_event_percentile < 0.3` (event under-priced — realized may exceed implied) | percentile ∈ [0.3, 0.7] |
| **Flow** | Hedge-flow intensity falling AND directional-whale aligned with the matrix's emergent vol-down read | Hedge-flow intensity rising (defensive demand) OR directional-whale put-side dominant | Dealer-Hedge or Gamma-Scalper footprints dominant with no clear directional bias; or `aggressor_label_confidence == "illiquid"` for the ticker |
| **VRP (strict)** | `vrp_zscore_252d > +0.5` (carry rich) AND no `vrp_sign_flip_30d` | `vrp_zscore_252d < −0.5` **OR** `vrp_sign_flip_30d == TRUE` (regime-change alarm overrides the z-score band) | z-score ∈ (−0.5, +0.5) and no recent sign-flip |

**Direction sign convention**: "vol-down" = supports short-vol carry; "vol-up" = supports long-vol / tail-hedge. This mapping is the single source of truth used by `cockpit_matrix.build_matrix_state()` and the backtest. **Changes here invalidate prior backtest results.**

**Note on Flow as a 7th row in a 6-dim table**: per `00-overview.md` §1 the canonical framework folds Flow into Dimension 5 ("Implied Move + Flow"). For the consistency *count*, IM and Flow are read as two separate sub-dimensions whose direction labels must agree before the dim-5 vote is counted; if they disagree, dim-5 contributes `neutral`. This preserves the canonical 6-vote count without losing flow's information content.

### 0.2 Consistency tolerance — what counts as "6 agree"

Decision tree Step 1 is described as binary in the slides but the operational rule needs a tolerance band:

| Reading | Rule | Action |
|---|---|---|
| 6/6 same direction (no neutrals) | strict consistency | proceed to Step 2 (high-confidence) |
| 5/6 same + 1 neutral | strong consistency | proceed to Step 2 (proceed; flag the neutral dimension in the report) |
| 4/6 same + 2 neutral | weak consistency | proceed only if neither neutral is VRP or Term Structure (those are the highest-information dimensions per Johnson 2017 / BTZ 2009) |
| 3/3 directional split (any neutral count) | **explicit conflict** | NO-TRADE |
| 4/2 directional split | **mild conflict** | NO-TRADE |
| 5/1 directional split | NO-TRADE in v1; revisit with backtest data — may relax later if Strategy 4 shows the 5/1 cases are tradeable | NO-TRADE |

The 5/1 threshold is the most arguable; the backtest's Strategy 4 (decision-tree compliance, `09 §5`) should report Sharpe under the 5/1 inclusion and exclusion to determine whether this tolerance is value-additive.

**Cluster-coverage overrides** (per Limitation #1 — "true 6-direction agreement requires at least one signal from each cluster"):

- **Both Vanna and Charm neutral → NO-TRADE**, regardless of the count from the other four. Without dealer-flow confirmation the matrix's mechanism is unsupported — see [`07-limitations.md`](07-limitations.md) §1 confirmation-cluster table. This applies most stringently to Scenario B (post-event grind-up) which is *defined* by joint Vanna+Charm sign.
- **All four of (Skew, Term, IM, VRP) neutral while Vanna+Charm agree → "thin" consistency**: the IV-surface cluster is silent. Treat as "weak" tier per the table above, never "strong".
- **VRP sign-flip alarm (`vrp_sign_flip_30d == TRUE`) → force vol-up label** on the VRP row regardless of z-score band, and additionally **down-grade the tier** by one step (strong → weak; weak → NO-TRADE). A flipped carry regime is the framework's loudest single-dimension warning.

### 0.3 Data-freshness contract per dimension

When is a dimension's reading "stale"? The Cockpit must display reliable timestamps; readings past their stale threshold should be greyed or flagged. Recommended thresholds:

| Dim | Stale after | Reason |
|---|---|---|
| Vanna / Charm (intraday) | 30 min during RTH; 24 h after-hours | Per-strike greeks update intraday; staleness > 30 min during cash hours means missed dealer rebalance |
| Skew (25Δ rr 30dte) | 24 h | Daily endpoint; intraday change is small relative to noise |
| Term Structure | 24 h during normal regime; 30 min during stress | Curve shape rarely intraday-actionable; but during regime changes (Volmageddon-style) it can flip in hours |
| Implied Move | 30 min during RTH | Straddle/spot is real-time-sensitive; particularly important for IM-event-percentile |
| VRP (strict) | by definition lagged 30d; freshness = "nightly batch ran today" | Strict VRP cannot be real-time; freshness contract is "computed at the most recent EOD rollup" |
| VRP (proxy) | 24 h | Daily IV/RV cadence |
| Flow | 5 min during RTH | Real-time aggressor flow degrades fast in informational value |

These thresholds populate a `freshness_state` field on each `MatrixState` reading; the consistency check (§0.2) must **exclude** stale dimensions from the count, not pass them through as "neutral".

### 0.4 Definition of done — v1 success criteria

The v1 Cockpit ships when **all** of:

- [ ] 5 tabs render for all 4 tickers (SPX/SPY/QQQ/IWM) with non-stale data
- [ ] `cockpit_matrix.build_matrix_state()` returns a labeled `consistency_label ∈ {consistent_vol_up, consistent_vol_down, strong_vol_up, strong_vol_down, weak_vol_up, weak_vol_down, conflict, insufficient_data}` per §0.2
- [ ] **Sign-convention test passes**: a golden test in `tests/cockpit/test_skew_sign_convention.py` asserts that SPX baseline `risk_reversal` is negative (per UW convention), that `skew_25d_zscore_180d > 0` corresponds to "compressed smirk → vol-down", and that flipping the database value sign changes the consistency_label as expected. Same shape of test for `vrp` (Convention A) and Term Structure (`back − front`, positive = contango). These tests guard the §0.1 direction mapping against silent inversion if a future refactor reverses any of those signs.
- [ ] **Stale-dimension denominator rule** implemented: when a dimension is `stale` per §0.3, it is *excluded from the count* (not silently mapped to `neutral`). The consistency-tier table in §0.2 evaluates against `(directional_dims, total_fresh_dims)`, not `(directional, 6)`. Required because §0.3 explicitly says stale dimensions must not pass through as neutral.
- [ ] **`matrix_state_snapshots` table persisted** per `08 §5` row — every Cockpit page-load (or nightly batch, whichever produces canonical state) writes a row keyed by `(ticker, asof_date)` so the backtest can replay actual production state exactly. Without this, Phase 1 backtest in `09 §9` cannot verify look-ahead-free behavior.
- [ ] `cockpit_ai.py` returns a structured outcome citing only Cockpit-scope source paths (no stock-detail bleed-through)
- [ ] Backtest Phase 1 falsification criteria 1, 4, 5, 6 (per `09 §1`) have empirical answers (pass or fail, not "did not run"), **and a written disposition for each "fail" result**: criterion 1 fail → matrix is not tradeable as designed (do not ship as a trading aid; downgrade to research dashboard); criterion 4 fail → drop VRP from the consistency vote and re-run; criterion 5 fail → strip term-state from Strategy 1 entry rules; criterion 6 fail → invalidation rule is not value-additive, but the matrix may still ship as a *display* (no trading recommendation).
- [ ] No regression in stock-detail AI: existing `trade_insights_ai.py` blacklist still rejects vanna/charm; existing skew/term/VRP-proxy paths still produce outcomes
- [ ] Cockpit data-freshness flags surface on each tab (§0.3)

The Cockpit does **not** need to pass v1 if:
- Backtest Phase 2 / Phase 3 criteria 2, 3 are still untested (they require items 11–13 in `08 §4`)
- Cockpit AI prompt is rough (it is, by design — Phase 3 hardens it)
- The single-name research extension is unstarted (§11)

---

## 1. The six dimensions

The framework arranges options analytics as a *6-instrument cockpit*, deliberately mixing greeks (path-and-flow indicators), surface descriptors (cross-sectional vol shape), and a carry/expectation pair. The author's organizing metaphor is that **no single instrument is sufficient** — the matrix exists because every single-dimension inference has documented exceptions (see [`07-limitations.md`](07-limitations.md) and "Five single-dimension misreadings" below).

### Top 4 — greeks and surface shape

| # | Dimension | Author's metaphor | Formula / role | Operative time window |
|---|---|---|---|---|
| 1 | **Vanna** | 风 (wind) | ∂Δ/∂σ — conditional dealer IV-crush reaction | 1–3 days |
| 2 | **Charm** | 重力 (gravity) | ∂Δ/∂t — OPEX magnet + far-OTM Δ accelerated decay | 1–5 days |
| 3 | **Skew** | 形状 (shape) | OTM-call IV − OTM-put IV (UW convention; baseline negative for SPX-style smirk — see [`03-skew.md`](03-skew.md) §1) — tail-hedge demand thermometer | 2–8 weeks |
| 4 | **Term Structure** | 节奏 (rhythm) | front-month IV vs back-month IV — event-type vs liquidity-type backwardation classifier | hours to weeks |

### Bottom 2 — real-time + carry

| # | Dimension | Role | Constituent |
|---|---|---|---|
| 5 | **Implied Move + Flow** | market expectation + capital intent | Implied Move ≈ 0.8 × straddle/spot; **4 flow footprints**: Directional Whale, Hedge Flow, Dealer Hedge, Gamma Scalper (long-gamma vs short-gamma) |
| 6 | **VRP** | carry economics | VRP = E^Q[Var] − E^P[Var]; SPX long-run ≈ 3–5 vol points. Three drivers: insurance demand, fat-tail risk premium, risk aversion |

Per-dimension deep dives, with literature validation, are in [`01-vanna.md`](01-vanna.md) through [`06-vrp.md`](06-vrp.md).

---

## 2. The 4-step decision tree

The framework prescribes a strict ordering. No step is optional. The author's stance: *"trading is not finding an entry reason — it is designing exit conditions."*

### Step 1 — Consistency check

- All six dimensions point the same direction → high-confidence setup → proceed to Step 2.
- Conflict (3–3 or 2–4 split) → **default NO-TRADE.**

The framework's central insight is that the matrix's primary job is to **block low-confidence trades**, not generate them.

### Step 2 — Local vs global

- **Event-type signature** (single near-month points up; back of curve flat) → idiosyncratic, isolate: single-name short-vol or single-name long-put.
- **Liquidity-type signature** (entire curve inverts; risk thermometer red across surface) → systemic, **reduce short-vol exposure and add portfolio hedge.**

This step is the matrix's *idiosyncratic-vs-systemic discriminator*. See [`04-term-structure.md`](04-term-structure.md) for the formal four-state classification (contango / event-back / liquidity-back / mixed).

### Step 3 — Time-window check

| Horizon | Dominant dimensions |
|---|---|
| Short (1–3 days) | Vanna + Charm + near-month Implied Move |
| Mid (1–4 weeks) | Skew + Term Structure |
| Long (1–6 months) | VRP + far-month Skew + Hedge Flow |

Reading dimensions outside their time window is one of the framework's "Seven Limitations" (Limitation #3 — data lag for high-frequency dimensions); see [`07-limitations.md`](07-limitations.md).

### Step 4 — Invalidation (mandatory)

Pre-entry, write down a single concrete line: **"If this data appears, I close immediately."**

- Cannot write the invalidation line → **not allowed to enter.**
- The framework's worked example (Scene A, short ATM straddle on event-driven IV over-pricing) lists explicit invalidation triggers: Term flips to liquidity-type → immediate close + buy OTM put; Skew accelerated steepening (put-IV up >1.5× call-IV up) → close; VRP thermometer turns negative → close; Flow color flips call-heavy → re-evaluate vanna; any trigger fires → no excuses, no waiting for mean revert.

The author's stance: "If you can't write what data would prove you wrong, this isn't a trade — it's a prayer."

---

## 3. Three canonical scenarios

### Scenario A — Pre-event setup (earnings / FOMC / CPI approaching)

Six dimensions consistent vol-down → **short-vol candidate (defined-risk only, never naked).**

The framework subdivides A into two mutually-exclusive sub-cases:

| Sub-case | Signature | Tools |
|---|---|---|
| **A.1 Idiosyncratic event-driven** | Term: single-point near-month event-type bump; Skew: smirk (not accelerating); Implied Move > historical distribution; Hedge Flow rising; Vanna aligned with flow color | Short ATM straddle / iron condor / iron butterfly + deep OTM put hedge |
| **A.2 Systemic + event overlap** | Term: full-curve inverted (liquidity-type); Skew: accelerated steepening; Hedge Flow surging; VRP near zero (carry crushed); Vanna in short-gamma zone | **Long tail, NOT short-vol.** Long deep OTM put / long VIX call. "Missing the carry costs 1×; getting blown up in a systemic shock costs 100×." |

Per-dimension readings on slide IMG_4623 (Scene A pre-event setup) and side-by-side on IMG_4624 (idiosyncratic vs systemic).

### Scenario B — Post-event vol crush

Vanna's direction *depends on prior flow color* — it is not automatically bullish.

| Prior flow signature | Dealer position pre-event | IV crush behavior | Path |
|---|---|---|---|
| Put-heavy hedge flow | Dealer pre-sold stock to hedge | IV crush → dealer un-shorts → re-buys stock | **Grind up** |
| Call-heavy event chase | Dealer pre-bought stock to hedge call writes | IV crush → dealer unwinds long → sells stock | **Reverse sell-off** |

"Post-event grind up is not an automatic conclusion — it is the result of flow color × inventory conditions."

Vanna + Charm same-direction is the necessary condition for the grind-up to hold. Tools:
- **Professional**: small size, delta-managed short straddle, active Δ-hedge, never naked.
- **Retail**: defined-risk iron fly / iron condor, explicit tail cap.

### Scenario C — Macro shock / risk-off

All six instruments turn red simultaneously (slide IMG_4626).

| Dim | Reading in shock |
|---|---|
| Vanna | IV↑ + spot↓ + dealer net short gamma → **sell-pressure self-reinforces (reflexivity)** |
| Charm | High-vol regime: vol-driven path overwhelms magnet → charm pin **nearly fails** |
| Skew | Full surface IV up; put wing rises faster; extreme regime = crash smile |
| Term Structure | Whole curve inverted, liquidity-type, systemic tension |
| Implied Move + Flow | Implied Move expands rapidly; Hedge Flow surges; whales lean short-side |
| VRP | Carry thermometer **flips negative**; sell-vol books bleed → forced unwind → reflexive |

**Actions**: ① NO sell-vol. ② NO bottom-fish until at least 2 dimensions stabilize. ③ Long tail finally pays — this is the only regime where chronic tail-hedge carry cost is recovered.

---

## 4. Position translation (5 steps)

From decision to ticket size:

| Step | Lever | Inputs |
|---|---|---|
| 01 | Strike selection | ATM vs OTM × IV level + skew + personal risk preference |
| 02 | Expiry selection | Weekly vs monthly vs LEAPS — term-structure shape determines value |
| 03 | Hedge budget | Tail hedge carries long-term cost; pays only at key moments — sized accordingly |
| 04 | Market-state weapon kit | low-vol / high-vol / event-driven / shock — four states, four tool combos |
| 05 | Review + psychology | Anchoring · sunk cost · revenge trade — psychological traps kill more than math errors |

---

## 5. Five single-dimension misreadings (why one dimension is never enough)

Each appears reasonable in isolation but has a documented exception that the matrix is designed to catch:

| # | Single-dim inference | Exception |
|---|---|---|
| 01 | "IV high → sell vol" | Maybe event-type high IV; after vol crush you earn less than expected |
| 02 | "OTM put expensive → short-vol candidate" | Skew may steepen further; the more expensive it gets, the more vulnerable to tail blow-up |
| 03 | "Term backwardation → crisis" | May be single-stock earnings (event-type); index back-month still in contango |
| 04 | "Implied Move high → ST vol over-priced" | True realized move may exceed implied; benchmark against historical same-event distribution |
| 05 | "Thick VRP → guaranteed sell-vol carry" | VRP is a decades-long mean; specific years can flip negative |

Each misreading is dissected with literature in the per-dimension docs.

---

## 6. Four philosophical takeaways

From slide IMG_4630 ("把六维哲学浓缩成几句话" — "compressing the 6-dim philosophy into a few sentences"):

1. **Options is not retail-vs-retail.** It is long-term *sell-insurance* vs long-term *buy-insurance*. **VRP is the long-term average premium of that insurance.**
2. **Single dimension long-term easily lies.** Six dimensions together make lying difficult — but not impossible. **True risk management = NO-TRADE when six conflict.**
3. **Options doesn't predict the future.** It tells you what risks the market is currently *pricing*. Your job is to find pricing dislocations.
4. **The strongest options players don't see more than others — they're slower to be wrong.** The matrix pulls you out *before anchor* takes hold.

---

## 7. Cross-reference with current `uw_scan` setup (summary)

Full mapping with concrete file paths in [`08-implementation-gaps.md`](08-implementation-gaps.md).

| # | Dim | Current status | Headline gap |
|---|---|---|---|
| 1 | Vanna | ⚠️ DB only (`greeks_by_expiry_strike`, `exposures_by_expiry_strike`) | No API, no UI, no conditional-reading classifier |
| 2 | Charm | ⚠️ DB only | No API, no UI, no OPEX magnet detection |
| 3 | Skew | ✅ end-to-end (watchlist `SkewBlock`, stock-page SVG chart, `risk_reversal_skew_history`) | Acceleration detector; regime classification (smirk vs crash smile) |
| 4 | Term Structure | ✅ Volatility tab v2 surfaces curve | Four-state classifier (contango / event-back / liquidity-back / mixed) |
| 5 | Implied Move + Flow | ⚠️ Flow tab full; IM derived but **no historical-event-distribution benchmark**; flow footprints not classified | IM benchmarking; 4-class flow-footprint classifier |
| 6 | VRP | ✅ IV−RV proxy in Volatility tab | Strict VRP (IV_t vs subsequent t→t+30 RV) per Ep 9 framing; long-run regime classifier |

**Build-out priority** (justified in [`08-implementation-gaps.md`](08-implementation-gaps.md) and [`09-backtest-plan.md`](09-backtest-plan.md)):
1. **Vanna + Charm read paths** (the structural gap — these are the *only* dimensions with no API surface despite full DB coverage).
2. **Strict VRP** and **IM benchmarking** (small derivers on top of existing data).
3. **Four-state Term classifier** and **flow-footprint classifier** (logic on top of data we already serve).

---

## 8. Companion documents

| File | Contents |
|---|---|
| [`01-vanna.md`](01-vanna.md) | Vanna: definition · 4 conditional readings · dealer-hedging literature · misreadings · single-name caveats · UW mapping |
| [`02-charm.md`](02-charm.md) | Charm: definition · OPEX magnet · far-OTM Δ decay · pinning literature · UW mapping |
| [`03-skew.md`](03-skew.md) | Skew: 25Δ risk reversal · smirk baseline · steepening acceleration · literature · UW mapping |
| [`04-term-structure.md`](04-term-structure.md) | Term structure: 4 states · vol-crush prediction · VIX futures literature · UW mapping |
| [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) | IM (0.8× straddle/spot) · 4 flow footprints · microstructure literature · aggressor-side caveats |
| [`06-vrp.md`](06-vrp.md) | VRP: strict vs proxy · 3 sources · literature · long-run regime |
| [`07-limitations.md`](07-limitations.md) | Eight limitations validated against literature (incl. v1-specific per-dim credibility caveat) |
| [`08-implementation-gaps.md`](08-implementation-gaps.md) | Cross-reference with `uw_scan` — data / API / UI / derivations per dimension |
| [`09-backtest-plan.md`](09-backtest-plan.md) | Backtest proposals: universe · data · strategies per scenario · metrics · falsification |
