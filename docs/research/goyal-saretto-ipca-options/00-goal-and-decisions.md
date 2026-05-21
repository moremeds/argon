# 00 — Goal and decisions (north-star doc)

**Read this first.** Everything else in this workspace serves the goal stated here. If a doc or a piece of code drifts from this, the doc is wrong, not the goal.

## The goal

**Use Goyal & Saretto (2025) as a decision-shaping reference for the unusual-whales signal stack — prune what is redundant, harden what survives, never trust a backtest that ignores realistic spread cost.**

We are **not** replicating the paper. We have neither the OptionMetrics academic feed nor the historical full-chain depth required to reconstruct contract-level delta-hedged option returns over 1996–2022. Anything that requires those inputs is structurally out of reach on our data stack and is **out of scope** for this workspace.

We **are** using the paper's findings as guardrails on what we build, what we drop, and what we publish to users.

## What changed (compaction log)

- **2026-05-20 — Initial framing was "replication plan."** Reframed to "guidance audit + backtest" after the user asked to clear the goal: alphas in the paper aren't our alphas, but the paper's findings constrain which directions are likely dead ends and which are likely live.
- **2026-05-20 — All discussion now persists to docs.** Per user directive: every analytical decision, every endpoint probe, every methodology debate lives in this workspace. The conversation is not the source of truth — these docs are.

## The four guardrails (paper findings → our decisions)

These are the load-bearing claims from the paper, and the concrete things we will change about our system because of them.

| # | Paper finding | What we change in unusual-whales | Verification path | Status |
|---|---|---|---|---|
| **1** | 46 option-side signals collapse to ~1 factor dominated by RV−IV | Stop adding option-side scanner signals on the assumption they're independent. Audit existing CRI / VCG / scanner components against RV−IV. | Notebook `notebooks/01-rv-iv-residualization.ipynb` (doc 07) — cross-sectional correlation + residualization on 12 months × 103 tickers. | Data sufficient. Notebook not yet built. |
| **2** | Only 2 of 46 signals survive Benjamini-Hochberg 5% FDR (RV−IV, IV slope) | RV−IV's centrality in CRI is well-founded. IV-slope deserves a first-class slot if it doesn't already have one. Most other option-side signals are scenery — they ride on these two. | Inventory of current scanner signals + L1 backtester (doc 13) decile sorts on each. | Inventory not yet built. |
| **3** | IPCA F2/F3 dominated by MarketCap + Assets (firm-level chars) | Pure option-side scanning misses real cross-sectional structure. Firm size and balance-sheet position carry information our system doesn't currently see. | Phase 3 — massive fundamentals fetcher (doc 09) → cross-sectional decile sort on MarketCap, Assets. | Phase 3 not yet built. Coverage audit done (doc 14). |
| **4** | All 46 IPCA alphas turn negative after 30% effective-to-quoted spread is applied | Any trade plan / signal that doesn't apply realistic TC is presumed false. The 30% ESPR/QSPR ratio is the floor. | TC audit on existing trade-plan / Trade Insights AI surfaces + L1 backtester applies it from day 1. | Not started. |

## The actually-novel question (paper's framing → our edge)

Goyal-Saretto's 46 characteristics are all derived from **historical OHLC + the risk-neutral surface + firm fundamentals**. They do **not** include:

- Dealer-positioning signals (vanna, charm, net GEX)
- Trade-aggressor classification (ask-side vs bid-side flow)
- Per-ticker option-volume regime (rolling option-volume z-scores, premium imbalances)

These signals are **novel to UW** in the sense that no published paper has tested whether they collapse to RV−IV or carve out an independent factor.

**The most interesting research output this workspace can produce** is therefore not a replication of the paper, but an answer to: *do UW's flow/dealer signals add information beyond the paper's 46?*

That answer requires:
- Phase 2 (matrix-state backfill — vanna/charm/aggressive-flow on ≥12 months of history for the full watchlist)
- L1 backtester (doc 13) capable of residualizing each novel signal against RV−IV and reporting alpha gross + net of TC

