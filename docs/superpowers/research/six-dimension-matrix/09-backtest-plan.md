# 09 — Backtest Plan

> Concrete proposals for empirically validating the 6-dimension matrix. Designed to *falsify*, not just *confirm* — the framework's takeaway #02 ("six dimensions together make lying difficult — but not impossible") explicitly invites empirical testing.

This doc is structured around **falsification criteria first**: what observations would invalidate the matrix, before describing the strategies that test it.

---

## 1. Falsification criteria (what would invalidate the matrix)

Before any backtest, the answers to these questions are the framework's success/failure boundary:

| Claim | Falsifying observation |
|---|---|
| **All-6 consistent ⇒ tradeable edge** | If consistent-signal trades return *no better* than random (mean Sharpe < 0.3 with no statistical separation from 6-dim conflicting trades) → claim is false |
| **6-dim conflict ⇒ no-trade is the optimal rule** | If conflicting-signal trades have non-zero edge, "no-trade" is suboptimal |
| **Vanna+Charm same-direction is necessary for Scenario B grind-up** | If grind-up occurs at the same rate when V+C *disagree*, the joint condition is not necessary |
| **VRP > 0 ⇒ short-vol carries positively** | If high-VRP regimes have *lower* short-vol Sharpe than low-VRP regimes, the carry thesis fails |
| **Term-structure state distinguishes idiosyncratic from systemic** | If event-type and liquidity-type regimes have *similar* post-event behavior, the classifier is uninformative |
| **Decision tree's invalidation rule reduces drawdown** | If max drawdown is *worse* with invalidation than without, the rule's costs exceed benefits |

These criteria define **rejected at 95% confidence** boundaries. If any single claim fails, the framework — *as stated* — needs revision in that specific dimension.

---

## 2. Universe and scope

### Primary (Cockpit product universe)

Per the 2026-05-14 product decision, the Cockpit ships with this 4-ticker universe:

| Asset | Rationale | Data |
|---|---|---|
| **SPX** | European cash-settled, the academic literature's primary subject (Carr-Wu, BTZ, Bekaert-Hoerova) — clean alignment with citations | UW + massive OHLC |
| **SPY** | American ETF — the dealer-flow / vanna-charm regime where retail flow density makes the matrix mechanics observable | UW + massive |
| **QQQ** | Tech beta, distinct dealer dynamics, separate 0DTE concentration profile | UW + massive |
| **IWM** | Small-cap beta — broadens factor coverage; tests whether the matrix transfers across cap regimes | UW + massive |

### Out-of-scope for v1 (research extensions only)

| Asset | Why deferred |
|---|---|
| NDX (cash) | Largely redundant with QQQ for product purposes; could be added later as a European-settlement validation |
| RUT (cash) | Largely redundant with IWM; same reasoning |
| NQ / ES futures options | Different ecosystem (CME futures options); separate broker/data integration |
| Sector ETFs (XLF, XLE, XLK, SMH, XLV) | "Index-like" but with idiosyncratic single-name composition; valid stress-test but not product universe |
| Mega-cap single-names | Per Limitation #4, expected degradation; not in Cockpit scope |

The stress-test set (sector ETFs, mega-caps) remains valuable for **research** — see §6.6 for the single-name vs index degradation curve, gated behind §11 as a research extension — but does **not** appear in the v1 Cockpit UI.

### Effective independence of the 4-ticker universe

The 4 tickers are not 4 independent observations for statistical power purposes:

| Pair | Daily-return correlation (typical) | Independence |
|---|---|---|
| SPX ↔ SPY | ≈ 1.00 | Same exposure; effectively one observation |
| SPX ↔ QQQ | ≈ 0.90 | Highly correlated but distinct factor tilt |
| SPX ↔ IWM | ≈ 0.85 | Distinct size factor |
| QQQ ↔ IWM | ≈ 0.75 | Two factor tilts |

Effective independent sample count is closer to **2–3**, not 4. The SPY result should be read as **dealer-flow-regime confirmation** for SPX, not as an independent test. Power calculations and bootstrap-block sizes (§6.9) should be set accordingly.

---

## 3. Time period and regime split

### Training window
- **2018-01-01 → 2022-12-31** (5 years) for parameter calibration

