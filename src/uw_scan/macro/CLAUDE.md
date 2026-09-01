# src/uw_scan/macro — point-in-time macro domain states

Four domain engines settle independently — **inflation**, **rates**, **USD**, **gold** (MC0–MC3) —
each on its own schedule, each answering only from evidence it can prove it could have seen.
`available_at <= as_of` is the universal predicate across the whole lane: every read, every fixture,
every replay. A snapshot assembler decides afterwards whether the four answers are one coherent
chain; there is **no composite, ever**.

Code lives in `src/uw_scan/macro/` (pure engines + assembly), with ingestion in
`sources/{fred_macro,bis_eer,cftc_tff,treasury_supply}.py` and the FOMC/SEP source family,
persistence in `storage/{macro_context,macro_domain_state}.py`, jobs in
`worker/jobs/{macro_series_ingest,macro_market_layer_ingest,macro_state_jobs,macro_policy_jobs,rates_jobs}.py`,
and the API in `api/routers/macro.py`. The web surface is `web/components/macro/` +
`web/app/macro/[tab]/`.

## Module map

| Module                 | What it is                                                                        |
| ---------------------- | --------------------------------------------------------------------------------- |
| `contracts.py`         | Contracts shared by the point-in-time macro domain engines                         |
| `evidence_store.py`    | Reading persisted evidence back into the shape the domain engines consume          |
| `confidence.py`        | The confidence a domain state is entitled to, given what it actually knows         |
| `transforms.py`        | Publisher transforms, computed on the calendar rather than on row positions        |
| `inflation.py`         | Point-in-time inflation state                                                      |
| `rates.py`             | Point-in-time policy and rates state                                               |
| `rates_market.py`      | The rates market layer as evidence: Treasury supply and futures positioning        |
| `rates_rules.py`       | Horizon resolution and the rules that fire when the rates evidence disagrees       |
| `rates_sub_states.py`  | The rates market sub-states: supply, positioning, plumbing                         |
| `usd.py`               | Point-in-time USD transmission state                                               |
| `gold.py`              | Gold's declared inputs, and the manifest that proves what was read                 |
| `gold_state.py`        | The gold domain state: whether the relationship Lens 2 rests on is in force        |
| `gold_ingest.py`       | Gold's own two series, promoted from the warm store into the evidence store        |
| `policy.py`            | Pure assembly of independent policy paths                                          |
| `policy_report.py`     | Point-in-time policy comparison assembly from immutable observations               |
| `snapshot.py`          | The macro context snapshot: four domain answers held as ONE answer                 |
| `snapshot_assembly.py` | Decide whether four domain answers are one coherent chain                          |

---

## The domain engines

### Point-in-time macro states (MC0–MC3: inflation / rates / USD)

`src/uw_scan/macro/` (`contracts`, `confidence`, `evidence_store`, `inflation`, `rates`, `rates_market`, `rates_sub_states`, `usd`, `gold`) + `sources/{fred_macro,bis_eer,cftc_tff,treasury_supply}.py` + `storage/{macro_context,macro_domain_state}.py` + migrations `115`–`131` + `worker/jobs/{macro_series_ingest,macro_market_layer_ingest,macro_state_jobs}.py` + `api/routers/macro.py` (`/inflation`, `/rates`, `/usd`, `/gold`).

**Five things that will bite:**

1. `available_at <= as_of` is the universal predicate and the ONLY availability a FRED row has is its `realtime_start`, so a fixture or query that collapses a period to its current vintage silently makes every historical replay empty.
2. `request_window()` splits on the contract's **frequency**, so a daily series is bounded at `DAILY_VINTAGE_START` (FRED 400s the unbounded window) while a monthly one is not.
3. `DTWEXBGS` is a **weekly release carrying daily observations**, so its cadence is 7 and a window expressed in observation COUNT means a different calendar span on each series (63 obs is a quarter on the anchor and 63 months on `RTWEXBGS`).
4. A domain must never re-read what an upstream owns — USD consumes `UpstreamState` and raises if handed an upstream-role observation.
5. Every `*_as_of` reader carries a SECOND point-in-time clause, `macro_evidence_invalidations.invalidated_at <= as_of` (`_NOT_INVALIDATED`, migration `131`) — a new reader added without it will keep serving evidence the desk has since disowned, and one added with the filter but WITHOUT the clock will silently rewrite history instead of ending it.

`fetch_macro_observation_history` is the deliberate exception: the audit view MARKS invalidated rows and must never filter itself. `vintage_to` is INCLUSIVE, so a range cannot say "strictly before instant X" — name the last bad vintage.

