# docs/research/gold-sdf-framework — Gold SDF research

Pre-spec research for the `/gold` GOLD COMPASS endpoint. **Read [`README.md`](./README.md) first** — it's the entry point and reading map for the 14 sub-documents in this directory.

## What this directory is

A research foundation, not an implementation. It cross-validates the SDF-based gold framework (viviennaBTC article + Andrew Ang Ch. 11) against primary sources and synthesizes a three-lens model:

- **Lens 1 — Structural flow** *(dominant 2022-present)*: central-bank reserves, ETF holdings, exchange vaults, FX, COT, UW options stress
- **Lens 2 — Cyclical** *(gated by regime)*: real yields, inflation breakevens, DXY, the article's two-force model
- **Lens 3 — Valuation overlay** *(always-on tail-risk flag; never a sizing input)*: Erb-Harvey real-price percentile

Lenses share variance — they are complementary, **not orthogonal**. Position sizing must assume correlated signals until variance accounting proves otherwise.

## What this directory is NOT

- **Not the implementation spec.** Specs live under `docs/superpowers/specs/` once the research lands.
- **Not a backtest.** No model has been fit to data; all claims come from academic primaries, industry research, and direct review of the article.
- **Not complete.** Open questions are tracked in [`10-open-research-questions.md`](./10-open-research-questions.md).

## Status vs. shipped code (2026-05-17)

| Lens | Sub-document | Code path | Status |
|---|---|---|---|
| 1 | `05-structural-flow-factors.md` | `sources/etf_holdings.py`, `sources/comex.py`, `sources/lbma.py`, `sources/cftc_cot.py`, `sources/wgc_etf.py`, `sources/uw_gold_options.py` | Mostly live (Phase A1); `wgc_cb.py` deferred |
| 2 | `06-cyclical-factors.md` | `sources/fred.py`, `sources/gpr.py` | Live (FRED + GPR) |
| 3 | `07-valuation-overlay.md` | computed in `worker/jobs/gold_jobs.py::gold_posture_compute_job` | Live |

Routing into the cockpit: `api/routers/gold.py` → `storage/gold_etf.py` (+ other gold repositories) → `web/app/gold/` and `web/components/gold/` (lens1/lens2/lens3 component groups mirror the research lenses).

## Deferred sources (Phase A1 → v2)

Five of the eight anonymous-CSV sources designed for v1 had moved or paywalled by 2026-05-17 implementation time. Tracking + re-wire plan: [`11-deferred-sources-phase-a1.md`](./11-deferred-sources-phase-a1.md). Most-likely fixes lean on official APIs (Socrata, IMF IFS, SEC N-PORT) rather than scraping issuer pages.

The provider files for deferred sources (e.g., `wgc_cb.py`) stay in the tree so re-wiring is a one-source change, not a structural refactor. Until that lands, the structural-lens CB tiles and the corresponding tables (`cb_gold_reserves_monthly`) stay empty by design.

## When working in this directory

- **Cite primary sources, not the article.** Every empirical claim must trace back to Ang/Cochrane/Erb-Harvey/Baur-Lucey/WGC/FRED rather than to the SDF article itself. The article's directional claims are correct; its specific numbers are not always (see [`02-empirical-claims-validation.md`](./02-empirical-claims-validation.md)).
- **Regime gating is load-bearing.** The article's framework operates only in pre-2022 regimes (gold ↔ real-yield correlation ≈ -0.84). Post-2022 the correlation collapsed (~ 0). Code that consumes Lens 2 must gate on the regime gauge, not assume the relationship is always on.
- **Cost rule:** All required series are free or already paid for. Roughly $0 in new external-data costs — the bottleneck is engineering time, not data subscriptions.
- **Spec promotion path.** When a finding here is ready to ship, draft a spec under `docs/superpowers/specs/` referencing the specific sub-document. Don't grow research files into specs — keep these focused on *what's true*, not *what to build*.
- **Updates over rewrites.** Each finding lives in its own sub-document so the body of work can grow without any single file becoming unwieldy. New findings either extend an existing file or land as a new numbered file with a README link.

## Provider-level conventions

Gold-source rules are documented at the implementation layer: [`src/uw_scan/sources/CLAUDE.md`](../../../src/uw_scan/sources/CLAUDE.md). Highlights that touch research:

- **Backtest lag for COT:** lag to `release_date + 3 trading days`, never `obs_date` (look-ahead).
- **Audit-first persistence:** raw payload + audit row land before normalisation, so a mid-pipeline crash still leaves a trace and we can reconstruct issuer payloads after schema drift.
- **Source-workbook lineage** is preserved for revised monthly workbooks (WGC ETF) — revisions don't overwrite history.