### Out-of-sample window
- **2023-01-01 → 2025-12-31** (3 years) for performance evaluation

### Regime-stratified analysis
Split results by:

| Regime | Definition | Why |
|---|---|---|
| Calm | VIX < 18, no NBER recession | Default regime; matrix expected to work best |
| Elevated | 18 ≤ VIX ≤ 28 | Mid-state |
| Stress | VIX > 28 OR Term-structure liquidity-type backwardation | Per Limitation #2, expect matrix failure |
| Post-shock | First 60 days following stress regime exit | Recovery dynamics — different from calm |

**Strictly include**: Volmageddon (Feb 2018), COVID Q1 2020, 2022 inflation regime, 2023 banking stress (SVB), 2024–25 0DTE-heavy regime, regional banking stress events.

---

## 4. Data infrastructure required

| Data | Source | Status |
|---|---|---|
| Per-ticker IV / RV / Greeks per strike per expiry per date | UW (already integrated) | ✅ |
| OHLC / volume | massive (already integrated) | ✅ |
| Earnings calendar | needs FMP or similar | ❌ — required for IM event distribution |
| FOMC / CPI / OPEX calendar | manually curated or via FRED/ICE | ❌ — small static dataset |
| Historical OPEX dates | static | trivial |
| Settled strict VRP | needs `vrp_30d_settlements` table — see [`08-implementation-gaps.md`](08-implementation-gaps.md) §2.6 | ❌ |
| Matrix state snapshots | needs `matrix_state_snapshots` table | ❌ |

**Backtest blocker**: items 3, 5, 7, 8 must be built before the full backtest can run. See [`08-implementation-gaps.md`](08-implementation-gaps.md) §4 build sequence.

### Phase 0 — data-availability spike (completed 2026-05-15)

Spike ran on the live UW account via `scripts/uw_history_spike.py`. **Full result and decision options**: [`reviews/2026-05-15-uw-history-spike.md`](reviews/2026-05-15-uw-history-spike.md).

**Headline**: the 2018-2025 backtest as designed in §3 is **infeasible on the current UW subscription**. UW returns `403 historic_data_access_missing` on the per-strike greeks/exposures/spot-exposures endpoints across all probed years; the current tier only serves the **last 30 trading days** (earliest 2026-04-01).

| Endpoint | Coverage on current account | Backtestable? |
|---|---|---|
| `/api/stock/{T}/greeks` | 30 trading days | ❌ |
| `/api/stock/{T}/greek-exposure/strike-expiry` | 30 trading days | ❌ |
| `/api/stock/{T}/spot-exposures/expiry-strike` | 30 trading days | ❌ |
| `/api/stock/{T}/historical-risk-reversal-skew` | ~1 year (251 rows, requires far-dated expiry param) | ⚠️ partial — skew row of §0.1 only |

Term Structure, IV, RV, and flow endpoints have not been probed yet — see the followup-probes table in the spike result doc.

**§3 dates are no longer provisional — they are blocked.** The 2018-01-01 start cannot be achieved without (A) a UW subscription upgrade, (B) sourcing historical greeks externally (ORATS / Polygon / IVolatility / CBOE LiveVol), or (C) accumulating forward via the nightly worker (~12–24 months until enough live data exists).

The recommendation in the spike result doc is **C + D combination**: ship the Cockpit as display-only now, accumulate `matrix_state_snapshots` from day 1, run a skew-only Phase 0.5 validation in the meantime, and re-evaluate after 6 months of live snapshots whether the matrix shows enough forward-data promise to justify A or B.

**Phasing impact**: §9 Phase 1 backtest is materially deferred. The realistic substitute on the current account is "Phase 0.5 — skew-only validation" (1-year window, single-dimension), described in [`reviews/2026-05-15-uw-history-spike.md`](reviews/2026-05-15-uw-history-spike.md) §"Available options" row D.

---

## 5. Strategy candidates (one per scenario)

### Strategy 1 — "Consistent vol-down → defined-risk short straddle"

**Maps to**: Scenario A.1 (idiosyncratic event-driven)

