# 10 — Open Research Questions

A backlog of questions surfaced during the cross-validation work that remain unresolved. Status tracked per question. **Resolve before implementation only if marked critical.**

---

## Critical (must resolve before spec finalization)

### Q1. Where do we draw the operational line between "framework operative" and "framework suspended"?

The post-2022 regime break finding suggests gating the article's framework (Layer 2) on a rolling Gold ↔ DFII10 correlation gauge. But what specific threshold?
- 252-day rolling correlation in `[-0.9, -0.5]` → operative
- in `[-0.5, -0.2]` → partial
- in `[-0.2, +0.2]` → suspended

These bounds are intuitive but not derived from a test. **Resolution path:** Compute the rolling correlation time series ourselves, look at the distribution, and pick thresholds based on observed regime persistence rather than guesses.

**Status:** open · **Owner:** unassigned

---

### Q2. Does the dashboard show the article's framework anyway when suspended?

Even in suspended mode, the article's three signals (CPI YoY, T5YIFR, DFII10 60d change) and regime classification remain interesting — they tell you what gold *would* be doing if the structural-flow buyer weren't dominant. But surfacing the A position recommendation when the gauge says "suspended" is misleading.

**Tentative answer:** show the framework's outputs ("if this regime were operative, A would size to X"), but explicitly grey out the recommended action and replace with a "framework suspended — see Layer 1" note.

**Status:** open · **Owner:** UX decision

---

### Q3. What's our gold price reference?

GLD ETF (already wired via massive.com), GC=F front-month futures, or LBMA AM/PM fix. They diverge by basis (futures), tracking error (GLD), and timing (LBMA fix is once-daily, GLD is intraday).

- **GLD pros:** already wired, intraday, single source
- **GC=F pros:** purer spot signal, no ETF tracking error
- **LBMA fix pros:** academic standard, used by Erb-Harvey

**Tentative answer:** GLD as primary (cheapest path), surface LBMA fix in a side panel for academic reference. Use GC=F only if we add a futures-positioning page later.

**Status:** open

---

## Important (resolve during spec / early implementation)

### Q4. Is the post-2022 break a permanent regime or a phase of a longer cycle?

Two more years of data would clarify. **For now, the prudent assumption is permanence.** But the dashboard should expose the regime gauge so users can detect reactivation themselves.

**Status:** open · **Action:** add the rolling Gold ↔ DFII10 correlation as a top-level chart

---

### Q5. What's the best "valuation overlay" signal — real price percentile or gold/M2 ratio?

Erb-Harvey use **real price of gold** (CPI-deflated, USD-denominated). Some practitioners use **gold/M2 ratio** (deflates by money supply rather than CPI). Different signals can give different mean-reversion reads.

**Resolution path:** compute both, look at correlation, pick the one with cleaner mean-reversion behavior. Likely both should be surfaced.

**Status:** open

---

### Q6. F10 IC anomaly — actually replicate it?

viviennaBTC reports F10 (TIPS-BEI Spread) IC at +0.73. This is implausibly high for any macro factor. We should attempt to replicate the calculation with multiple specifications (Pearson vs Spearman, levels vs returns, in-sample vs walk-forward) to understand where the 0.73 comes from and what the IC actually is under standard methodology.

**Status:** open · **Action:** compute as part of the empirical-claims validation pass

---

### Q7. How do we handle China's underreporting of gold reserves?

The PBoC reports official gold holdings periodically but is widely believed to under-report. Industry estimates suggest actual holdings are 2-3× reported. Do we:
- Use only reported (clean, biased low)?
- Use industry estimates (less clean, more accurate)?
- Show both and let the user decide?

**Tentative answer:** show reported as primary, surface industry estimates in a tooltip.

**Status:** open

---

### Q8. What's the right cadence for the dashboard?

- Daily updates for FRED + ETF + COMEX + LBMA-when-available + FX
- Monthly updates for CB reserves + LBMA + GPR-monthly
- Quarterly updates for WGC demand trends

Mixed-cadence visualization is non-trivial. **Tentative answer:** all daily data on the main panel; monthly/quarterly in a "structural" tab with explicit "last updated" badges.

