# src/uw_scan/fundamentals — the fundamental PM lane

The lane runs statement store → features → composite → anchors → desk/reports: raw provider
statements are normalized and hashed into an observation store, derived into features, scored
cross-sectionally into a composite, turned into own-history valuation bands, and finally read by the
per-ticker card, the AI chain desk, and the versioned research reports.

Code lives in `src/uw_scan/fundamentals/` (pure compute), `storage/fundamental_*.py` (plus
`storage/{company_identity,company_sector,earnings_calendar,earnings_reactions,implied_move,research_events,research_reports,research_taxonomy,sec_filing_index,fundamentals_desk}.py`),
`worker/jobs/fundamental_*.py`,
`api/routers/{stock,fundamentals_desk,radar,research_evidence,research_reports}.py`,
`web/components/fundamentals/` and `web/app/fundamentals/`.

**The two lane-wide verdicts.** The composite **orders names cross-sectionally** (rank IC 0.039,
t 2.67 on rows carrying a real `filing_date`) but **cannot time one name against itself**
(within-ticker market-neutral IC −0.0000, all 16 tests fail BH). Own-history **valuation** is the
one thing that times a name: `sales_to_ev` within-ticker 2q IC +0.0744, t 5.77, while
cross-sectional value measured INVERTED in the same universe (`book_to_price` IC −0.0365, t −2.32).
Every surface in this lane is built to respect that split — the card draws no price consequence from
subscore trajectories, and the buy-zone surface lists rather than ranks.

## Module map

| Module                | What it is                                                                                     |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| `statements.py`       | Normalization and integrity checks for provider fundamental statements                          |
| `features.py`         | Raw feature derivation from normalized statement payloads. Pure compute                         |
| `scoring.py`          | Stage-2 scoring: cross-sectional z-scores, composite, and result identity                       |
| `valuation.py`        | Stage-3 valuation anchors: a price band from a name's OWN valuation history                     |
| `valuation_math.py`   | Valuation arithmetic — identity hashing, yields, percentiles, price inversion                   |
| `valuation_policy.py` | Valuation routing and refusal policy — which method a company type gets                         |
| `validity.py`         | Which recorded integrity failures are allowed to reach the math. Pure compute                   |
| `observation_time.py` | When a statement content VERSION became usable — the vocabulary, frozen                         |
| `publication_evidence.py` | Does one stored content version earn a publication date? Pure rule, no I/O                  |
| `card.py`             | Assembly of the per-ticker fundamental card (spec §7, deterministic blocks)                     |
| `fx.py`               | Currency translation for foreign filers' statements                                             |
| `concentration.py`    | Revenue concentration from raw XBRL breakdown rows                                              |
| `underwriting.py`     | Underwriting features (spec §5-v): DIO, SBC/revenue, shares-outstanding YoY                     |
| `dimensions.py`       | Independent research-priority dimensions and their permission. Pure compute                     |
| `claims.py`           | The product claim registry — what each surface is ALLOWED to say (M3.3)                         |
| `chain_nodes.py`      | What a chain analysis node IS, declared as data                                                 |
| `report_delta.py`     | What changed between two report versions. Pure compute, no I/O                                  |

---

## The statement store and the card

### Fundamental PM lane (statement store → composite → card)

`src/uw_scan/fundamentals/` (`statements`/`features`/`scoring`/`valuation`/`fx`/`card`) + `storage/fundamental_{obs,scores,anchors}.py` + migrations `114`/`117`/`118` + `worker/jobs/fundamental_{ingest,scoring,anchors,refresh}.py` (`fundamental_refresh` 18:20 ET, massive-0, gated `UW_SCAN_FUNDAMENTAL_REFRESH_ENABLED` default **on**, chains routing → subscores → anchor bands at zero UW/IB spend; it deliberately does **not** ingest — new filings come from `fundamental_ingest_daily`, with `scripts/backfill/fundamental_ingest_backfill.py` still the manual path) + `api/routers/stock.py` (`/fundamentals`, `/fundamentals/statements`) + `web/components/stock/tabs/FundamentalsTab.tsx` + `web/components/stock/panels/Fundamental*`.

**Three things that will bite:**