**Entry**:
- 6-dim matrix all agree on vol-down (`consistency_label == "consistent_vol_down"`)
- Term-structure state = `event_back` (not `liquidity_back`)
- `implied_move_event_percentile` > 0.7 (IV at top-30% of historical event distribution)
- VRP proxy positive (carry available)
- Skew not accelerating
- 1–5 days before identifiable event (earnings / FOMC / CPI)

**Position** (must be **fully defined-risk** — capped on both sides):
- **Iron fly** (short ATM straddle + long OTM call wing + long OTM put wing) OR **iron condor** (short OTM strangle + long deeper-OTM wings)
- A bare "short ATM straddle + long OTM put" is **NOT** defined-risk — the call side remains uncapped. Always cap both sides explicitly.
- Size: 1% of capital per trade (max), where "capital at risk" = max defined loss of the structure (i.e. wing-width − net premium received)

**Exit / Invalidation** (decision tree Step 4):
- Term-structure flips to `liquidity_back` → close + buy long put immediately
- Skew accelerated steepening (`skew_25d_5d_change` > 2σ) → close
- VRP proxy crosses negative → close
- Flow color flips call-heavy → re-evaluate vanna conditional
- Event has passed and IV crushed > 50% → take profit

**Performance metric**: Sharpe, hit rate, mean P&L per trade, max single-trade loss, ratio of winning trades closed by event vs by invalidation.

### Strategy 2 — "Vanna + Charm consistent → grind-up bias"

**Maps to**: Scenario B (post-event vol crush)

**Entry**:
- Post-event window: 1–3 days after earnings / macro event
- `dealer_net_vanna_proxy` × `dealer_net_charm_proxy` > 0 (same sign)
- Prior 3-day flow color (`directional_imbalance_3d`) was put-heavy or call-heavy (not balanced)
- IV crushed > 30% from pre-event peak

**Position**:
- Small long SPX (or QQQ) cash position with options collar
- Or: short put + long call (synthetic long stock) with explicit tail cap

**Exit / Invalidation**:
- Vanna sign flips → close
- Charm regime breaks (high-vol state per `pin_regime_flag` = false) → close
- Term-structure enters liquidity backwardation → close + add tail hedge

**Performance metric**: directional Sharpe (long-only), comparison to S&P benchmark over same windows, attribution to the vanna+charm joint condition (via subsample of *single*-direction agreement).

### Strategy 3 — "All-red → long tail"

**Maps to**: Scenario C (macro shock / risk-off)

**Entry**:
- Matrix state shows 6/6 vol-up
- VRP proxy < 0 (negative carry)
- Term-structure state = `liquidity_back`
- Skew `crash_smile_flag` = TRUE

**Position**:
- Long deep OTM put (3-month, ~5% OTM)
- Or: long VIX call (1-month ATM)
- Size: 0.5% of capital (small — tail cost is high)

