# Goyal & Saretto (2025) — IPCA factor model for equity option returns

Research workspace for understanding, validating, and potentially replicating:

> **Goyal, A., & Saretto, A. (2025).** "Can Equity Option Returns Be Explained by a Factor Model? IPCA Says Yes." *The Review of Financial Studies*, 38(6), 1783–1821. DOI: [10.1093/rfs/hhae087](https://doi.org/10.1093/rfs/hhae087).

The paper builds an Instrumented Principal Component Analysis (IPCA) factor model on 46 cross-sectional predictors of delta-hedged equity-option returns (OptionMetrics, 1996–2022) and concludes:

1. The "alphas" claimed in the option-anomaly literature collapse under a 3-factor IPCA model (avg alpha ≈ 6bp/mo; only 2 of 46 survive Benjamini–Hochberg MHT at 5% FDR).
2. The first IPCA factor is dominated by the **RV−IV** characteristic — zeroing its Γ_β makes the model fail to price 32 other strategies, with alpha rebounding ~1%/month on average.
3. Once transaction costs (30% effective-to-quoted-spread) are layered on, IPCA alphas are negative for *all* 46 strategies.

## Why this matters here

`unusual-whales` already exposes most of the paper's option-side characteristics (IV ATM, IV skew/term, RV−IV via `vol_series.py`, model-free moments via skew tables). The CRI work specifically uses a VRP-style component. If Goyal-Saretto's single-factor reading is right, **most of the cross-sectional option signals we might build are statistical refractions of one underlying RV−IV signal**. That has direct implications for:

- The CRI redesign (`docs/superpowers/plans/2026-05-19-cri-methodology-tune.md`, `2026-05-20-cri-page-enrichment.md`) — confirms RV−IV is doing real work, but suggests other regime-side option signals may be near-redundant.
- The 6-dimension option analysis roadmap (see `MEMORY.md` → `project_six_dimension_option_analysis.md`).
- The scanner's signal-ranking weights (`src/uw_scan/scanner/`) — adding more option-side signals on top of an RV−IV-style score should expect rapidly diminishing returns.

## Files (read in order)

| File | Status | What's in it |
|---|---|---|
| [`00-goal-and-decisions.md`](00-goal-and-decisions.md) | **done** | **READ FIRST.** Goal, four guardrails, what we are and are not doing, success criteria, pinned conventions |
| [`README.md`](README.md) | draft | 1-page overview suitable for sharing |
| [`01-paper-metadata.md`](01-paper-metadata.md) | done | Authoritative title, authors, journal, DOI, working-paper history, verbatim abstract |
| [`02-summary-card-notes.md`](02-summary-card-notes.md) | done | English translation of the bilingual card the user provided; each claim cross-checked against the published paper |
| [`03-methodology.md`](03-methodology.md) | done | IPCA equations (eqs. 2–4), variable construction (46 chars), filters, return definition, transaction-cost overlay |
| [`04-key-results.md`](04-key-results.md) | done | Tables 1, 2, 3, 5; the RV−IV centrality findings (Table 4, Figure 2, conclusion ¶) |
| [`05-replication-plan.md`](05-replication-plan.md) | **reframed** | **Now: four-guardrail audit checklist.** R0/R1/R2 replication tiers preserved in appendix for reference only. |
| [`06-open-questions.md`](06-open-questions.md) | **refreshed** | 16 questions tracked, ~6 closed by reframe (Q2, Q7, Q8, Q9, …), 4 new items added (rate-limit, field parity, watchlist coverage, calendar source) |
| [`scripts/`](scripts/) | done | Persisted probe scripts (`probe_massive.py`, `probe_vx_deep.py`) — reproducible from `uv run --with httpx --with python-dotenv python scripts/probe_*.py` |
| [`07-notebook-scope-and-data-audit.md`](07-notebook-scope-and-data-audit.md) | done | V1 notebook spec (Diagnostics A + B) + 3-layer data verdict + universe/month-end/sign-flip conventions |
| [`09-massive-fundamentals-coverage.md`](09-massive-fundamentals-coverage.md) | done | Massive.com coverage verdict: 15 of 17 paper firm-chars; per-characteristic mapping |
| [`10-data-access-contract.md`](10-data-access-contract.md) | **done** | Interface contracts for `src/uw_scan/research/data_access.py` — universe, panels, look-ahead rules |
| [`13-backtest-design.md`](13-backtest-design.md) | **done** | L1 cross-sectional + L2 per-signal backtester architecture; synthetic-straddle return engine; TC overlay; persistence schema |
| [`14-massive-endpoint-probe-log.md`](14-massive-endpoint-probe-log.md) | **done** | Authoritative endpoint-by-endpoint probe log (raw record behind doc 09's summary) |
| [`_references/goyal-saretto-2024.pdf`](_references/goyal-saretto-2024.pdf) | done | Full RFS-version PDF, 39 pages |

**Numbering gaps reserved:** 08 (redundancy-audit-results, awaits notebook output), 11 (tc-audit, awaits Guardrail-4 audit), 12 (firm-chars-gap, awaits Phase 3), 15 (flow-signal-verdict, awaits Phase 2+3).

## Standing rules for this workspace

- **Quote verbatim or cite a page number** for any claim attributed to the paper. The summary card the user provided already drifts on at least one number (Stock-price alpha 0.15 vs paper's 0.09); don't propagate.
- **Use the published RFS version (2025)**, not the working paper, when citing. SSRN id is `4194384` and was last revised before the final RFS edits.
- **Internet Appendix not yet pulled** — referenced as "IA1–IA5" in the paper; living on the Oxford UP supplementary page. Several robustness checks (delta-hedged puts, straddles, month-end-to-month-end returns) are *only* in the IA. Flag IA-dependent claims as such.
- **Don't conflate "VRP" with RV−IV here.** The paper measures RV−IV with realized vol of log returns (12mo daily, A.3) minus 30-day implied vol from the surface (A.2.1). UW's `vol_series.py` may compute it differently — needs verification in `05-replication-plan.md`.
