# 06 — Open questions

Track unresolved items here. As each is closed, link to the file or commit that resolves it.

**Status legend:** 🟢 closed (resolved or now out of scope) | 🟡 open and addressed by an in-progress doc | 🔴 open, no plan yet

**2026-05-20 update:** the workspace reframed from "replication" to "four-guardrail audit" (doc 00). Many original questions are now closed by the reframe, not by an experimental answer. Status reflects the new framing.

## Methodology

### 🔴 Q1. Does the paper's IPCA-explains-everything result depend on the 2017–2022 portion of the sample?
The Zhan-et-al-10 robustness check (Table 6) is the only IS/OOS split in the paper, and it splits at the *Zhan publication date* (Apr 2016). OOS raw returns there are *higher* than IS (1.43% vs 0.61% avg). The single-RV−IV-factor structure is documented on the full sample, not split. We don't know whether F1's RV−IV-dominance is stable across decades.
- **New status (2026-05-20):** out of scope under doc 00 — this is a paper-internal question we can't answer without 27 years of contract-level data. Kept here as a literature-quality flag, not an active item.

### 🟢 Q2. Is the paper's RV−IV construction identical to what `vol_series.py` produces?
The paper: A.4.1 RV−IV = (12-mo daily realized vol of log returns, ≥150 obs) − (30-day ATM IV from OptionMetrics surface, observed at position initiation).
- **Closed by:** doc 13 §"Sign-flip view (Step 0 prerequisite)" — the sign convention is now centralized in SQL view `v_rv_iv_paper_sign`. The notebook (doc 07) reads the view, not the raw column. Definitional parity with `vol_series.py` is still worth a one-time check before V1 ships, but the *sign* question — the most common foot-gun — is resolved by the view.
- **Remaining:** confirm `vol_series.py` uses log returns (not arithmetic), 12-mo window with ≥150 obs, 30d ATM (not OI-weighted). One-line cell in V1 notebook.

### 🔴 Q3. How sensitive is the result to the ESPR/QSPR ratio?
The paper uses 30% based on Muravyev-Pearson (2020). They don't sweep ratios in the main paper. Internet Appendix may.
- **Action:** Internet Appendix IA1 is the figure showing net-of-TC alphas across strategies. Verify whether IA includes sensitivity to ESPR/QSPR. (Need to pull IA from OUP.)
- **Why it matters:** UW's user base trades through retail brokers where effective spreads can be materially worse than 30% of quoted (e.g., 50–70% in less-liquid names). The paper's "no alpha survives TC" claim could be *stronger* in practice, not weaker.
- **New status:** open and **directly relevant** to Guardrail 4. Doc 13 §1.4 specifies that L1 backtester reports alphas at 30%, 50%, and 100% — sensitivity is baked in by design.

### 🔴 Q4. Why exactly is RV−IV special — risk premium for variance, or just measurement?
Goyal & Saretto themselves flag this as future work:
> "An open question remains of why the return to the RV−IV managed portfolio is so strongly related to latent factors that IPCA recovers. We plan to address this issue in future work." (p.1786 / p.1787)
- This is a *theoretically* open question, not just empirical. Note for any internal discussion of CRI / VRP framing — the "RV−IV proxies for VRP, VRP is a priced risk" story is the natural explanation, but isn't proven in this paper.
- **New status:** unchanged. Theoretical question, not an experimental one. Not blocking any workspace deliverable.

## Codebase implications

### 🟡 Q5. Does CRI's existing VRP component already encode this single-factor structure?
- **Action:** Read `src/uw_scan/scanners/cri.py` (and the related `docs/superpowers/archive/plans/2026-05-19-cri-methodology-tune.md` for context). If the CRI bar already weights VRP heavily, the paper *retroactively justifies* that design choice. If CRI distributes weight equally across vol-complex sub-signals, the paper suggests we may be over-weighting redundant ones.
- **New status:** addressed by V1 notebook (doc 07) — Diagnostic B residualizes every scanner-side signal against RV−IV. Verdict lands in `08-redundancy-audit-results.md` (not yet written).

### 🟡 Q6. Should the scanner's signal-stacking weights drop after RV−IV is included?
If 32 strategies' alphas rebound when we zero RV−IV's Γ_β, that means *most* option-side cross-sectional signals are statistical reflections of RV−IV. In a scanner that stacks ranks across signals, adding a 5th option-side signal to an already RV−IV-aware stack should give little marginal information.
- **Action:** add a correlation audit to `src/uw_scan/scanner/signals/` — what is the cross-sectional rank correlation between each scanner signal and a UW-derived RV−IV at the same observation date? Anything above ~0.7 is likely a near-duplicate.
- **New status:** this *is* Guardrail 1 in doc 00. Resolution is the V1 notebook output → `08-redundancy-audit-results.md`.

### 🟢 Q7. Does UW provide enough data to compute the Bakshi-Kapadia-Madan model-free moments?
The paper's MFvol/MFskew/MFkurt require a *grid* of OTM C and P prices for a *single* (T=30d, K range covering ≈ ±2σ) cross-section. We have the chain but the strike grid completeness varies by name.
- **Closed by:** doc 07 §2.3 — only 5 days × 26 tickers of `iv_smile_snapshots` historically. **BKM moments are out of scope** for the V1 notebook and for any of the four guardrails. Paper's own Table 5 ranks MFkurt outside the top 13; the cost of acquiring this data far exceeds the decision-information value.

### 🟢 Q8. Is Seth Pruitt's IPCA code publicly available as a Python package?
Goyal-Saretto acknowledge using it. Pruitt's website was at `sethpruitt.net` in the K-P-S era. As of the most recent revision (2025), need to verify availability.
- **Closed by:** doc 00 — full IPCA estimation is out of scope. We don't need Pruitt's code because we are not running IPCA. The four guardrails are answerable with simple cross-sectional sorts + residualizations.

