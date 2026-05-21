# 07 — Notebook scope and data audit

**Status:** scoping doc, not code. Answers two questions:
1. What is the minimum-viable notebook that delivers the "RV−IV redundancy audit" value implied by Goyal-Saretto for our codebase?
2. Is the data in `option_wizard` Postgres sufficient to run it?

**Read also:** doc 00 (goal), doc 10 (data-access contract — this notebook consumes it), doc 13 (backtest design — this notebook is the V1 deliverable of the L1 backtester).

## 0. Three-layer data verdict (updated 2026-05-20)

The data sufficiency question depends on which experiment you mean. Three layers:

| Experiment | Data ready? | Bottleneck |
|---|---|---|
| **Redundancy audit** — "do our scanner signals add information beyond RV−IV on the current universe?" | ✅ **Yes, today.** 12 months × 103 tickers of vrp/RV/IV/skew + 4.5 years of options_volume + 13 months OHLC. | none — this is the V1 notebook scope below |
| **Forward-looking IPCA on UW data** — "estimate a 3-factor IPCA on UW-derived option chars 2025→2026+" | 🟡 **Marginal now, yes in ~18 months.** 12 monthly cross-sections × 103 ≈ 1,200 obs is too thin for IPCA EM convergence; paper uses ~100 months × 2,000 names. | calendar time — accumulates one month per month |
| **Paper replication (R1, 1996-2022)** — "reproduce Table 2/3 numbers on UW data" | 🔴 **No, and probably never.** | `option_chain_per_strike` is 5 days deep. We cannot reconstruct historical delta-hedged option returns. UW supplies current chain snapshots, not a retro-corpus. |

**This notebook delivers Row 1.** Rows 2 and 3 are documented in `00-goal-and-decisions.md` as out-of-scope or gated by calendar time.

---

## 1. Notebook scope

**Path:** `docs/research/goyal-saretto-ipca-options/notebooks/01-rv-iv-residualization.ipynb`

**Question it answers:** For each option/regime signal we currently compute (CRI components, VCG components, GEX, scanner signal-hit scores, …), how much of its cross-sectional variation is already encoded in RV−IV?

### 1.1 Universe and cadence

- **Universe (refined 2026-05-20):** all tickers in `uw_scan.watchlist` ∩ `massive ticker_type = 'CS'` ∩ ≥126 days of `vrp_daily` history. The `type = 'CS'` filter drops ETFs (SPY, QQQ, IWM), indices (SPX), and ADRs — the paper restricts to CRSP share codes 10/11 (US common stock); this is the equivalent. Pre-Phase-3, we use a hard-coded drop list inline in `data_access.py:get_universe()`; post-Phase-3 it joins `tickers_metadata.type`.
- **Drop log persisted:** every notebook / backtest run records which watchlist tickers were excluded and why, via `data_access.get_universe_drop_log()`. No silent drops.
- **Cadence:** monthly cross-sections, taken on the last trading day of each calendar month per NYSE calendar, 2025-05-30 through 2026-04-30 (12 complete monthly snapshots).
- **Month-end fallback:** if a ticker has no `vrp_daily` row on the official month-end day, walk backwards up to 3 trading days; otherwise drop that (ticker, month) cell. Behavior centralized in `data_access.resolve_observation_date()`.
- **Why monthly, not daily:** matches Goyal-Saretto's panel. Monthly also dampens microstructure noise in our signals, and gives us 12 × 103 ≈ 1,200 observations — enough for the simple linear diagnostics below, not enough for full IPCA EM.

### 1.2 Signals to audit (the X side)

Each row below is a candidate "predictor" we'll project against RV−IV. **All are already in the DB.**

| Signal | DB source | Goyal-Saretto analog (Table 5 importance rank) |
|---|---|---|
| **RV−IV** | `vrp_daily.vrp` | **#1, 0.54** — the reference; what we project everything else *against* |
| **RV (12mo realized vol)** | `vrp_daily.rv` or `volatility_stats_history` | #4, 0.45 |
| **IV ATM (30d)** | `vrp_daily.iv` | folded into RV−IV; #9 in own right (0.29 via Option price) |
| **IV skew (25d RR)** | `risk_reversal_skew_history` | analog of IV slope #10 in Table 5 |
| **CRI score** | `cri_snapshots.cri_score` | composite — not in paper, novel to UW |
| **CRI VRP component** | `cri_snapshots.payload->'cri'->'breakdown'->'vrp'` | direct restatement of RV−IV |
| **VCG score** | `vcg_snapshots.payload` (TBD) | composite — novel to UW |
| **Net GEX** | `greek_exposure_daily.net_gex` | flow / dealer-positioning — not in paper |
| **Stock momentum (1mo, 11mo skip-1)** | derived from `daily_ohlc` | Stock return / Stock return11; #18 / not-ranked |
| **Stock price** (log close, EOM) | `daily_ohlc.close` | #8, 0.37 |
| **Max10 (3mo top-10 daily ret avg)** | derived from `daily_ohlc` | #5, 0.42 |
| **Realized skew (12mo)** | derived from `daily_ohlc` | not ranked highly in Table 5 |
| **Volume** ($ option vol, EOM) | `options_volume_daily.call_premium + put_premium` | not in Table 5 top-13 |
| **Bullish/bearish premium imbalance** | `options_volume_daily.net_call_premium - net_put_premium` | novel to UW |
| **Aggressive flow ratio** (ask-side / total) | `options_volume_daily.call_volume_ask_side / call_volume` | novel to UW |