1. Observation identity is a `content_hash` that **excludes UW's `inserted_at`/`updated_at`** — include them and every refresh reads as a phantom restatement.
2. The composite **orders names cross-sectionally** (rank IC 0.039, t 2.67 on rows carrying a real `filing_date`) but **cannot time one name against itself** (within-ticker market-neutral IC −0.0000, all 16 tests fail BH), which is why the card presents subscore trajectories as descriptive and draws no price consequence from them.
3. **The statement endpoints and `fundamental-breakdown` spell the same quarter differently** — AAPL's June quarter is `2026-06-30` in one and `2026-06-27` in the other, so filing dates resolve through a ±7-day nearest match (exact first) and `record_statements` fills a NULL `filing_published_at` via `COALESCE` on conflict. Both were bugs: exact matching returned 0 of 885 NULL periods, and a date UW published after first ingest was discarded permanently.

Specs `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md` + `2026-08-12-fundamentals-card-flip-design.md`; verdicts `docs/research/2026-08-12-fundamental-*/`

### Statement ingest — daily calendar-driven + monthly backstop

`worker/jobs/fundamental_ingest_daily.py` (04:20 ET **daily**, uw-0, `UW_SCAN_FUNDAMENTAL_INGEST_DAILY_ENABLED` default **on**, `lookback_days` via `UW_SCAN_FUNDAMENTAL_INGEST_DAILY_LOOKBACK_DAYS`, default 3, plus `forward_days` via `UW_SCAN_FUNDAMENTAL_INGEST_DAILY_FORWARD_DAYS`, default 14) + `sources/earnings_calendar.py` + slugs `EARNINGS_PREMARKET`/`EARNINGS_AFTERHOURS`; the monthly `fundamental_ingest` (03:40 ET on the 2nd) **stays registered on purpose**.

**The two windows are asymmetric and answer different questions:** the BACKWARD one finds statements to ingest (a company files on or after it prints, so only a past date can name a retrievable filing); the FORWARD one ingests nothing and exists solely so `earnings_calendar` holds rows the desk's "what prints next" panel can read — `EarningsCalendarRepository.next_prints` filters `report_date >= today`, so a backward-only scan leaves that panel structurally empty forever (measured 2026-08-29: 2,443 rows, 0 with `report_date >= CURRENT_DATE`) and renders "nothing prints next" out of a question never asked. Forward listings are deliberately NOT folded into `symbols`: a print that has not happened has no statement, and ingesting one spends 4 UW calls per name to retrieve nothing, every run, until the company reports.

**Two more things that will bite:**

1. `premarket`/`afterhours` is the **classified** calendar — a name UW reports as `report_time: "unknown"` appears in NEITHER and there is no combined endpoint on our tier (ISRG, SONY, DJCO, POET verified absent from their own report date), ≈2% of the statement-bearing universe, which is the first reason the monthly sweep survives.
2. The lookback is **outage insurance, not a wait for UW** — a statement is retrievable the day the company reports (100% of reports 2–7 days old, 98.5% over 704 events), so growing it to chase a missing filing date is treating the wrong clock.

The second reason the sweep survives is that only a late full re-pull collects a filing date UW published after first ingest. Costs ~900 UW calls/month against the monthly sweep's 1,800.

Verdict `docs/research/2026-08-23-fundamental-filing-date-recovery/`; plan `docs/superpowers/plans/2026-08-23-fundamental-calendar-ingest-and-filing-dates.md`

---

## The industry desk

### AI chain desk — the question ladder + three 3D scenes

`api/routers/fundamentals_desk.py` (every route is `GET /api/fundamentals/{section}/…`: `capex`/`cases`/`scope` beside `calendar`/`delta`/`matrix`/`profit-pool`/`limits`/`node/underwriting`) + `reports/fundamentals_desk_spine.py` + `storage/fundamentals_desk.py` (`chain_layers`/`non_usd_currencies`/`quarterly_line_item`/`chains_outside_domains`) + `web/app/fundamentals/ai-semi/{page,cases/page}.tsx` + `web/components/fundamentals/*` + `web/lib/fundamentals/{scene,desk}.ts`; e2e `web/tests/e2e/fundamentals-chain-desk.spec.ts`.

**Five things that will bite:**