This is the **R2** scenario in doc 05's appendix — and it is the only scenario worth pursuing as research output, because the alternatives (R0/R1) require data we don't have.

## Out of scope (and will not become in-scope without an explicit goal re-write)

- Reproducing Table 2 / Table 3 numbers from the paper
- Building Pruitt's full IPCA EM estimator on our data
- Anything that depends on historical full-chain depth pre-2026 (we have 5 days of `option_chain_per_strike`)
- Anything that depends on OptionMetrics academic subscription
- BKM model-free moments (MFvol / MFskew / MFkurt) — would need historical full chain
- 13-F institutional ownership (InstOwn) — not on our massive tier; lowest-importance char in paper's Table 5
- Benzinga analyst dispersion (AnalystDisp) — not on our massive tier; not in paper's top 13

## Success criteria

The workspace has earned its keep when it produces these three artifacts, in order:

1. **A defensible pruning verdict.** A list of current scanner signals to deprioritize or drop because they are RV−IV duplicates on our universe. Output goes in `08-redundancy-audit-results.md`. (Guardrail 1 + 2.)
2. **A TC realism patch.** A list of places in the product (scanner ranking, Trade Insights AI, watchlist cards, trade-plan UI) where expected-outcome numbers are shown without applying ≥30% of quoted spread as cost. Output goes in `11-tc-audit.md`. Each item closes with a code-level fix. (Guardrail 4.)
3. **A flow-signal verdict.** Once Phase 2 + Phase 3 land, an L1 backtest run that answers whether vanna/charm/aggressor signals are alpha-additive to RV−IV on our universe after TC. Output goes in `15-flow-signal-verdict.md`. (Guardrail 4 + novel question.)

Artifacts 1 and 2 are achievable in days, on existing data, with no new backfill. Artifact 3 is multi-week, gated by Phase 2 + Phase 3.

## Read order

1. **This doc** — orienting frame, what we are and aren't doing
2. **01-paper-metadata.md** — citation, abstract, IDs
3. **04-key-results.md** — Tables 1, 2, 3, 5 transcribed verbatim
4. **03-methodology.md** — IPCA equations, return definition, MHT cutoffs
5. **05-replication-plan.md** (top section only) — guidance audit checklist; appendix has the abandoned R0/R1/R2 tiers for reference
6. **07-notebook-scope-and-data-audit.md** — what the immediate notebook delivers and what data we have
7. **09-massive-fundamentals-coverage.md** — fundamentals data source verdict
8. **10-data-access-contract.md** — interface signatures for `data_access.py`
9. **13-backtest-design.md** — L1 cross-sectional + L2 per-signal backtester architecture
10. **14-massive-endpoint-probe-log.md** — authoritative endpoint probe log

## Pinned conventions for this workspace

- **RV−IV sign convention.** The paper uses `RV − IV` (positive when realized exceeded implied). Our `vrp_daily.vrp` historically stored `IV − RV`. Source of truth going forward is the SQL view `v_rv_iv_paper_sign` (migration TBD, part of step 0 in doc 13). Consumers read the view, never the raw column.
- **Universe.** Watchlist ∩ massive `type='CS'` ∩ ≥126 days of `vrp_daily` history. Drops ETFs, indices, ADRs. Filter lives in `src/uw_scan/research/data_access.py:get_universe()`.
- **Month-end.** Last trading day of each calendar month per NYSE calendar. If a ticker has no `vrp_daily` row that day, fall back to the most recent prior day within a 3-trading-day window; otherwise drop that (ticker, month) cell.
- **TC ratio.** Paper's baseline 30% of quoted spread; we also report at 50% and 100% for sensitivity. Never report a gross-only number in a user-facing surface.
- **No fabricated alphas.** If a backtest's sample is too thin for a defensible CI, the writeup says so. No t-stats from 12-month windows treated as if from 27-year windows.
