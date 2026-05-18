# Gold SDF Framework — Changelog / Review Responses

A running log of substantive changes to the research foundation, with rationale and source. Each entry lists what changed, which files were touched, and why.

---

## 2026-05-18 — Live data-quality reconciliation

**Source:** Local warm-store audit on branch `feat/gold-uw-etf-flows`.

### Code Remediation Update

The first implementation pass closed the local/provider issues that did not
require a new licensed or alternate macro source:

- CFTC COT ingestion now uses the official disaggregated futures-only commodity
  feed for the current row and the CFTC Public Reporting Environment Socrata
  dataset `72hh-3qpy` for 400-day history, filtered to gold contract `088691`.
- `gold_posture_daily.cot_mm_4w_change_sigma` is now computed from persisted COT
  history.
- `wgc_etf_monthly_canonical` now provides latest-revision WGC rows; GLD
  canonical count is 257 months versus 16,362 raw revision rows.
- `data_freshness_jsonb` now carries `status=ok/missing` so unresolved sources
  are visible instead of silently absent.
- `gold_posture_compute_job()` defaults to the latest GLD market date, not
  calendar today.
- `gold_posture_daily` now has `row_status` / `superseded_reason`; normal latest
  state and replay skip invalidated rows, while the audit rows remain in place.

Remaining source decisions: IMF/IFS central-bank reserves, COMEX vaults, and UW
options history/dealer-gamma semantics.

The Phase A1 docs were updated to reflect the actual current data state rather
than the initial handoff snapshot. GLD daily holdings and the WGC monthly ETF
corpus are now available. The initial reconciliation noted COT, CB reserves,
COMEX, freshness, and replay gaps; the implementation update above records
which of those are now closed.

### Changes

- Added [14-data-quality-remediation.md](./14-data-quality-remediation.md) with
  a source-by-source issue table, root causes, resolution order, and definition
  of done.
- Updated [README.md](./README.md) to point at the live data-quality caveat.
- Updated [11-deferred-sources-phase-a1.md](./11-deferred-sources-phase-a1.md)
  so GLD daily holdings and CFTC COT are no longer described as deferred, while
  CB reserves and COMEX remain unresolved.
- Updated [12-wgc-etf-flow-corpus.md](./12-wgc-etf-flow-corpus.md) and
  [13-wgc-etf-flow-mining.md](./13-wgc-etf-flow-mining.md) to make WGC
  canonicalization mandatory before factor use.
- Updated [09-data-sources-catalog.md](./09-data-sources-catalog.md) to separate
  working sources, blocked sources, authenticated/export-backed sources, and
  sources needing alternate open-data rewires.
- Updated [docs/handover/2026-05-17-gold-v2-codex-handover.md](../../handover/2026-05-17-gold-v2-codex-handover.md)
  so future agents do not follow stale D2 guidance.

---

## 2026-05-17 — Phase A1 ingestion field notes (deferred sources)

**Source:** Implementation pass against the v1 plan in [09-data-sources-catalog.md](./09-data-sources-catalog.md).