Specs `docs/superpowers/archive/specs/2026-08-18-inflation-rates-state-design.md`, `2026-08-21-rates-market-layer-design.md`, `2026-08-12-usd-gold-state-design.md`, `2026-08-24-macro-evidence-invalidation-design.md`

### MC1 official policy-path evidence (FOMC statement + SEP)

`worker/jobs/{macro_policy_jobs,macro_policy_rows,rates_jobs}.py` (ingestion orchestration / observation-row shaping / US rates mirror + snapshot) + `sources/{fomc_statement,fomc_text,fed_sep,fed_sep_provider,fed_sep_tables}.py` + `sources/fomc_release_{census,contracts,discovery,dom}.py` (typed discovery of the official release URLs). Scheduled 19:00 / 19:05 / 19:10 ET daily on **massive-0** (`_should_schedule_macro_policy_ingest`), each leg separately gated by `UW_SCAN_MACRO_{FOMC,SEP,SME}_INGEST_ENABLED` — all three default **off**

---

## The desk

### Macro desk (four domain states + the chain verdict, and the merged Gold/Rates/Macro tabs)

**Current product contract:** `docs/superpowers/specs/2026-08-30-macro-desk-signal-first-design.md`. The captured Claude HTML and the intermediate pixel-port plans are historical and intentionally removed; executable tests are the maintained visual contract.

**Overview (tab 00).** `web/app/macro/[tab]/page.tsx` tab 00 (`web/app/macro/page.tsx` is now only a redirect to `/macro/overview`) + `web/components/macro/OverviewDesk.tsx` + `web/components/macro/overview/{Zone,chain,zone1,zone2,zone3}.tsx` + `web/components/macro/types.ts` + `web/lib/api.ts` (`macroDomainState`, `macroContextSnapshot`) + `web/tests/unit/macroDesk.test.tsx`. Reads `/api/macro/{inflation,rates,usd,gold}` for the cards and `/api/macro/snapshot` BESIDE them for the chain verdict (migration `130`) — **no composite, ever**: averaging four differently-grounded answers hides the contradictions the cards exist to show, and a test asserts the desk's own chrome carries no score/allocation/probability. Each domain settles independently (four engines, four schedules) and the empty slot is three-state — answered / request failed / never computed. The snapshot is fetched beside the cards, never instead of them: it answers the one question no card can — whether the four belong together — and its own failure renders as `macro-chain-unassembled`, never as a clean chain.

**Entry points (all tabs).** `web/components/macro/{ReplayControl,ReplayStatus,MacroTabBar}.tsx` + `web/components/macro/{tabs,replay}.ts`, `web/components/macro/domain/{BoardPanel,ConfidencePanels,FactorTable,InflationPanels,UsdPanels,FactorExport,EnergyProposal}.tsx` + `web/components/macro/domain/confidence.ts`, `web/components/gold/*`, `web/components/rates/{deskShared,FedDesk,CurveDesk}.tsx` + `web/components/rates/RatesDesk.module.css`, and `web/app/macro/{layout,[tab]/page,[tab]/goldTab}.tsx` + `web/app/macro/board.css`.

**Invariants.** `VALID_TABS` is the route/display registry and operator tabs are its audience-filtered subset; replay clocks stay endpoint-specific (`as_of`, `computed_at`, exact `obs_date`); every panel declares Live/Derived/Planned/Reference provenance; implementation identifiers remain audit metadata, not visible copy; Frenzy meeting bars render only publisher-supplied distributions and never synthesize odds; no supported desktop width may create horizontal scrolling; and a label/value/unit or formula operator/operand group stays on one line whenever its intrinsic width fits.

---

## Gold Compass

### Gold Compass — code

`api/routers/gold.py` + `storage/gold_etf.py` + `worker/jobs/gold_jobs.py` + `sources/{fred,gpr,lbma,comex,etf_holdings,uw_gold_options,cftc_cot,wgc_etf,wgc_cb}.py` + `web/app/macro/[tab]/goldTab.tsx` (macro desk tab 05; `/gold` 308s there and `web/app/gold/page.tsx` is gone) + `web/app/gold/replay/[date]/` (kept) + `web/components/gold/*`

### Gold Compass — research / sources docs

`docs/research/gold-sdf-framework/CLAUDE.md` (3-lens model, status vs. shipped, deferred sources) + `src/uw_scan/sources/CLAUDE.md` (per-source status + failure modes)