**Exit / Invalidation**:
- At least 2 of the 6 dimensions stabilize → take profit (the framework's "等至少两维 stabilize")
- VRP returns positive → close
- 90 days elapsed without resolution → close (the tail cost is paid; the option has decayed)

**Performance metric**: Tail-CAGR contribution to a broader portfolio; ratio of payoff (winners) to premium spent (losers); Sortino ratio.

### Strategy 4 — "Decision tree compliance"

**Maps to**: Step 1 + Step 4 of the decision tree (consistency + invalidation)

**Mechanism**: Run any strategy with and without the consistency check and invalidation rules. Compare:
- Sharpe with vs without consistency check
- Max drawdown with vs without invalidation
- Sharpe degradation × fewer-trades trade-off

If consistency-check trades have higher Sharpe with *fewer* trades, the rule is value-additive. If invalidation reduces max drawdown without sacrificing Sharpe, the rule is dominant. This **isolates the decision-tree contribution** from the dimensional alpha.

---

## 6. Robustness tests

### 6.1 Look-ahead bias check
All matrix dimensions must be computable using *only* data available as of `t` — no use of subsequent realized vol or future OHLC. Strict VRP at `t` must use `IV_30d(t−30)` vs `RV(t−30 → t)`, *not* `IV_30d(t)` vs `RV(t → t+30)`.

### 6.2 Survivorship bias
For the v1 Cockpit universe (SPX/SPY/QQQ/IWM) survivorship is not a concern — all four tickers continuously exist over the backtest window. **Single-name extensions (deferred — see §11)** must include delisted tickers (e.g. SIVB) with proper exit dates; the matrix's tail-hedge predictions are only meaningful if delisting scenarios are present.

### 6.3 Aggressor classification noise floor
Per Limitation #5: simulate flow-footprint labels with the Savickas-Wilson error rates injected (17% mislabel for liquid, 30% for illiquid). Measure strategy Sharpe degradation. If Sharpe collapses entirely under realistic noise, the flow dimension is over-credited in the matrix.

### 6.4 Stress-regime exclusion test
Run all four strategies *with* and *without* stress periods (Limitation #2 regime). The expected pattern:
- Strategies 1 (short-vol) and 2 (grind-up): substantially worse during stress (matrix fails)
- Strategy 3 (long-tail): substantially better during stress
- Strategy 4 (decision-tree compliance): much smaller drawdown during stress

If strategies 1/2 perform *well* during stress, the matrix doesn't add value (any vol-down signal works); if strategy 3 doesn't pay off in stress, the tail-hedge thesis fails.

### 6.5 0DTE-regime stratification — **highest-priority robustness test**
Per Limitation #7 and the verified 2025 0DTE shares (SPX 59% / SPY 45% / NDX up to 78% / IWM not separately disclosed): split results by year cohort to isolate the 0DTE-heavy regime (2023+) **AND** by per-ticker 0DTE-share band:

| Cohort | Definition | Expected behavior |
|---|---|---|
| Pre-0DTE | 2018–2021 (no SPX M/W/F daily expiries until 2022-04; ETF dailies came later) | Framework's home turf — short-vol Strategy 1 should produce the cleanest Sharpe |
| Transition | 2022 — daily expiries roll out | Matrix expected to work but with weaker effect sizes |
| 0DTE-dominant | 2023 → present (SPX 0DTE > 40%, climbing to 59% FY 2025) | **Stress test for the entire framework** — Limitation #7 explicitly says the matrix may not work here |

Additionally, compute Strategy 1 Sharpe stratified by trailing-30-day 0DTE share **per ticker**, since SPY 0DTE share (~45%) and SPX (~59%) differ materially. The hypothesis from Limitation #7 — "matrix breaks down somewhere between 20% and 40% 0DTE share" — is now testable with confidence intervals around the empirical decision boundary.

**Pass criterion for shipping**: Strategy 1 Sharpe in the 0DTE-dominant cohort must not be statistically distinguishable from zero (at 5% level after deflated-Sharpe adjustment per §6.9) for "matrix still adds value." If Strategy 1 Sharpe is reliably negative in this cohort, the framework as designed cannot run on its own primary universe — the Cockpit ships as a *display* (no trading recommendation; see §0.4 fail-state rule for criterion 1 in [`00-overview.md`](00-overview.md)).

### 6.6 Single-name vs index degradation curve — **research extension only (deferred, see §11)**
This test is **not** part of v1 backtest, which is indexes-only (§2). It is documented here so the methodology is ready if/when a single-name extension is approved:

> For a single-name backtest: compute per-ticker Sharpe and plot against (a) average daily option volume, (b) OI density at ATM, (c) average bid-ask spread. The expected pattern: Sharpe falls monotonically with each illiquidity dimension. If single-name results are independent of liquidity, the matrix is somehow universal — surprising; investigate.

### 6.7 Dimensional collinearity stress test
Per Limitation #1: compute the *correlation matrix* of the 6 dimension signals at the start of every "consistent" trade. If correlation among Skew/VRP/Term/Move is > 0.7 (highly collinear), then a "6-dim consistent" reading is closer to "4-dim consistent" — re-grade Strategies 1/2 with that adjusted denominator.

### 6.8 Execution realism — critical for short-vol claims

A theoretical-fill backtest will materially overstate short-vol performance. Must model:

| Component | Concrete assumption | Source |
|---|---|---|
| Option bid-ask spread | Use the actual half-spread at fill time; for entry, assume 70% fill at mid (not 100%) | UW best-bid/best-ask if available; otherwise CBOE TOPS |
| Slippage | For multi-leg structures (iron fly/condor): leg-by-leg slippage compounds — typically +5–15bp of premium per side | empirical; see Jiang/Tian (2010) on options market quality |
| Assignment / exercise | Short ITM options assigned by expiry; backtest must close at expiry, not hold past | standard |
| Margin | Maintenance margin scales with vol; backtest may need to mark to market and reduce size if margin pressure rises | broker-specific |
| Borrow / financing | Short-stock leg of short-vol structures (rare for index options) costs SOFR + borrow fee | trivial for SPX |
| VIX option / future availability | VIX options expire on specific Wednesdays; VX futures roll monthly with calendar-spread cost | CBOE settlement docs |

Without execution-realistic costs, Strategy 1 (short-vol) Sharpe will be inflated by ≥0.2 — material at the threshold for "edge confirmed."

### 6.9 Multiple-testing / publication-bias controls

Per the falsification standard, plain bootstrap is not sufficient when the matrix runs many simultaneous hypotheses. Add:

- **White's Reality Check** (White 2000, *Econometrica*) or **Hansen's SPA** (Hansen 2005, *JBES*) — controls family-wise error rate when comparing multiple strategy variants
- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014, *Journal of Portfolio Management*) — corrects Sharpe for selection bias and non-normality
- **Stationary / block bootstrap** (Politis & Romano 1994) with block-size chosen by automatic methods — preserves serial correlation in the returns series, especially around event clusters

Drop the simple "5th percentile bootstrapped Sharpe > 0" criterion in favor of these. The matrix's "6-dim consistent" filter implicitly tests millions of joint signals; nominal p-values will lie.

---

## 7. Performance metrics suite

For each strategy:

| Metric | Definition | Threshold for "edge confirmed" |
|---|---|---|
| Sharpe ratio (annualized) | mean(daily P&L) / std(daily P&L) × √252 | > 1.0 |
| Sortino ratio | mean / downside-std | > 1.5 |
| Max drawdown | |min peak-to-trough| | < 20% |
| Hit rate | wins / total trades | > 50% |
| Profit factor | sum(wins) / |sum(losses)| | > 1.5 |
| Mean trade P&L (% of capital) | mean per-trade return | > 0.3% / trade |
| Tail loss | 5th percentile single-trade P&L | > −5% |
| Trade count | total trades in 3y OOS | > 50 (statistical power) |

**Statistical significance**: bootstrap 1000× by sampling trade-blocks (preserves serial correlation). Reject null only if 5th percentile of bootstrapped Sharpes > 0.

---

## 8. Comparison to passive benchmarks

| Benchmark | Why |
|---|---|
| Hold cash + roll 1m VX futures short | Naive VRP harvester |
| Buy-write SPX (BXM index) | Naive systematic short-vol |
| Long SPX | Baseline |
| Tail Risk Parity (e.g. CBOE PPUT) | Naive long-tail |
| Random matrix readings | Direct falsification — matrix signals should outperform random labels |

**Critical comparison**: Strategy 1 (matrix-consistent short-vol) vs naive buy-write (BXM). If matrix-consistent does not outperform BXM net of transaction cost, the dimensional analysis is not delivering alpha — only the underlying VRP harvest is.

---

## 9. Phasing — minimum viable backtest

Mapped to the 15-item Cockpit build sequence in [`08-implementation-gaps.md`](08-implementation-gaps.md) §4. The MVB runs after Phase 1 of that sequence.

### Phase-1 backtest (after `08 §4` items 1–7 — vanna+charm reads, IM deriver, term classifier, skew acceleration, strict VRP, event distribution, universe gate)

Data + derivations complete; no UI required. Runnable from notebooks against the warm store.

- Strategy 1 (short-vol on consistent vol-down)
- Strategy 3 (tail-hedge on all-red)
- Strategy 4 (decision-tree compliance test)
- **Falsification criteria 1, 4, 5, 6** testable (consistency edge, VRP carry, term-state classifier, decision-tree invalidation)

### Phase-2 backtest (after items 8–10 — `cockpit_matrix.py` assembler, `/cockpit` routers, 5 tab components)

UI is live but classifiers are not yet wired into the joint condition.

- Strategy 2 (Vanna+Charm grind-up) is **still partial** — runs against `dealer_net_vanna/charm_proxy` sign, but the full conditional reading (Vanna 4-rule + Charm pin classifier) is still pending until items 11–12.
- No new falsification criteria gated by this phase (the gating bottleneck is the classifiers in Phase 3).

### Phase-3 backtest (after items 11–13 — vanna conditional, charm pin, flow footprint)

- Full Strategy 2 with the joint Vanna+Charm conditional reading
- **Falsification criterion 3** (Vanna+Charm same-direction necessary for grind-up) testable
- **Falsification criterion 2** (6-dim conflict ⇒ no-trade optimal) testable end-to-end
- All 6 falsification criteria now have data
- The optional Cockpit AI (item 14) only affects the *delivery* of insights, not the falsification answer — runs anytime after item 14 lands

### Out-of-scope for backtest phasing
- Single-name degradation curve (§6.6) — research extension, §11
- Bekaert-Hoerova VRP decomposition (`08 §4` item 15) — research extension

---

## 10. Open research questions

These are explicit research outputs from the backtest — not foregone conclusions:

1. **Is the 0.8 IM coefficient empirically optimal?** Brenner-Subrahmanyam gives `√(2/π) ≈ 0.7979` theoretically. Many practitioners use 0.85. What does the actual realized-vs-implied ratio look like across the SPX 2018–2025 sample, stratified by event type?

2. **Does Vanna+Charm joint sign actually predict grind-up?** Hypothesis from [`01-vanna.md`](01-vanna.md) §2 and [`02-charm.md`](02-charm.md). Test with logistic regression: P(positive next-5d return) ~ vanna_sign × charm_sign × IV_crush_magnitude.

3. **What's the half-life of strict VRP signals?** Bollerslev-Tauchen-Zhou claim quarterly horizon. Verify with the post-2018 sample.

4. **Does the matrix-state's "consistency_label" provide more information than the marginal-distribution of each dimension's signal?** Equivalent to testing whether the *joint* signal has predictive power beyond what each dimension contributes independently. Information-theoretic test: I(return; matrix_state) vs Σ I(return; dim_i).

5. **At what 0DTE-volume threshold does the matrix break down?** Compute Strategy 1 Sharpe stratified by trailing-30-day 0DTE share. Look for an inflection — likely between 20% and 40% 0DTE share.

6. **How much of the matrix's gains come from blocking bad trades vs picking good ones?** Strategy 4 isolates this. If most of the edge is in blocking, the framework is fundamentally a **risk-management** tool, not an alpha-generation tool — consistent with takeaway #02.

### Deferred to §11 (research extensions, not v1 questions)
- **How much of the matrix's edge survives single-name application?** Per-ticker Sharpe and the liquidity-degradation slope. Out of v1 scope per Limitation #4 and the Cockpit indexes-only product decision.

---

## 11. Research extensions (post-v1, indexes-only does not apply)

These are explicitly deferred from the v1 Cockpit backtest. They are documented here so the methodology is preserved for later approval:

| Extension | What it is | Why deferred from v1 |
|---|---|---|
| Single-name application (§6.6, §10 Q "single-name") | Per-ticker Sharpe vs liquidity dimensions; mega-cap + sector-ETF stress test | Limitation #4 (index-pricing-pressure phenomena); product universe is indexes-only |
| Bekaert-Hoerova VRP decomposition (`08 §4` item 15) | Split VIX² into conditional variance + premium; test each independently | Refines but does not change v1 falsification answers |
| NDX/RUT (European cash) | European-settlement validation of QQQ/IWM results | Largely redundant with QQQ/IWM for v1; expand if v1 backtest passes |
| Futures options (NQ/ES) | CME-settled options pricing universe | Separate broker/data integration |

Extensions are gated behind v1 falsification results: an extension is built only if it changes an answer that v1 leaves ambiguous, not just to add a result.

## 12. Cross-references

- Decision tree (Steps 1 + 4 are the operational subject of Strategy 4) — [`00-overview.md`](00-overview.md)
- Three canonical scenarios → three baseline strategies — [`00-overview.md`](00-overview.md)
- Per-dimension derived metrics needed for backtest — `01-vanna.md` through `06-vrp.md` §7
- Limitations 2, 4, 5, 7 are explicit boundary conditions tested in §6 — [`07-limitations.md`](07-limitations.md)
- Implementation gap build sequence — [`08-implementation-gaps.md`](08-implementation-gaps.md) §4