15 signals → cross-section of 15 columns × 103 tickers × 12 months.

### 1.3 Diagnostics to compute (the Y side)

**Scope decision (2026-05-20):** V1 ships only Diagnostics A and B. Diagnostics C and D were deferred — rationale documented under §4.

#### Diagnostic A — Cross-sectional rank correlation matrix

Each month, compute Spearman ρ between each pair of signals across the cross-section. Then time-series-average over the 12 months.

**Output:** a 15×15 heatmap. **Action threshold:** any non-RV−IV signal with |ρ| > 0.7 to RV−IV is *prima facie* a redundant signal. Drop it, replace it, or document that it adds non-cross-sectional information.

#### Diagnostic B — RV−IV residualization R²

For each non-RV−IV signal *s*, regress *s* on RV−IV cross-sectionally each month:
```
s_{i,t} = α_t + β_t · (RV−IV)_{i,t} + ε_{i,t}
```
Report time-series average R² for each signal. **Action threshold:** R² > 50% means RV−IV "explains" most of the cross-sectional spread of that signal.

#### Deferred — Diagnostic C (forward predictive power with stock-return proxy)

This was the original "form decile portfolios on raw vs residualized signals, compare next-month stock-return spread" plan. **Deferred** because:
- The paper's claim is about *option*-return spreads vanishing. A stock-return-spread proxy answers a different question.
- The honest fidelity-preserving version is a synthetic-straddle return engine — built as Step 8 in doc 13, not in V1.
- A/B without C still produces a defensible pruning verdict via correlation + R² thresholds.

Diagnostic C will run later, against the L1 backtester (doc 13), once `SyntheticStraddleProvider` ships.

#### Deferred — Diagnostic D (rolling 6-month stability)

Statistically too thin on a 12-month window — only 7 rolling windows, all overlapping. The plot would be noisy and any "trend" would be eye-of-the-beholder. Revisit once the panel has ≥ 18 months.

### 1.4 Deliverables

- A single `.ipynb` with the four diagnostics, ~12 cells, runnable end-to-end in < 5 min on the local DB.
- A short report `docs/research/goyal-saretto-ipca-options/08-redundancy-audit-results.md` written *after* the notebook runs, with the heatmap exported as PNG and the action-threshold table populated.
- Decision-relevant output: a list of signals we can deprioritize in the scanner (the "RV−IV duplicates"), and the signals that survive the audit and earn their slot.

---

## 2. Data audit — what's in the DB right now

**Queried 2026-05-20 against `option_wizard` Postgres.**

### 2.1 Universe and depth

| Table | Tickers | Earliest | Latest | Rows | Sufficient? |
|---|---:|---|---|---:|---|
| **`watchlist`** | 103 | — | — | 103 | ✅ |
| **`daily_ohlc`** | 102 | 2025-04-14 | 2026-05-19 | 6.4k | ✅ 13 months daily |
| **`vrp_daily`** *(IV, RV, RV−IV)* | 104 | 2025-05-13 | 2026-05-19 | 24.7k | ✅ 12 months daily |
| **`realized_volatility_history`** | 104 | 2025-05-12 | 2026-05-19 | 26.4k | ✅ |
| **`risk_reversal_skew_history`** | 103 | 2025-05-13 | 2026-05-19 | 22.5k | ✅ |
| **`options_volume_daily`** *(call/put vol, premium, aggressor split)* | 103 | **2021-08-31** | 2026-05-18 | 20.9k | ✅ 4.5-year depth (!) |
| **`cri_snapshots`** *(market-wide, not per-ticker)* | (market-level) | 2026-05-15 | 2026-05-19 | 242 | 🟡 5 days; one ticker (SPX) |
| **`vcg_snapshots`** | (market-level) | — | — | 238 | 🟡 same |
| **`iv_term_snapshots`** | 103 | 2026-05-11 | 2026-05-19 | 93k | 🟠 **only 8 days** |
| **`iv_smile_snapshots`** | 26 | 2026-05-13 | 2026-05-20 | 81k | 🟠 **only 7 days, 26 tickers** |
| **`option_chain_per_strike`** | 103 | 2026-05-13 | 2026-05-18 | 137k | 🟠 **only 5 days** |
| **`greek_exposure_daily`** | **2** | 2025-05-19 | 2026-05-19 | 504 | 🔴 **only 2 tickers** |
| `signal_hits` *(scanner detector outputs)* | 102 | 2026-05-18 | 2026-05-20 | 1.8k | 🟠 only 3 days of scanner runs persisted |
| `flow_events` *(raw UW alerts)* | 103 | 2026-04-13 | 2026-05-20 | 464k | ✅ 37 days, plenty |

### 2.2 Per-ticker depth distribution (`vrp_daily`)