1. The SECTION ORDER IS THE ARGUMENT (capex -> map -> cases -> valuation -> limits) and question three cannot be answered before question one, so reordering the page changes the claim.
2. A chain's plane is `layer_rank = 0` read from `research_chains` and NEVER from the membership join — the five `dc_buildout` chains carry an empty L3 row plus a ranked stage row holding every member, so a layer derived from memberships calls them stages and drops them off the map.
3. The two funnels share ONE radius scale and `GROWTH_CAP` is a constant, so both render from one component off one response — a per-case scale or a fitted cap breaks the comparison with nothing on screen to show it.
4. The capex panel is **the single place a currency amount is summed across companies** (USD filers only, excluded names printed with the figure) and its demotion in the original spec is deliberately reversed — it is the desk's PREMISE, never its edge, and rising capex is a COST line for the names that spend it.
5. The scene's `unit` is scaled off `min(W, H)` because perspective magnifies a plane's FAR corner (k ~ 1.29), so a width-scaled scene silently clipped L4/L5 while the legend still listed them.

### Fundamentals-industry-desk data spine (durable calendar + reactions + implied move + delta rail)

`storage/{earnings_calendar,earnings_reactions,implied_move}.py` + migrations `144`/`145`/`146` (`earnings_calendar`, `earnings_reactions`, `implied_move_daily`) + `worker/jobs/{earnings_reactions,implied_move_snapshot,fundamental_change_events}.py` (19:41/20:45/21:15 ET, massive-0, `UW_SCAN_{EARNINGS_REACTIONS,IMPLIED_MOVE_SNAPSHOT,FUNDAMENTAL_CHANGE_EVENTS}_ENABLED`, all default **on**) + `fundamentals/underwriting.py` (`underwriting_features` — `dio`/`sbc_to_revenue`/`shares_outstanding_yoy`, descriptive-only, outside `FEATURES`) + backfills `scripts/backfill/{earnings_calendar,earnings_reactions,implied_move}_backfill.py`.

`earnings_calendar.session` is `'premarket' | 'afterhours' | NULL`; the ~2% UW never classifies land with `session=NULL, source='statement_obs'` via `fundamental_ingest_daily.persist_unknown_statements`.

**Two things that will bite:**