**Status:** open · **Action:** UX prototype

---

## Useful but not blocking

### Q9. What does our UW options data add that no macro model has?

GLD dealer gamma, vol skew, large-trade flow on the gold complex (GLD/GDX/IAU) are not in any academic gold model we've found. This is potential research-paper-grade content but is not load-bearing for v1.

**Status:** open · **Action:** add as a v2 research item

---

### Q10. SGE physical inventory — worth the scraping cost?

Shanghai Gold Exchange physical delivery data is the cleanest signal of Chinese physical demand. But it's only published in Chinese and requires browser scraping. Engineering cost is moderate; signal value is high but uncertain because Chinese demand is already partially captured by per-country CB reserves and XAU/CNY.

**Tentative answer:** defer to v2. v1 covers most of the signal via CB reserves + XAU/CNY.

**Status:** open

---

### Q11. Backtest harness — when and how?

The natural next step after the regime-aware model ships is a walk-forward backtest of the A/B position recommendations against actual gold returns. This requires:
- Proper purged k-fold or expanding-window CV
- Point-in-time data (CPI revisions, especially)
- Transaction cost assumptions
- Multiple decision rules (Kelly-lite vs fixed vs vol-targeting)

This is a meaningful project (~2-4 weeks). Not v1.

**Status:** open · **Action:** queue as a separate spec after v1 ships

---

### Q12. Should we model the gold-BTC relationship?

The source article discusses BTC as "digital gold" and concludes (correctly, per the data) that BTC has not behaved as a safe haven. But the discussion is theoretical. Do we add BTC as a competing-asset overlay?

**Tentative answer:** defer. The four-asset board (Gold/USD/BTC/SPX) is a separate sub-project.

**Status:** open

---

### Q13. Option A, B, or A-prime?

The most important open decision. Determines v1 scope.

- **Option A:** Ship layered research dashboard in ~5-7 weeks. No backtest harness, no walk-forward CV, no online evaluation, **no audit scaffold**. Then commit to full quant model in ~6-10 more weeks. Total ~11-17 weeks with interim deliverable.
- **Option B:** Build full backtest harness alongside data pipeline. Single ~12-18 week deliverable. No interim.
- **Option A-prime (Codex-recommended):** Three phases.
  - Phase A1 (~5-7 weeks): research cockpit + data pipeline + **minimal replay/audit scaffold** (persist raw input snapshots, as-of timestamps, transformed factors, regime labels, posture rows to Postgres). No ML model. Deterministic historical playback for the correlation gauge and structural posture.
  - Phase A2 (~2-3 weeks): model readiness pass — PIT lag validation, internal correlation-break replication, threshold calibration, COT/options inclusion decision, benchmark definitions, target-definition lock-in.
  - Phase A3 (~6-10 weeks): full quant model + walk-forward harness, *only after* Phase A1/A2.
  - Total: ~13-20 weeks across three phases.

**Recommendation (revised after Codex review):** Option A-prime. Option A risks shipping a research cockpit that traps us into a parallel quant build later because the data path isn't time-travel-disciplined. Option B risks 3-4 months of hidden work around the wrong product shape. A-prime preserves the interim deliverable AND keeps the eventual quant model achievable from the cockpit's persistence layer.

**Status:** open · **Decision owner:** user

---

### Q14. Model class sequence and validation hurdles

Per [04a-quant-model-spec.md](./04a-quant-model-spec.md), the model class is earned, not chosen. The sequence (revised per Codex review) is:

1. **v1** Lasso linear with regime × factor interactions
2. **v2** State-space / Markov-switching regression or hierarchical Bayesian (moved earlier than trees because the research thesis is regime-switching, not nonlinear interactions)
3. **v3 (challenger)** XGBoost / LightGBM, only if v1/v2 leave clear nonlinear residual structure
4. **v4** Partial-pooling across precious metals (NOT a literal 4×N sample-size multiplier — partial information sharing only)