Five sources designed for anonymous CSV ingestion failed during the 2026-05-17 warmup (WGC CB reserves moved behind login, all four ETF holdings endpoints returned 301/404, COMEX scraping hit 403, the CFTC fetcher had a placeholder URL pointing at financial futures instead of commodities, and FRED's LBMA gold-fix series was retired). Each failure mode + concrete re-wire path documented in the new [11-deferred-sources-phase-a1.md](./11-deferred-sources-phase-a1.md). Sequencing recommendation included so the v2 pass can pick them up by signal-to-effort rather than rediscovering the failures.

Key meta-observation: anonymous CSV endpoints in this domain have a ~12-month half-life. Sources that survived the 18 months between catalog and ingestion (GPR, LBMA) survived only because we found new endpoints during ingestion. v2 should bias toward IMF / SEC / Socrata APIs and an auth path for the canonical industry sources.

---

## 2026-05-16 — Codex adversarial review response

**Source:** [docs/reviews/2026-05-16-gold-research-codex-review.md](../../reviews/2026-05-16-gold-research-codex-review.md)

The Codex review surfaced 14 substantive issues across methodology framing, the quant-model spec, missing factors, and the scope decision. Patches below preserve the core direction (regime-aware multi-lens framework with research-first scope) but downgrade overconfident claims, fix internal contradictions, add the largest missing factor class (COT positioning), and replace Option A/B with Codex's recommended Option A-prime phasing.

### Summary of accepted findings

| # | Codex finding | Action taken | Files touched |
|---|---|---|---|
| 1 | Post-2022 -84%/-7% correlation collapse overstated — RBC statistic is a clue, not a measurement | Downgraded language; required internal replication before any production quote | README, 03, 10 (new Q20) |
| 2 | "Orthogonal layers" framing overstates independence — lenses share variance | Renamed "three layers" → "three lenses / signal families"; added explicit shared-variance section; required variance accounting for v2+ sizing | README, 04, 04a, 10 (new Q23) |
| 3 | T5YIFR > 2.8% as "unanchored" is article folklore, not validated | Relabeled article zones; flagged thresholds as configurable defaults pending empirical calibration | 04, 06, 10 (new Q24) |
| 4 | Multi-task XGBoost does NOT quadruple N — claim was wrong | Reframed v4 as partial-pooling / information-sharing, not literal N multiplication; moved trees to challenger slot behind state-space | 04a, 10 (Q15, R5 revisions) |
| 5 | Q13 — Codex recommends Option A-prime (research cockpit with audit scaffold from day one, then model) | Adopted A-prime as recommended path; described A1/A2/A3 phasing | 04a, 10 (Q13) |
| 6 | Lens 3 contradiction — 04a had vol-scaler, 07 says never a sizing input | Removed Lens 3 vol-scaler from 04a; Lens 3 is now exclusively a tail-risk overlay; deferred valuation-conditional sizing to backtest validation | 04, 04a, 07, 10 (new Q22) |
| 7 | F10 IC=0.73 dismissal correct but needs replication-trap note | Added explicit replication-trap protocol — compute wrong-but-plausible IC versions to pin down the original construction | 08 |
| 8 | COT positioning is the largest single factor omission | Added F18 (MM net percentile), F19 (commercials net percentile), F20 (MM 4-week change) as Lens 1 inputs | 04, 04a, 09 |
| 9 | UW options skew = differentiated repo edge; persist from v1 | Added F21 (GLD 25Δ put-call IV spread) with v1 persistence policy + v2 model promotion | 04, 04a, 09 |
| 10 | GOFO discontinued 2015 — cannot include as direct feed | Documented as discontinued; use COMEX/LBMA/SGE proxies; v2 research item for lease-rate proxies | 09 |
| 11 | Sharpe hurdles under-specified | Replaced single-Sharpe gates with multi-metric validation basket (deflated Sharpe, PBO, regime-conditional, benchmark-relative, turnover-adjusted, calibration) | 04a, 10 (Q14) |
| 12 | Embargo internally inconsistent (5 vs 10 days) and should scale with horizon | Standardized as horizon-scaled (max(10, 0.25 × horizon)); flagged for empirical tuning | 04a, 10 (Q18) |
| 13 | "Recommendation" / "position size" language premature without backtest validation | v1 uses posture / risk / scenario language only; numerical sizing deferred to v2+ post-backtest | 04, 04a, 06 |
| 14 | B position conceptually muddled — strategic CB context vs event hedge are different trades | Split B into "strategic allocation context" (long-horizon) and "event hedge context" (Baur-Lucey 15-day decay) | 04, 04a |

### Findings noted but not yet incorporated (deferred to later passes)

| Codex finding | Disposition |
|---|---|
| Mining cost-curve dynamics | Defensible v1 omission per Codex; add as v3 valuation overlay study |
| Indian wedding-season seasonality | Small v1 calendar factor TBD during dashboard UX design; not added as code yet |
| BIS gold swap activity | Defensible v1 omission; mentioned in 05 caveats only |
| Expanding vs rolling vs regime-weighted training window | Logged as open question for Phase A3 (Q21) |
| Stop using "recommendation" language across dashboard copy | Doc-level guidance updated (04, 04a, 06); UI copy enforcement will happen at spec time |
| WGC 2025 figure source-pinning | Pinned to FY2025 page in 03 ("the 2022-2024 1000+t pace fell to 863t in 2025") |
| Non-synchronous close handling | Documented in 04a and 09 as mandatory backtest feature |

### Codex findings that were already correct in original draft

- F10 IC=0.73 dismissal (we already flagged it; Codex agreed and asked us to add the replication-trap protocol, now done)
- Linear baseline first (we already had this; Codex agreed)
- Walk-forward purged k-fold validation (we already had this; Codex sharpened the embargo specification)
- Point-in-time data requirement (we already had this; Codex extended it to release-calendar modeling and non-synchronous close handling)
- Online decay monitoring (we already had this; Codex affirmed it belongs even in research view as prediction-audit rows)

### Files modified

- `README.md` — softened headline finding #3, renamed lenses, acknowledged shared variance, added COT/UW-options to Lens 1 sketch
- `03-post-2022-regime-break.md` — replaced "not sampling noise" with measured language; added explicit replication-requirement section; updated "implications" section to use posture language and require replication before quoting magnitudes
- `04-three-layer-architecture.md` — added naming note (three lenses), shared-variance section, Lens 3 correction note, B-position split, posture-vs-recommendation language; added COT and UW options to Lens 1; switched Layer→Lens throughout
- `04a-quant-model-spec.md` — large rewrite: corrected mapping table (Lens 3 not vol-scaler); added COT (F18-F20) and UW options (F21) to feature set; reshuffled model sequence to put state-space before XGBoost; reframed v4 as partial pooling (not 4×N); rewrote Lens 3 section as tail-risk overlay only; replaced position-sizing composition with posture composition (v1) + deferred sizing (v2+); expanded backtest harness with release-calendar, non-synchronous close, target-definition, feature-selection leakage, turnover/capacity, deflated Sharpe, PBO, benchmark panel; rewrote Option A/B section as Option A-prime three-phase plan; updated viviennaBTC comparison table
- `06-cyclical-factors.md` — relabeled "regime classifier" as "article zones (heuristic, not validated)"; flagged thresholds as configurable defaults; replaced "Action layer" with "Posture layer"; added calibration TODO; updated "What we explicitly do NOT do (v1)" list
- `07-valuation-overlay.md` — added "Authoritative" callout reinforcing the never-sizing-input rule and noting the resolved contradiction with 04a
- `08-viviennabtc-factor-critique.md` — added replication-trap protocol for F10 IC=0.73 recomputation
- `09-data-sources-catalog.md` — added CFTC COT section (full entry, Lens 1); added UW options stress section with v1 persistence policy; added GOFO discontinued note; updated cost-summary table; updated ingestion-cost table with COT + UW options
- `10-open-research-questions.md` — Q13 updated with Option A-prime; Q14 revised hurdle to multi-metric basket; Q15 reframed pooling as information-sharing; Q18 revised embargo to horizon-scaled; R5 revised again (state-space before trees); added Q20 (correlation-collapse internal replication), Q21 (CV fold count + window scheme), Q22 (Lens 3 sizing role), Q23 (shared-variance accounting), Q24 (article-zone threshold calibration), Q25 (multi-horizon labels), Q26 (target-definition lock-in), Q27 (feature-selection leakage discipline), Q28 (turnover/capacity reporting), Q29 (benchmark comparison definitions)
- `CHANGELOG.md` — new file (this one)

### Unresolved decisions remaining after this pass

The most important decision still open is **Q13: Option A vs B vs A-prime**. The patches above adopt A-prime as the *recommended* path but the final selection belongs to the user. Other open questions accumulated during this pass (Q20-Q29) are mostly Phase A2/A3 tasks and do not block Phase A1 implementation work.

A complete current list of open questions lives in [10-open-research-questions.md](./10-open-research-questions.md).
