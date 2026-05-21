# 05 — Guidance audit checklist (formerly "Replication plan")

**Status:** active reference. **Reframed 2026-05-20 per doc 00** — we are *not* replicating the paper. We are using its findings as guardrails on what we build, drop, and publish. The original R0/R1/R2 replication tiers are preserved in the appendix at the bottom of this doc for reference only.

## The four-guardrail audit (paper finding → decision → verification → status)

Each row maps one paper finding to one concrete change we make to the unusual-whales system, the path to verify it on our data, and the current status.

### Guardrail 1 — Option-side signals collapse to RV−IV

- **Paper finding:** 46 option-side cross-sectional signals collapse to ~1 IPCA factor dominated by RV−IV. Only 2 of 46 survive Benjamini-Hochberg 5% FDR multiple-hypothesis testing.
- **Decision:** Stop adding option-side scanner signals on the assumption they're independent. Audit existing CRI / VCG / scanner components against RV−IV.
- **Verification path:** Diagnostics A + B in the V1 notebook (doc 07). Cross-sectional rank correlation + RV−IV residualization R² on 12 months × 103 tickers.
- **Decision threshold:** signal with `R²(s, RV−IV) > 0.5` OR `|ρ(s, RV−IV)| > 0.7` is presumed redundant and is dropped or replaced.
- **Status:** data sufficient (verified doc 07). Notebook not yet built. Critical path is doc 13 Steps 0–7.

### Guardrail 2 — Only RV−IV and IV-slope survive multiple-hypothesis testing

- **Paper finding:** of 46 raw signals, only RV−IV and IV-slope survive at the 5% FDR cutoff (t ≥ 2.25 raw, 2.60 IPCA-α). The rest are statistical artifacts amplified by the file-drawer problem.
- **Decision:** RV−IV's centrality in CRI is well-founded. IV-slope deserves a first-class slot if it doesn't already have one. Most other option-side signals are scenery — they ride on these two.
- **Verification path:** inventory current scanner-signal stack + L1 backtester (doc 13) decile sorts on each. Compare alpha_resid (after RV−IV residualization) to alpha_gross.
- **Decision threshold:** signal whose `alpha_net <= 0` is dropped. Signal whose `alpha_resid` is statistically indistinguishable from 0 is presumed to ride RV−IV — drop or document.
- **Status:** scanner-signal inventory not yet enumerated. L1 backtester is gated by Steps 0–5 of doc 13.

### Guardrail 3 — IPCA F2/F3 dominated by MarketCap + Assets (firm-level chars)

- **Paper finding:** in IPCA Table 5 importance scores, RV−IV is #1 (0.54), but MarketCap (#2, 0.49) and Assets (#3, 0.46) carry F2 and F3. Pure option-side analysis misses these.
- **Decision:** Phase 3 (massive fundamentals fetcher, doc 14) brings firm-level data into reach. Once integrated, audit whether our scanner cares about size and balance-sheet structure at all.
- **Verification path:** cross-sectional decile sort on MarketCap and Assets via L1 backtester (doc 13) once `get_firm_chars_panel()` (doc 10) is implemented.
- **Decision threshold:** if MarketCap or Assets has alpha_net materially above existing scanner signals, integrate them into the scanner's ranking weights.
- **Status:** massive coverage audit done (docs 09, 14). Phase 3 fetcher + persistence + cards not yet built.

### Guardrail 4 — All IPCA alphas turn negative after 30% effective-spread cost

- **Paper finding:** Muravyev-Pearson (2020) ESPR/QSPR ratio is ~30%. Applied to all 46 strategies, *every* IPCA alpha turns negative — not just the borderline ones.
- **Decision:** Any signal or trade-plan that doesn't apply realistic TC is presumed false on the product surface. The 30% ratio is the floor.
- **Verification path:** TC realism audit — inventory of scanner ranking, Trade Insights AI, watchlist cards, trade-plan UI — verify each shows net-of-TC numbers. L1 backtester applies the 30% baseline + sensitivity at 50% and 100%.
- **Decision threshold:** any product surface showing gross-only expected outcomes is a bug. Patch list lands in `11-tc-audit.md`.
- **Status:** TC audit not started. L1 backtester TC overlay specified in doc 13 §1.4.