**Open hurdle calibration:** the original "+0.2 Sharpe to advance" and "+0.1 for v3" were under-specified per the Codex review. The right hurdle is **statistically significant improvement on a multi-metric validation basket** (deflated Sharpe, PBO, regime-conditional, benchmark-relative) after multiple-testing correction, not a single Sharpe delta.

**Status:** open · **Action:** lock validation basket definition in Phase A2

---

### Q15. Partial-pooling target selection (v4 only)

For the v4 partial-pooling expansion, which targets? Note: per the Codex review, this is **partial information sharing**, NOT a literal 4× sample-size multiplier. The previous framing was wrong.

Candidates and their issues:

- **Gold-only** (no pooling) — preserves v3 baseline
- **Gold + silver** — closest substitute, ~30+ years history, but silver has industrial-demand component that gold doesn't
- **Gold + IAU** — IAU is nearly a duplicate of GLD; pooling adds little information
- **Gold + GDX** — GDX is a miner-equity basket carrying equity beta, energy/labor/cost-curve exposure, and management risk; pooling introduces target heterogeneity
- **Gold + silver + GDX + IAU** — full complex, but most heterogeneity
- **Gold + silver + platinum + palladium** — different industrial drivers; probably too heterogeneous

**Tentative:** Gold + silver as the cleanest pair. GDX deferred to a separate miners-focused study, not a precious-metals-target pool.

**Status:** open · **Action:** evaluate empirically when v4 is reached. Treat pooled performance gains on silver as separate accounting from gold-target gains.

---

### Q16. Single-horizon or multi-horizon in v1?

viviennaBTC ensembles 10d/20d/40d horizons. v1 simplification could pick one (20d typical) and add ensemble in v2.

**Tentative:** start single-horizon (20d) for v1 simplicity, add multi-horizon in v2 along with the tree-based upgrade.

**Status:** open

---

### Q17. Kelly fraction default

⅓ Kelly is standard for risk-averse practitioners. ½ Kelly is more aggressive but increases drawdown materially. Full Kelly is mathematically optimal under perfect parameter knowledge but catastrophic in practice.

**Tentative:** ⅓ Kelly default, exposed as configurable parameter.

**Status:** open

---

### Q18. Embargo length for walk-forward CV

Original draft was internally inconsistent (5 days in one section, 10 days in another). Per the Codex review, the embargo must scale with forward-return horizon AND with measured residual serial dependence — a fixed default is wrong.

**Revised tentative:** embargo = max(10, 0.25 × horizon) trading days, then tuned empirically against measured residual autocorrelation in Phase A3. For 40-day forward returns this floors at 10 days but can extend further if residuals demand.

**Status:** open · superseded the previous fixed-default suggestion

---

### Q19. Position-sizing combination rule (v2+ only)

v1 ships no numerical positions. When v2 sizing is introduced:

```
total = cyclical_size + strategic_allocation_context + event_hedge_context
```

The "B position" was previously monolithic; per the Codex review it has been split into *strategic allocation context* (long-horizon) and *event hedge context* (Baur-Lucey 15-day). Composition rule for v2+ is open:

- Additive with per-component caps (current default)
- Weighted average (constrained to sum=1)
- Max(A, B) — conservative
- Multiplicative composition

Crucially, composition must include **variance accounting** between Lens 1 and Lens 2 inputs — they share variance, so naive addition double-counts macro shocks. See Q23 below.

**Status:** open

---

### Q20. Internal replication of the post-2022 correlation collapse

The RBC-reported -0.84 → -0.07 Gold ↔ DFII10 correlation collapse has not been internally replicated. Per the Codex review, the magnitude could be exaggerated by window endpoints, level-vs-return choices, or pre-2022 non-stationarity. The dashboard should not quote the RBC numbers as our measured truth.

**Required before any production claim of the magnitude:**

1. Compute Gold ↔ DFII10 correlation across levels AND returns
2. Use rolling windows 60d / 126d / 252d / 504d, plus expanding
3. Cross-validate across gold inputs: spot, GLD, LBMA AM fix, GC=F
4. Cross-validate TIPS inputs: DFII10 level vs DFII10 daily change
5. Run at least one structural-break test (Bai-Perron, Quandt-Andrews, or rolling Chow)
6. Compare against a non-stationarity null (was pre-2022 one stable regime or one long non-stationary environment?)