1. `filing_published_at` (what a `statement_obs` row's `report_date` actually is) is a **filing** date, not a print date, and the drift is ONE-DIRECTIONAL and fat-tailed — a filing lands on or after its print (0 of 57 sampled tickers ever before it), but UNH's 2026-07-16 print was filed 25 days later. A symmetric ±10-day window sized from a 26-ticker sample's observed max was FALSIFIED by the very next sample, so the guard is asymmetric and sized from STRUCTURE instead: `FILING_LOOKBACK_DAYS = 45` in `fundamental_ingest_daily.py` (half the ~91-day inter-print spacing, so a backward-only window can never reach a neighbouring quarter) plus `FILING_FORWARD_TOLERANCE_DAYS = 3` — so `earnings_reactions_compute` and `implied_move_snapshot` both exclude `source='statement_obs'` rows outright (never compute a reaction or an implied move against a filing date) and count the exclusion in their own `excluded_statement_obs` counter, which is the correct outcome for that ~2%, not a bug.
2. `implied_move_shift`'s covering expiry is RE-PICKED every night, so its `detail_jsonb` carries both nights' `expiry`/`atm_iv`/`iv_basis` (not just the pct) so a covering-expiry re-pick reads apart from a genuine vol move.

---

## Valuation, routing, and concentration

### `company_type` routing + the financials refusal

`fundamentals/valuation.py` (`FINANCIALS`, `FINANCIALS_REFUSAL`, `TYPE_YIELD`) + `worker/jobs/fundamental_anchors.py` (`TICKER_TO_TYPE` name override, `SECTOR_TO_TYPE` = argon chain taxonomy, `VENDOR_SECTOR_TO_TYPE` = GICS-style, `seed_company_types`) + `storage/company_sector.py` + `worker/jobs/company_sector_refresh.py` (04:40 ET **daily**, uw-0, `UW_SCAN_COMPANY_SECTOR_REFRESH_ENABLED` default **on** — daily because it fills a cache rather than accruing a series: it asks only names with no row, so the first run costs one UW call per universe ticker and every run after it costs zero, which is what makes the table non-empty the morning after a deploy instead of up to 31 days later) + migrations `123` (cache) / `124` (`method` nullable).

**Three things that will bite:**

1. The two sector vocabularies collide on **`Energy`** — argon's chain means power generation (`power_infra`/EV-EBITDA), GICS means oil and gas — so they route through SEPARATE maps and must never be merged.
2. `financials` has **no `TYPE_YIELD` entry by design** (EV is not a meaningful denominator for a deposit-funded balance sheet, so there is no method to name, and `method` is NULL rather than a sentinel).
3. The anchors job must **persist** the refusal, because a skipped ticker renders as "no `company_type` routed — a gap in our coverage", false in every clause for a bank.

A name leaves the refusal **only** by routing to a market-cap-denominated method (`fcf_yield`), never by exemption — PYPL is the one entry, and a test fails if an override ever points at an EV-denominated type. Measurement: `docs/research/2026-08-19-valuation-refusal-anatomy/`

### Valuation buy-zone surface (cross-name list of own-history bands)

`storage/fundamental_anchors.py` (`in_buy_zone`/`band_coverage` — the only cross-name reads on `valuation_anchors`) + `api/routers/scanner.py` (`GET /scanner/value`, warm-store only, zero UW/IB) + `web/components/scanner/value/ValueSubTab.tsx` + check `scripts/research/valuation_band_coverage_check.py`.

**It LISTS, it must never RANK** — own-history value measured (`sales_to_ev` within-ticker 2q IC +0.0744, t 5.77) but cross-sectional value measured INVERTED in the same universe (`book_to_price` IC −0.0365, t −2.32), so no `sort` parameter over `spot_percentile` or depth may ever be added; the ordering is newly-entered-first then alphabetical.

Two more traps: `spot_percentile` is a **yield** percentile (0.80 = CHEAP) and reaches the screen only through `rankPhrase`; and `entered` is three-state, where `null` means "no prior band in the 30-day lookback" and must never render as NEW — on 2026-08-17 that was 29 of 98 names, all present because the panel widened 256 → 414.

Plan `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` (PR 4)

### Revenue concentration (segment / geography) — **descriptive only**

`fundamentals/concentration.py` (derivation, read-time) + `storage/fundamental_concentration.py` + migration `122` (`revenue_breakdown_obs`, content-hash identity) + `worker/jobs/fundamental_concentration_capture.py` (04:10 ET on the 3rd, uw-0, `UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED` default **on**, ~450 UW calls/run) + `api/routers/stock.py` (`/fundamentals/concentration`) + `web/components/stock/panels/FundamentalConcentration.tsx`.

**Not a signal and never a composite input** — the top share moves a median 1.20pp/quarter against p90 17.5pp of annual/quarterly basis contamination; the level is a factor loading, not alpha (spec §896 weight withdrawn 2026-08-18).

Three things that will bite: group by the XBRL **axis**, never `rev_group`; the denominator is the period's untagged consolidated row from **any** group; and annual-row detection compares against a period's **4 nearest neighbours**, never the ticker's lifetime median — a grower's recent quarter clears 2.5x its own median on growth alone.

Plan `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` (3 recorded deviations)

---

## The Fundamental PM Research System

### Publication evidence (SEC EDGAR)

`sources/sec_submissions.py` + `fundamentals/publication_evidence.py` + `storage/sec_filing_index.py` + `worker/jobs/{sec_filing_index_refresh,fundamental_publication_evidence}.py` + migration `134` + backfill `scripts/backfill/sec_publication_evidence.py`; verdict `docs/research/2026-08-25-sec-publication-evidence/`.

**Three things that will bite:**

1. EDGAR's `filings.recent` is a WINDOW — the archives live in `filings.files[]` and a walk that stops at `recent` sees only the last ~1,000 filings.
2. `httpx` must be built with `trust_env=False` or macOS proxy settings kill `www.sec.gov` with `SSL_ERROR_SYSCALL`, and a descriptive User-Agent carrying a contact email is required or EDGAR 403s.
3. The fiscal-period join needs **±7 days** (52/53-week calendars — NVDA's April quarter is `2026-04-26` at SEC and `2026-04-30` in argon), which took yield from 13.4% exact to 93.9%.

Measured: 0 → 73,994 `true_pit` claims over 396/401 tickers, 2003-12-31 → 2026-07-31

### Validity policy + typed provenance + company identity

`fundamentals/validity.py` (`CHECK_EFFECTS`, `FEATURE_WINDOW`, `VALIDITY_BY_CODE_VERSION`) + `storage/{fundamental_provenance,company_identity}.py` + migrations `135`/`136` + `scripts/seed_fundamental_method.py --activate-v2`.

**The validity policy is read FROM the engine version**, so a row cannot claim a method it did not run; `fundamentals-v1` = off, `fundamentals-v2` = exclude. A violated `total_revenue` poisons 4 quarters of TTM and `rev_growth` reaches 8, which is what `FEATURE_WINDOW` encodes. Provenance FKs are directional on purpose: `result_id` CASCADE, `obs_id` RESTRICT — cited evidence is undeletable

### Run ledger + research-priority dimensions

`storage/fundamental_runs.py` (`request_hash` EXCLUDES the clock, so a repeat asks the same question rather than queueing a second run) + `worker/jobs/fundamental_run.py` + `fundamentals/dimensions.py` (`DIMENSION_FEATURES`, `PROGRAM_CEILING`) + `storage/fundamental_dimensions.py` + migrations `137`/`138`.

**`PROGRAM_CEILING` is `research_priority`** and migration 138's CHECK forbids `investment_ranking` — the ceiling is unrepresentable in the store, not merely unused

### Research Radar + chain matrix (surfaces)

`models/radar.py` (six-state `FundamentalResultState`) + `api/routers/radar.py` + `web/app/radar/page.tsx` + `components/radar/RadarTable.tsx`; the chain index folded into the desk — `web/app/chains/page.tsx` now redirects to `/fundamentals/ai-semi` and `ChainMatrix.tsx` is deleted, so only `web/app/chains/[chain]/page.tsx` survives.

**`no_compatible_run` is not `no_coverage`** — collapsing them is how "the job never ran" gets read as "this company has no fundamentals", a statement about a real business Argon is not entitled to make

### Chain taxonomy + evidence-backed exposure

`storage/research_taxonomy.py` + `worker/jobs/research_taxonomy_seed.py` (`TAXONOMY_V1`) + migrations `139`–`140` + seed `scripts/backfill/research_taxonomy_seed.py`; verdict `docs/research/2026-08-25-chain-exposure-yield/`.

**A magnitude requires a disclosure** — a CHECK forbids one without `status='disclosed'` and a named basis. Measured 39 chains / 316 memberships / **4 with a disclosed magnitude (1.3%)**. `chain_membership` is grained `(chain, layer, ticker)`: a name in two layers appears twice, so every count and every mean must dedupe to distinct tickers or a numerator will exceed its own denominator

### Typed event ledger + deterministic risks + the discovery gate

`storage/research_events.py` + `worker/jobs/research_events_derive.py` + `api/routers/research_evidence.py` + migration `142`; verdict `docs/research/2026-08-25-evidence-discovery-gate/`.

**Six classes live, eight killed, and the kills are the deliverable** — a killed class REFUSES writes rather than warning. Two clocks travel with every event: `occurred_at` vs `first_known_at`, and a CHECK forbids the second preceding the first

### Versioned research reports (the north-star deliverable)

`storage/research_reports.py` + `fundamentals/report_delta.py` + `worker/jobs/research_report_{assemble,scaffold}.py` (three shapes: company / comparison / chain) + `api/routers/research_reports.py` + `models/reports.py` + `web/app/reports/` + `components/reports/ReportView.tsx` + migration `143`; completion test `docs/research/2026-08-25-research-report-completion/` (run `scripts/research/research_report_completion_test.py`).

**Three things that will bite:**

1. A report REPLAYS by reading its stored blocks, never by re-assembling — re-assembly under today's data is a different answer wearing an old version number.
2. The delta reports a MANIFEST change first and apart from value moves, because a composite that fell because the engine changed is not news about a company.
3. `check_single_basis` raises before anything is written if a block's evidence disagrees with the frozen manifest.

Republishing unchanged content is a no-op, so a double-click cannot manufacture history. A comparison keys on its SORTED ticker set and names every requested ticker in its coverage block, scored or not