## Output documents (one per decision)

| Doc | Owns the verdict for | Status |
|---|---|---|
| `08-redundancy-audit-results.md` | Guardrails 1 + 2 (option-side pruning verdict from V1 notebook) | not yet written; awaits notebook output |
| `11-tc-audit.md` | Guardrail 4 (product surface TC patch list) | not yet started |
| `12-firm-chars-gap.md` | Guardrail 3 (firm-level integration verdict) | not yet started; gated by Phase 3 |
| `15-flow-signal-verdict.md` | Novel question (do UW flow signals add information beyond RV−IV?) | not yet started; gated by Phase 2 + 3 |

## What this checklist explicitly is *not*

- A plan to reproduce the paper's numbers
- An IPCA estimator build
- A 46-characteristic panel construction

Those are documented as out-of-scope in doc 00 and as appendix below for reference only.

---

## Appendix — Original R0/R1/R2 replication tiers (deprecated)

**This section is preserved for reference.** It describes what a *replication* of the paper would entail and which tier is which. **None of these are active goals**; the workspace's actual goals are the four guardrails above. The appendix is kept because the per-characteristic data-source map at the bottom remains useful as a reference card when implementing Phase 3.

### The three tiers (none are active)

| Tier | Goal | Effort | Output |
|---|---|---|---|
| **R0** | Verify Goyal & Saretto's main numbers on their original sample using Seth Pruitt's IPCA code + OptionMetrics academic subscription | 2–3 weeks | Re-create Table 1, Table 3 within 5% |
| **R1** | Rebuild the 46 characteristics from UW + Compustat + CRSP-equivalent on the paper's 1996–2022 sample period, where each variable is constructible given our data | 1–2 months | Subset (≈30/46) characteristics; restricted-IPCA alphas; comparison to paper's restricted-IPCA |
| **R2** | Extend to 2023–2026 using UW flow-side characteristics (vanna, charm, gamma exposure) the paper does *not* have | 3+ months | Novel: do dealer-flow signals carve out a factor beyond the paper's 46? |

R0 isn't practical (no OptionMetrics). R1's chain-depth requirement is unmet by UW. R2 is the closest to "actually interesting research output" but is gated by both calendar time and Phase 2 backfill.

The four-guardrail framing above is a re-cut of R1's *intent* (test whether the paper's claims hold on our data) into smaller, decision-shaped chunks that don't require the full 46-char × 27-year panel.

## Per-characteristic data-source map

`Status` legend: ✅ already in DB / API; 🟡 derivable from existing UW endpoints; 🟠 needs new fetcher; 🔴 not in UW (need Compustat/CRSP-equivalent).

### A.1 Contract characteristics (8)

| Paper var | UW source | Our location | Status | Notes |
|---|---|---|---|---|
| Moneyness | UW chains | `cards/vol_series.py` derives; chains in `uw_chains` table | ✅ | strike/spot at initiation; trivially recoverable per option-symbol |
| Bid-ask spread | UW quote snapshots | `flow_repository.py`, `nbbo_*` columns | 🟡 | Goyal uses end-of-day OM quotes; UW snapshot cadence differs — need to verify spread definition |
| Open interest | UW historical chains | `vol_index_repository.py` (oi columns), endpoints in `uw.py` | ✅ | |
| Delta | UW Greeks endpoint | `greek_exposure_repository.py` | ✅ | UW publishes contract-level Δ |
| Vega | same | same | ✅ | |
| Gamma | same | same | ✅ | |
| Volume | UW flow / aggregates | `flow_repository.py` | ✅ | $ volume on initiation day |
| Option price | UW chains | midpoint of bid+ask at initiation | ✅ | |