Publish results in [02-empirical-claims-validation.md](./02-empirical-claims-validation.md) and update [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) with our measurement.

**Status:** open · **Critical** — gates any production quoting of correlation-gauge thresholds

---

### Q21. CV fold count and embargo scaling

Original draft fixed 5-fold expanding-window CV with a 5- or 10-day embargo (the two were inconsistent across sections). Per the Codex review the embargo must scale with the forward-return horizon and the training-window scheme should be tested, not assumed.

Tests to run:

- 5-fold vs 10-fold (latency/robustness trade-off)
- Expanding vs rolling 5y vs rolling 8y vs regime-weighted training
- Embargo = max(10, 0.25 × horizon) vs alternative scaling rules
- Measure post-fit residual autocorrelation and tune embargo against it

**Tentative defaults:** 5-fold, horizon-scaled embargo with floor of 10 days. Final values empirical.

**Status:** open · **Action:** part of Phase A3 backtest harness

---

### Q22. Should Lens 3 ever be a sizing input?

Currently Lens 3 is exclusively a tail-risk overlay per [07-valuation-overlay.md](./07-valuation-overlay.md). The Codex review confirmed this. An earlier draft of [04a-quant-model-spec.md](./04a-quant-model-spec.md) proposed valuation-conditional vol-scaling as a sizing multiplier; that contradicted 07 and was wrong.

**Open question:** if a future backtest shows that valuation-conditional sizing (e.g., reduce position when real-price percentile > 75) improves out-of-sample Sharpe by a statistically significant margin AND doesn't worsen drawdown or turnover, then valuation could become a sizing input — but only with backtest validation, not by default.

**Status:** open · **Action:** test in Phase A3 backtest harness; do not pre-commit

---

### Q23. Lens shared-variance accounting

The three lenses share variance: CB buying overlaps with GPR/DXY/TIPS; ETF flows overlap with real-rate transmission; valuation is endogenous to Lens 1 flow. Per the Codex review, treating the lenses as orthogonal in v2+ sizing is dangerous because it double-counts the same macro shock.

**Required for v2+ sizing composition:**

- Correlation matrix between all lens inputs (and inputs within each lens)
- Hierarchical clustering and VIF among inputs
- PCA / partial residuals to estimate independent-component count
- Regime-conditional feature importance (the variance sharing may differ pre-2022 vs post-2022)

Position sizing should assume correlated signals until variance accounting proves otherwise.

**Status:** open · **Critical** for any v2+ sizing logic

---

### Q24. Article-zone threshold calibration (CPI, T5YIFR)

Currently the article zones use CPI bands of 2% / 4% and T5YIFR bands of 2.5% / 2.7% / 2.8%. These are article-derived heuristics, **not empirically calibrated**.

**Calibration plan:**

- Derive thresholds from the historical T5YIFR and CPI YoY distributions (e.g., quartile-based)
- Compare the article zones against a multi-indicator anchoring basket (T5YIFR, T10YIE, SPF long-run expectations, Michigan long-run expectations, Fed CIE index)
- Use rolling structural-break detection to find natural breakpoints in the inflation regime
- Compare event labels under article zones vs empirically-calibrated zones

**Status:** open · gates production use of zone labels (especially "unanchored")

---

### Q25. Multi-horizon labels: ensemble or per-horizon?

Original draft committed to a 10d/20d/40d ensemble per viviennaBTC. Per the Codex review, multi-horizon labels are highly correlated by construction (overlap), and ensembling can mask which horizon is actually informative.

**Required:** report each horizon separately with its own validation pass *before* any ensembling decision. Single-horizon survivability is the gate; ensembling is an optimization on top.

**Status:** open · **Action:** part of Phase A3 backtest harness

---

### Q26. Target definition: GLD, GC=F, or LBMA fix?

GLD returns, spot gold returns, LBMA AM/PM fix returns, and GC=F front-month returns are not interchangeable once costs, tracking error, and close times matter. Per the Codex review, the backtest must fix a single target per run and document the choice transparently.