### 🟢 Q9. Do we have a Compustat-equivalent feed?
The 17 firm-fundamental characteristics (A.5) all source from Compustat/CRSP. FMP covers most of them but with varying coverage and freshness.
- **Closed by:** docs 09, 14 — **massive.com provides 15 of 17 firm-level characteristics natively** via `/v2/reference/financials` + `/vX/reference/financials`. No FMP integration needed. The 2 gaps (InstOwn, AnalystDisp) are the lowest-importance characteristics in paper's Table 5 and are not blockers.

### 🔴 Q10. What does the OOS period 2009–2022 tell us about regime breaks?
Paper's OOS table (Table 2 panel B) starts in 2009. They don't carve out 2020-2022 specifically. The post-COVID retail-option boom plausibly changed the cross-section of IV / RV / flow signals materially.
- **Action:** when R1 runs, present results split at 2020-03 and 2023-01.
- **New status:** out of scope under doc 00 — we are not running R1. Kept here as a literature-quality flag for any future research direction.

## Productization

### 🔴 Q11. If RV−IV is genuinely the only signal carrying alpha, is there an obvious user-facing product?
The naïve answer is "long-RV−IV-high, short-RV−IV-low, delta-hedged daily." The paper's empirical result is this earns 1.73%/mo *after* a generous 30% ESPR TC overlay, with *t* = 14.94.
- BUT: the paper applies TC only at initiation, not at daily delta-rebal. For a retail-side product, daily rebal is impractical at any scale.
- **Action:** before any product framing, compute the "no-rebal" version: hold static-Δ for the full holding period. Goyal-Saretto cite this in §2 fn 5 — they put it in IA5. Pull IA5 to see how much of the 1.73% net survives.
- **New status:** still open. The L1 backtester's synthetic-straddle engine (doc 13) can model this directly with `daily_rebal=False`. Defer until L1 V1 ships.

### 🔴 Q12. Counterparty / availability constraints?
Decile-1 RV−IV (low realized minus implied vol) — these are typically *liquid* names with low realized vol — easy to short delta-hedged options. Decile-10 (high RV−IV) is the much-discussed "underpriced gamma" — but in the retail-broker world borrow/short-sale constraints could be binding for the option-side leg. Ramachandran & Tayal (2021) cited by the paper discuss short-sale constraints affecting option returns directly. The paper notes their RSI characteristic loads on F1 but doesn't deeply explore the constraint mechanism for the headline result.
- **New status:** unchanged. Defer until L1 V1 ships.

## New questions raised by the 2026-05-20 reframe

### 🟡 Q13. What is massive's actual rate limit on our tier?
- **Why:** Phase 3 backfill (doc 09 §"Backfill economics") assumes Polygon-style 100 req/min — unverified. 103-ticker × 5-endpoint backfill should saturate before completing.
- **Action:** run a saturating burst from `scripts/probe_massive.py` and capture `Retry-After` / `X-RateLimit-*` headers. Before Phase 3 fetcher ships.

### 🟡 Q14. Field-parity between massive `/v2` and `/vX` in the 2009–2020 overlap zone?
- **Why:** docs 09 and 14 claim both endpoints can be combined for 1997–present coverage. We have not verified that `/v2.assets[2015-03-31] == /vX.balance_sheet.assets.value[2015-03-31]` for any ticker.
- **Action:** 30-line script that pulls AAPL + MSFT + JPM + 2 mid-caps from both endpoints for 4 quarters in the overlap zone and prints field-by-field diffs. Before Phase 3 ships.

### 🔴 Q15. Watchlist coverage on massive `/vX` for full 103 tickers?
- **Why:** sampled AAPL, RBLX, TSLA — all good. Have not confirmed coverage on smaller-cap watchlist names (whoever is in `uw_scan.watchlist`).
- **Action:** batch-probe full watchlist for `/vX/reference/financials?ticker={t}&limit=1` — report any tickers that 404 or return empty results.

### 🟡 Q16. NYSE calendar source for month-end resolution?
- **Why:** doc 10 specifies "last trading day of each calendar month per NYSE calendar" — implementation needs a calendar source. `pandas_market_calendars` adds a dependency; alternatively roll our own holiday list.
- **Action:** check whether the codebase already has trading-day math somewhere (gold scheduler? options_volume calendar?). Reuse if so.

---

## Item status checklist

```
- [x] Q2 — sign-flip view centralizes convention (migration 049 in doc 13)
- [-] Q5 — addressed by V1 notebook (doc 07)
- [-] Q6 — this IS Guardrail 1; resolution = V1 notebook output
- [x] Q7 — BKM moments out of scope (doc 07 §2.3, doc 00)
- [x] Q8 — IPCA estimator out of scope (doc 00)
- [x] Q9 — massive replaces FMP (docs 09, 14)
- [ ] Q1 — out of scope; literature flag only
- [ ] Q3 — addressed by L1 TC sensitivity (doc 13 §1.4); IA1 still worth pulling
- [ ] Q4 — theoretical, not blocking
- [ ] Q10 — out of scope; literature flag only
- [ ] Q11 — defer until L1 V1 ships
- [ ] Q12 — defer until L1 V1 ships
- [-] Q13 — rate-limit burst test before Phase 3
- [-] Q14 — /v2 vs /vX field parity before Phase 3
- [ ] Q15 — full-watchlist coverage probe before Phase 3
- [-] Q16 — calendar source for month-end resolution before doc 10 implementation
```

Legend: `[x]` closed | `[-]` in-progress / addressed by an in-flight doc | `[ ]` open, no active plan