### A.2 Risk-neutral distribution measures (8)

| Paper var | UW source | Status | Notes |
|---|---|---|---|
| IV ATM | UW vol surface, 30d slice | ✅ | exposed via `vol_series.py` |
| IV slope | UW vol surface, 30d, OTM 0.8 − ATM | 🟡 | We have 25Δ/50Δ slice — need to derive 0.8-moneyness slice or accept a different convention. Document the substitution. |
| IV term | UW surface, 360d ATM − 30d ATM | 🟡 | 360d slice availability varies by ticker; we have 30/60/90/180 reliably. **Gap.** |
| IV vol (vol of vol) | stdev of 30d ATM IV over prior month | 🟡 | Computable from historical surface time series |
| MFvol | Bakshi-Kapadia-Madan 2003 on 30d OTM C+P | 🟠 | Not currently computed — we'd need to integrate the BKM kernel against the UW chain |
| MFskew | same family | 🟠 | same |
| MFkurt | same family | 🟠 | same |

The MF-* trio is the most painful gap. Implementation is well-known (Hansis-Schlag-Vilkov 2010 code is on Vilkov's page, the paper cites it).

### A.3 Physical distribution measures (9)

| Paper var | Our source | Status | Notes |
|---|---|---|---|
| Stock return (1mo) | OHLC | ✅ | massive / `market-warehouse` lake |
| Stock return11 (skip-recent momentum) | OHLC | ✅ | trivial |
| RV (12mo, ≥150 daily obs) | OHLC | ✅ | matches what `vol_series.py` already does for the RV−IV calculation |
| Rskew, Rkurt | OHLC | ✅ | |
| Turnover | OHLC + shares-outstanding | 🟡 | shares-outstanding source TBD; CRSP-equivalent unknown |
| IdiosynVol (FF3 residual stdev, 10d min) | OHLC + FF3 factors | 🟠 | need FF3 factor series (Ken French's data library — public download, easy) |
| Max10 (avg top-10 daily returns last 3mo) | OHLC | ✅ | trivial |
| Autocorrelation (6mo, ≥100 obs) | OHLC | ✅ | |

### A.4 Physical − risk-neutral differences (4)

| Paper var | Computation | Status |
|---|---|---|
| **RV−IV** | A.3 RV − A.2 IV ATM | ✅ — this is the entire CRI-VRP component |
| RV−MFvol | A.3 RV − A.2 MFvol | 🟠 — gated by MFvol |
| Rskew−MFskew | | 🟠 |
| Rkurt−MFkurt | | 🟠 |

### A.5 Stock-level firm characteristics (17)

Most of these come from **Compustat / CRSP fundamentals data we do not have today**. We have UW + massive/OHLC; we don't have a structured Compustat feed.

| Paper var | Source | Status | Workaround |
|---|---|---|---|
| BM | Compustat CEQ / Mkt | 🔴 | yfinance has it sometimes (banned as primary); FMP could supply but coverage gaps |
| Profitability | Compustat GP/AT | 🔴 | FMP `key-metrics` endpoint |
| InstOwn | Thomson Reuters 13f | 🔴 | UW Institutional Activity endpoint may help; coverage and 13f-update lag differ |
| MarketCap | Cap = px × shares-outstanding | 🟡 | shares-outstanding feed needed |
| RSI (short-int-ratio) | Compustat shortintadj | 🔴 | UW short-volume endpoint not the same metric |
| Assets | Compustat AT | 🔴 | FMP |
| Debt | Compustat DLTT+DLC | 🔴 | FMP |
| Leverage | Debt/Assets | 🔴 | derived from above |
| CashFlowVar | 60mo cash-flow variance | 🔴 | needs 5yrs of Compustat per-month |
| Cash to asset | CHE/AT | 🔴 | FMP |
| AnalystDisp | IBES dispersion | 🔴 | FMP `analyst-estimates`, dispersion derivable |
| 1yr NewIss / 5yr NewIss | CRSP cfacshr-adjusted shrout | 🔴 | shares-outstanding history needed |
| Profit margin | Compustat OIADP/SALE | 🔴 | FMP income statement |
| Stock price | log(close-of-month) | ✅ | already in OHLC |
| ROE | NI/BE | 🔴 | FMP |
| ExternalFin | net share-issuance + net-debt issuance / AT | 🔴 | FMP cash-flow statement |
| Z-score | Dichev 1998 | 🔴 | FMP — also a composite the dexter project may already build |

**A clean R1 replication using only UW + OHLC would drop these 17 firm-level characteristics**, leaving 29 features. That's still enough to be informative about whether the option-side characteristics collapse to an RV−IV-dominated factor, *but* it removes MarketCap and Assets — exactly the characteristics that dominate F2 and F3 in Γ_β. So the F2/F3 part of the story can't be replicated without firm fundamentals.

## Suggested R1 minimal experiment

**Goal:** answer "on UW data 2017–2025, does a 3-factor IPCA fit on option-side characteristics alone reduce the cross-sectional alphas of a curated set of option strategies to near-zero, and is the first factor still dominated by RV−IV?"

**Data scope:**
- 100 most-liquid optionable US names (or our existing universe — `web/app/page.tsx` watchlist intersected with UW coverage), monthly cross-sections, 2017-01 through 2025-12 (≈100 months).
- 29 characteristics (drop 17 firm-fundamentals from A.5).
- Construct delta-hedged call returns expiration-to-expiration *with daily Δ rebalancing* — exactly the paper's primary specification.

**Estimation:**
- Use Seth Pruitt's IPCA Python package (verify on PyPI; if not, build from his MATLAB code in the K-P-S 2019 supplementary materials).
- K ∈ {1, 2, 3, 4, 5}, constrained Γ_α = 0; report Table 2-style R²s.
- Bootstrap Wald α-test on K = 3 (B = 1000).

**Trading-strategy alphas (Table 3 analog):**
- For each of the 29 characteristics, form decile sorts → 10−1 or 1−10 long-short → compute realized return and IPCA-expected return → α.
- BH 5% FDR cutoff at 2.60 (paper's threshold).

**Transaction-cost overlay:**
- Use UW NBBO snapshots to compute QSPR per contract at initiation; apply ESPR/QSPR ∈ {30%, 50%, 100%}.
- Persist all monthly returns and per-strategy alphas to a new repository `storage/ipca_replication_repository.py` (per the [feedback_repository_split_threshold](.) standing rule — never extend `repository.py`).

**Output deliverables:**
- `src/uw_scan/research/ipca/` package (separate from the production scanner; this is research, not user-facing).
- Notebook in `docs/research/goyal-saretto-ipca-options/notebooks/01-ipca-on-uw.ipynb` with the IS results.
- A markdown report `docs/research/goyal-saretto-ipca-options/15-uw-replication-results.md` documenting deviations from paper numbers and any new findings on 2023–2025 data.

## What this would teach us about CRI / scanner

Three concrete deliverables if R1 runs cleanly:
1. **Confirms or refutes** that on UW data, the RV−IV-style component carries most of the cross-sectional option-return spread post-2022. If confirmed → CRI's reliance on a VRP-like component is well-founded. If refuted → either (a) the regime changed, (b) UW data captures a different signal than OptionMetrics, or (c) our RV−IV is implemented slightly differently and we should investigate.
2. **Tests whether dealer-flow / vanna-charm signals** carve out a fourth IPCA factor — i.e., whether they add information beyond the paper's 46. This is the genuine research contribution.
3. **Cost-of-implementation reality check.** The paper's TC overlay kills *all* IPCA alphas. If UW's NBBO data shows that ratio is even higher in practice for retail-accessible option markets, that's a key warning to add to any signal-trading product surface.