**Tentative:** GLD as primary target (cheapest data path, matches eventual execution vehicle); report LBMA fix as a side panel for academic comparison; reserve GC=F for any futures-positioning v2 extension.

**Status:** open · **Action:** lock in during Phase A2 model-readiness pass

---

### Q27. Feature-selection leakage discipline

viviennaBTC's 8-factor list and the "survivor" factors emerged after looking at the same historical period we now want to backtest. Per the Codex review, the backtest must distinguish pre-registered factors from discovered factors, and discovered factors get held-out validation only.

**Plan:**

- Pre-register F1-F21 (current spec) as the fixed factor set at the start of any backtest run
- Any factor discovered or added later must be marked with a discovery date
- Discovered factors cannot enter the in-sample window of any walk-forward run that crosses their discovery date
- The backtest report must clearly label which results come from pre-registered vs discovered factors

**Status:** open · **Critical** for backtest credibility

---

### Q28. Turnover and capacity reporting

Per the Codex review, a high-Sharpe signal with constant churn is fake for this product unless costs and execution rules are explicit.

**Required reporting (Phase A3):**

- Average daily turnover (% of position rotated per day)
- Annualized turnover
- Maximum position size as % of GLD average daily volume
- Net-of-cost Sharpe at multiple cost assumptions (5 bps, 10 bps, 15 bps round-trip)

**Status:** open · **Action:** part of Phase A3 backtest harness

---

### Q29. Benchmark comparison panel definitions

Per the Codex review, a model that fails to beat simple benchmarks is not a quant win regardless of its absolute Sharpe. Required benchmarks for the validation basket:

- Buy-and-hold GLD
- Vol-targeted GLD (10% annualized target)
- 12-month price trend / momentum rule
- Real-yield-only signal (DFII10 change, no other inputs)
- No-trade (cash) — establishes whether the model adds anything at all

**Status:** open · **Action:** lock in benchmark definitions during Phase A2

---

## Resolved (kept for traceability)

### R1. Are the article's references real?

**Resolution:** Yes. All five cited papers exist and are correctly attributed. See [01-references-and-citations.md](./01-references-and-citations.md).

### R2. Is FRED data free?

**Resolution:** Yes. CSV endpoint is no-auth; JSON API requires a free instant-issue key. No paid tier exists. See [09-data-sources-catalog.md](./09-data-sources-catalog.md).

### R3. Is GVZ on FRED?

**Resolution:** Yes, as `GVZCLS`. Daily, free, no need to scrape CBOE directly.

### R4. Does the article omit anything material?

**Resolution:** Yes. Three omissions: (1) the post-2022 regime break, (2) Erb-Harvey's real-price mean-reversion finding, (3) Baur-Lucey's 15-trading-day safe-haven duration. All three are material to implementation. See [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) and [07-valuation-overlay.md](./07-valuation-overlay.md).

### R5. Should we use XGBoost?

**Resolution (revised again 2026-05-16 post-Codex):** Trees are a **challenger, not the roadmap**. The model sequence is: linear baseline (v1) → state-space / Markov-switching (v2) → XGBoost / LightGBM challenger (v3, only if v1/v2 leave clear nonlinear residual structure) → partial-pooling across precious metals (v4, treated as information sharing, not literal N multiplication). The first revision of R5 was correct that XGBoost is on the menu; it was wrong about *when*. State-space comes before trees because the research thesis is *regime switching in the pricing kernel*, which a regime-switching model captures directly while a tree only approximates. See [04a-quant-model-spec.md](./04a-quant-model-spec.md) for the full updated sequence and validation basket.

### R6. Can we replicate viviennaBTC's 8 factors?

**Resolution:** Yes, all 8. F1 (DXY), F4 (BEI), F5 (GPR), F6 (GVZ), F10 (TIPS-BEI Spread), F11 (DXY momentum), F13 (Gold-GDX divergence), F14 (GVZ momentum). One new FRED client + one GPR CSV ingestor + computed transforms. Zero new external data cost.