- 104 tickers total.
- Average days/ticker: **237** (≈ 11 months).
- Min: 120 days. Max: 256.
- **103 tickers have ≥126 days** (6 months). 21 have ≥1 year.

This is the most relevant depth statistic. **For a monthly-cross-section analysis with ≥6 months of history, we get the full 103-ticker watchlist.**

### 2.3 Verdict table

| Notebook need | Data ready? |
|---|---|
| Monthly RV−IV cross-section over 103 tickers, 12 months | ✅ |
| Monthly stock returns, momentum (1mo, 11mo skip-1), Max10 | ✅ — derive from `daily_ohlc` |
| IV skew (25d risk-reversal) cross-section, monthly | ✅ |
| Option-volume / premium / aggressor signals, monthly | ✅ — `options_volume_daily` is the surprise jewel here (4+ years deep) |
| CRI / VCG as composite scanner signals | 🟡 only 5 days of market-level CRI snapshots; for the notebook we'd need to recompute CRI components from underlying inputs over 12 months. Doable but adds scope. |
| BKM model-free moments (MFvol/MFskew/MFkurt) | 🔴 needs strike-grid IV per ticker; we have only 5 days × 26 tickers of `iv_smile_snapshots`. **Drop from scope.** |
| IV term factor (360d − 30d ATM) | 🔴 8 days only. **Drop or backfill first.** |
| Per-ticker GEX/vanna/charm as residualized signals | 🔴 `greek_exposure_daily` only has 2 tickers. **Drop from scope.** |
| Delta-hedged-call expiration-to-expiration return as dependent variable | 🔴 `option_chain_per_strike` is only 5 days deep. **Use stock returns as a coarse proxy** for Diagnostic C, with a clear caveat in the writeup. |
| Compustat firm-level chars (BM, Assets, Profit margin, …) | 🔴 not in DB at all. **Out of scope.** |

---

## 3. What this notebook will and won't tell us

### Will tell us
- Whether RV−IV alone makes 5+ of our scanner signals statistically redundant on this codebase's universe over the past 12 months (the "Q5/Q6" question in `06-open-questions.md`).
- Whether our option-volume / aggressor-flow signals (the ones the Goyal-Saretto paper does *not* have) are decoupled from RV−IV — if yes, they're our actual cross-sectional edge.
- Whether the CRI's VRP component is doing what we think it is by checking its correlation with raw `vrp_daily.vrp`.

### Won't tell us
- Whether our results would hold on a 27-year sample or in a market regime other than 2025-2026.
- Whether the headline Goyal-Saretto result (IPCA explains all 46 strategies) reproduces on our data — we don't have the firm-level characteristics or the contract-level returns, so the paper's actual experiment is out of reach.
- Anything about transaction-cost-adjusted returns. The retail-execution TC story is a separate notebook.

---

## 4. Caveats baked into the methodology

- **Diagnostic C deferred.** A stock-return proxy answers a different question than the paper's option-return one. Diagnostic C ships against the L1 backtester (doc 13) with a synthetic-straddle engine, not against this notebook.
- **Monthly cross-section of ~103 tickers is thin.** Spearman ρ confidence intervals are wide. Treat |ρ| > 0.7 as "actionably high," not statistically conclusive.
- **12 months is one regime.** Anything that depends on 2020-style or 2008-style vol shocks for identification will look weak here. Flag this in the writeup.
- **Sign convention is now centralized in a SQL view** (`v_rv_iv_paper_sign`, migration 049). `vrp_daily.vrp` historically stored `iv − rv`; the paper uses `rv − iv`. The view exposes `rv_minus_iv` as the canonical column. **All notebook code reads `v_rv_iv_paper_sign`, never the raw `vrp_daily.vrp`.** The first-cell sign-check from the prior plan is obviated by the view; we retain a one-line cell that asserts `rv_minus_iv = rv - iv` for sanity.
- **Universe filter is now explicit.** ETFs, indices, ADRs dropped by `type = 'CS'` filter (paper's CRSP-share-code-10/11 equivalent). Drop list logged via `data_access.get_universe_drop_log()`.

---

## 5. Decision

Recommendation: **build it as the V1 deliverable of doc 13's critical path.** The data is sufficient for the slice that delivers actionable signal-redundancy verdicts on the current scanner, and the slices that aren't ready (BKM moments, full chain history, per-ticker Greeks) are precisely the ones that the Goyal-Saretto paper itself shows are *not* the dominant explainers — so missing them doesn't compromise the central question.

**Build order (matches doc 13's Steps 0–7):**
1. Migration 049 — sign-flip view (~10 min)
2. `data_access.py` per doc 10 contract (~2-3 hr)
3. Notebook skeleton, universe pull, sign-flip sanity assertion (~30 min)
4. Diagnostic A (correlation matrix) (~45 min)
5. Diagnostic B (residualization R²) (~45 min)
6. Writeup `08-redundancy-audit-results.md` populated from notebook output (~1 hr)

Total ~5–6 hours to **first decision-worthy output** (the pruning verdict for Guardrail 1). Subsequent diagnostics layer on top of the L1 backtester in doc 13.
