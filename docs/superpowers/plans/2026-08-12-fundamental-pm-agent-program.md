# Fundamental PM Agent — Program Plan

> **Status:** active program plan. This is the cross-phase roadmap, not a claim that one PR can
> deliver the system. Every build milestone below gets its own child implementation plan before
> code starts.

**Goal:** turn Argon into a trustworthy, extensible research surface where an operator can ask about
a company, an industry chain, or a narrow sub-chain and receive a versioned, evidence-linked report
covering fundamentals, valuation, score dimensions, catalysts, risks, technical context, and explicit
unknowns.

**Architecture:** Argon owns point-in-time facts, deterministic computations, typed jobs, audit
results, report persistence, permissions, and UI. Model providers may synthesize prose over those
fixed outputs but may not change facts, valuation anchors, scores, taxonomy evidence, or method
parameters. A later external harness may plan and trigger bounded research workflows through narrow
Argon command APIs; it does not receive raw database write access.

**Primary design:** `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`

**Tech stack:** Python 3 via `uv`, FastAPI/Pydantic v2, psycopg/Postgres, APScheduler workers,
Next.js/React/TypeScript, existing Argon provider runners, SEC/UW/Massive/livewire inputs, and
optional separately licensed research datasets.

---

## 1. Program boundary

This program has four successive products. They must not be collapsed into one PR or one release:

1. **Deterministic research engine** — point-in-time observations, financial derivations, valuation
   anchors, score dimensions, confidence, and provenance.
2. **Decision surfaces** — a single-stock fundamental card and a generalizable industry-chain view.
3. **Audited research reports** — structured narrative, claims, evidence links, versions, deltas,
   and publication gates.
4. **Agent harness** — a later control plane that interprets a research request, constructs a bounded
   task graph, calls approved Argon jobs, and produces or refreshes report drafts.

The following are explicitly outside the first three products:

- automatic trading or order staging;
- an automatically reweighted score;
- autonomous edits to valuation assumptions or taxonomy facts;
- an implied promise that a score forecasts returns;
- mandatory dependence on Sharadar, LSEG, or FactSet;
- a ranked long/short book.

The work remains aligned with Argon's goal ladder:

- deterministic facts and surfaces belong to Stage 1, trustworthy foundation;
- the report control plane and self-tending harness belong to Stage 2;
- recommendations or proposals require separate, stronger gates and are not implied by this plan.

## 2. Current state and evidence boundary

Snapshot at the plan baseline, commit `d912d5d` on 2026-08-12:

| Area | State | Evidence / constraint |
|---|---|---|
| P0 persistence bug | **landed** | PR #328 fixed `fundamentals_refresh` transaction behavior |
| P1a provider/data probes | **landed** | PR #329 committed coverage, field-contract, UW, and SEC probes |
| Fundamental method validation | **landed** | PR #329 found the composite informative at broad width but noise at core-25 width |
| Valuation-control follow-up | **parallel research branch** | `research/fundamental-valuation-control`; not part of this plan branch baseline |
| P1b PIT ingest | **not started** | no immutable fundamental observation tables or canonical views yet |
| P2 valuation/score runtime | **not started** | only design and research artifacts exist |
| P3 fundamental card | **not started** | no production API or UI surface yet |
| P4 concentration/edge work | **not started** | must begin with a discovery gate |
| P5 narrative/audit queue | **not started** | current trade-insight queue is not a legal or semantic parent |
| General industry research | **taxonomy skeleton only** | current watchlist has layer/chain membership, not a versioned exposure graph |
| Versioned report object | **not started** | a narrative row is not yet a report control plane |
| Loop harness | **deliberately deferred** | §10 of the primary design; not a missing task in the current research PR |

The current broad-universe validation supports a descriptive product, not an unrestricted ranking:

- the 245-name run found measurable two-quarter ordering;
- the core-25 AI cohort is too narrow for defensible cross-sectional ranking;
- survivorship bias remains because current sources do not carry a complete delisted universe;
- the study has not modeled turnover, costs, capacity, or borrow;
- the valuation-control branch indicates that simple value directions are metric- and regime-specific;
- historical estimate revisions have not been tested with a true PIT consensus dataset.

No later phase may silently strengthen those statements. Stronger claims require their own recorded
evidence and gate.

## 3. Non-negotiable invariants

### 3.1 Evidence and time

1. Every source fact records provider identity, economic period, publication/knowledge time, first
   observation time, and source payload identity.
2. A restatement creates a new immutable observation. It does not overwrite the fact consumed by an
   old report.
3. Point-in-time queries filter on when the market could have known the fact, not when Argon fetched
   it.
4. Provider disagreements are persisted and rendered; canonical selection is rule-based and
   versioned.
5. A missing or invalid input produces `na` with a reason. No model fills it by plausibility.

### 3.2 Deterministic method

1. Python computes every number.
2. Every deterministic output carries `engine_version`, `inputs_hash`, and exact source observation
   references.
3. Same method plus same inputs produces the same result.
4. Method parameters are immutable per version and activated through one explicit pointer.
5. An agent may request recomputation but cannot edit the active method or its weights.

### 3.3 Model behavior

1. Models consume a bounded, persisted payload.
2. Models cannot move valuation anchors, score values, source facts, or relationship confidence.
3. Claims distinguish disclosed fact, deterministic derivation, inference, and unsupported unknown.
4. Numeric and evidence audits run before publication.
5. Provider failure degrades to deterministic surfaces; it never removes the underlying analysis.

### 3.4 Cost and licensing

1. Every provider capability has a cost, entitlement, retention, display, and LLM-processing policy.
2. Website reads use persisted data; they do not trigger uncontrolled full-provider refreshes.
3. A report declares omitted capabilities when the data is unavailable or over budget.
4. A personal-use license cannot be assumed valid for professional, entity, multi-user, or commercial
   use.
5. Trial success does not grant production rights; legal/contract fields are part of the data gate.

## 4. Target architecture

```text
TRIGGER
  manual question | page action | schedule | filing | earnings | licensed news/event
      ↓
SCOPE
  report type | domain | chain | ticker set | as-of | freshness | budget
      ↓
EVIDENCE
  immutable observations → validation verdicts → PIT canonical views
      ↓
DETERMINISTIC COMPUTE
  DERIVE → ANCHOR → SCORE → chain rollups
      ↓
REPORT ASSEMBLY
  fixed blocks + optional model narrative + claims/evidence links
      ↓
AUDIT AND GATE
  numeric | source | PIT | inference | coverage | contradiction | authorization
      ↓
PERSIST AND RENDER
  report version | delta from prior | approval state | feedback
```

The later harness sits above this flow. It does not replace it:

```text
external harness
  ├── read research state and previous reports
  ├── build a bounded task DAG
  ├── enqueue typed Argon jobs
  ├── wait for persisted outputs
  ├── request report assembly
  └── propose follow-up work

external harness MUST NOT
  ├── write raw observations
  ├── edit score/valuation parameters
  ├── approve inferred taxonomy facts
  ├── bypass report audits
  └── trade
```

## 5. Workstreams

The milestones in §7 sequence delivery. These workstreams define the enduring capabilities each
milestone contributes.

### Workstream A — point-in-time data and evidence

#### Source roles

The intended fundamentals policy is:

| Priority | Source | Role |
|---:|---|---|
| 1 | UW statements | quarterly backbone and reported currency |
| 2 | Massive `/vX` | filing-date enrichment and independent drift/discrepancy check |
| 3 | SEC XBRL | authoritative gap fill, including NCI/current debt where available |
| 4 | Massive `/v2` | narrow historical metadata such as ADR share factor, not current backbone |
| — | explicit `na` | all sources absent, invalid, or non-comparable |

**Precondition:** the primary design still contains a stale architecture row that reverses this
precedence. Milestone M0 must reconcile the decision table, canonical-view text, P1b description,
tests, and field contract before an ingest implementation is allowed to encode the rule.

#### Required data layers

1. **Source observations** — immutable statements, segments, SEC filings, extracted relationships,
   and validation violations.
2. **Canonical PIT views** — one selected usable fact per company/period/field under a documented
   precedence and as-of boundary.
3. **Derived facts** — TTM, growth, margins, balance-sheet and segment measures, computed by pure
   functions.
4. **Versioned results** — valuation anchors, score dimensions, chain rollups, confidence, and
   coverage.
5. **Report evidence** — exact result and observation references used by every published claim.

References are enforceable data, not opaque JSON arrays. Before M1.1 freezes migrations, the child
design must choose typed association tables for result → observation provenance. M7 similarly uses a
typed claim-evidence table that identifies evidence kind and a real foreign-key target (or separate
association table per target kind); one polymorphic `evidence_id` with no enforceable foreign key is
not accepted. JSON may cache a rendered manifest, but it is not the authoritative relationship.

#### Data-quality minimums

- absolute accounting identities are checked during ingest;
- invalid observations remain stored but are excluded from downstream arithmetic;
- fiscal periods key on economic period end, not convenient calendar labels;
- foreign issuers carry explicit currency, translation, ADR, and NCI treatment;
- each ticker reports its own usable history rather than inheriting a global coverage claim;
- all provider probes retain HTTP/result state so zero rows cannot be confused with an error.

### Workstream B — general industry-chain model

The current AI taxonomy is the first content pack, not the permanent schema.

```text
research_domain
  └── industry
       └── layer
            └── chain
                 └── company_exposure
                      └── evidence
```

A company exposure needs more than membership:

| Field | Meaning |
|---|---|
| role | supplier, customer, equipment, material, substitute, end demand, or other typed role |
| exposure strength | disclosed share where available; otherwise bounded qualitative level |
| valid period | when the relationship or classification is believed to hold |
| evidence | filing, company disclosure, provider record, or reviewed inference |
| status | disclosed, derived, inferred, disputed, expired, or unsupported |
| confidence | mechanical score with reasons, not model sentiment |
| version | taxonomy/exposure version used by a report |

Domain-specific metrics are plugins, not branches in the central pipeline:

| Domain | Example additions |
|---|---|
| semiconductor | node, capacity, utilization, book-to-bill, equipment exposure |
| optical communication | 400G/800G/1.6T mix, DSP, EML, silicon photonics, module/customer mix |
| robotics | sensors, motion control, reducers, motors, controllers, backlog, penetration |
| power/energy | capacity, rate base, PPA, load growth, fuel/commodity sensitivity |
| metals/mining | reserves, grade, AISC, production, jurisdiction, commodity scenario |
| software | ARR, NRR, RPO, SBC, FCF margin, cohort/seat exposure |

Adding a domain must not require changes to run orchestration, report versioning, or audit logic.

### Workstream C — score stack

The product must not compress unlike questions into one unexplained number.

#### Persisted dimensions

| Dimension | Question |
|---|---|
| fundamental quality | is the operating and cash-generation base durable? |
| growth | what is growing, and is growth accelerating or decelerating? |
| balance sheet | how much financial fragility exists? |
| valuation position | where is spot relative to applicable valuation anchors? |
| technical state | what does the market currently confirm or reject? Kept outside fundamentals |
| catalyst/expectation | what could change the market's information set? |
| research confidence | how complete, fresh, comparable, and well-sourced is the analysis? |
| research priority | which unresolved or changing names deserve attention first? |

Two aggregates, if retained, must stay distinct:

- **investment attractiveness** summarizes approved investment dimensions but is not called a return
  forecast and is not automatically actionable;
- **research priority** ranks attention using change, uncertainty, event importance, disagreement,
  stale coverage, and catalyst timing; it does not mean “buy first.”

#### Direction policy at this program baseline

- profitability levels and trends render descriptively; no good/bad direction is claimed while the
  observed margin inversion remains unexplained;
- `valuation_position` is **metric-specific / direction withheld** until the actual anchor-position
  method is validated; book-to-price, earnings yield, and FCF yield cannot be treated as one empirical
  signal;
- technicals remain a separate block and do not enter the fundamental composite;
- a score calculated over missing subdimensions records the absent set and the renormalization or
  abstention rule;
- core-25 surfaces may display a company's own dimensions but may not order multiple companies by the
  composite.

#### Ranking gate

Cross-company ranking is allowed only for the exact population and method that satisfy all of:

1. comparable inputs and recorded missingness;
2. realized cross-section broad enough for the intended test;
3. correct knowledge-time/PIT construction;
4. active and delisted membership or a measured survivorship bound;
5. held-out/out-of-sample evidence;
6. multiple market regimes or an explicit regime limitation;
7. turnover, cost, liquidity, capacity, and shorting assumptions where relevant;
8. stable score behavior under reasonable parameter perturbation;
9. versioned validation artifact and a stated horizon.

Failure of this gate does not block descriptive reports.

### Workstream D — valuation engine

The valuation-control research is a factor-control experiment, not the production valuation engine.
The production engine has four layers.

#### D1. Normalized inputs

- TTM and normalized revenue, EPS, EBITDA, EBIT, and FCF;
- cash, debt, net debt, diluted shares, and enterprise value;
- segment economics and company-specific KPIs;
- reporting currency, translation rules, and ADR ratio;
- current spot and corporate-action reference frame;
- comparable-company observations under a versioned peer set;
- current analyst targets as an external cross-check;
- PIT analyst estimates only when a licensed PIT dataset is present.

#### D2. Company-type routing

| Company type | Candidate methods |
|---|---|
| semiconductor/hardware | normalized EPS, FCF, EV/EBITDA, cycle-adjusted scenarios |
| cloud/platform | SOTP, FCF, EPS, segment multiples |
| SaaS/high-growth software | revenue multiple, FCF path, margin scenarios |
| data-center/electrical equipment | EV/EBITDA, FCF, backlog/order sensitivity |
| utility/power | DCF, EV/EBITDA, rate-base/capacity cases |
| energy/metals | NAV, commodity cases, normalized FCF |
| industrial/robotics | EBIT/FCF, EV/EBITDA, order/backlog cycle |

Company type is historized input data. The agent does not choose it during prose generation.

#### D3. Scenario and method outputs

Each applicable method produces independently persisted bear/base/bull assumptions and price outputs
for the declared horizon. The blend then produces:

```text
buy_below
observe_low
observe_mid
observe_high
risk_above
```

These are decision anchors, not a point prediction. Each result includes applicability, sensitivity,
confidence, and abstention reasons.

#### D4. Blend and validation

- method weights are versioned by company type and coverage, never authored by an LLM;
- analyst targets are external evidence, not ground truth;
- greater disagreement between applicable methods mechanically lowers confidence;
- missing critical inputs cause the affected method to abstain;
- peer set, spot date, share count, currency, and net-debt reference date are included in
  `inputs_hash`;
- validation covers reproducibility, sensitivity, band width, forward coverage, regime dependence,
  and whether a valuation gap is merely quality/industry/momentum exposure.

### Workstream E — company and chain analysis

The single-company surface supplies the atomic rows; the chain surface is a read-time comparison over
compatible versions.

Every chain/layer report may show separately:

1. operating strength;
2. valuation pressure and method disagreement;
3. technical breadth;
4. catalyst density;
5. customer/segment/geographic concentration;
6. upstream/downstream dependency;
7. estimate-revision state, only when true PIT data exists;
8. coverage and research confidence;
9. explicit unknowns.

The first chain view must not color small cells by an unvalidated composite. Initial comparative
encodings use coverage, confidence, valuation distributions, raw financial trends, and separately
labeled technical breadth. Every rollup drills down to companies and evidence.

### Workstream F — audited reports and harness

#### Report types

- single-company deep dive;
- two-to-five company comparison;
- full industry-chain report;
- sub-chain dive-in;
- pre-earnings brief;
- post-earnings delta report;
- filing/news impact report;
- periodic watchlist brief.

#### Report contract

Every report version contains:

- research scope, universe, taxonomy version, as-of, and freshness policy;
- input manifest and deterministic engine versions;
- data coverage and omitted capabilities;
- market/technical context;
- financial changes;
- valuation anchors and method disagreement;
- score dimensions and confidence;
- chain position and dependencies;
- catalysts, risks, invalidation conditions, and unknowns;
- claims linked to exact evidence;
- audit verdicts;
- cost/usage summary;
- delta from the prior comparable report.

#### Harness levels

| Level | Capability | Publication authority |
|---:|---|---|
| 0 | fixed pipeline from a page action | deterministic output only |
| 1 | question → bounded plan → report draft | operator publishes |
| 2 | filing/earnings/event-triggered delta draft | operator publishes |
| 3 | scheduled monitoring and stale-report refresh | operator publishes |
| 4 | auto-publish audit-clean descriptive reports | explicit policy required |
| 5 | ranked/recommendation output | separate empirical and approval gate |

The program's first harness target is Levels 1–2. Level 4 is not assumed, and Level 5 is outside the
descriptive-report entry gate.

## 6. Data-cost and procurement plan

### 6.1 Capability cost classes

| Class | Description | Default behavior |
|---|---|---|
| C0 | already persisted or free authoritative data | use first |
| C1 | existing metered entitlement such as UW | budgeted incremental refresh; cache aggressively |
| C2 | low-cost research subscription | research-only until license and value gates pass |
| C3 | quote-based institutional feed | optional capability; never a silent runtime dependency |

Every capability registry entry records:

```text
provider
capability
license_class
fixed_subscription_cost
marginal_request_cost
rate_limit
refresh_frequency
retention_rights
display_rights
derived-data rights
LLM-processing permission
coverage
freshness
fallback
last_contract_reviewed_at
```

Every research/report run records estimated and actual provider usage, cache hits, paid capabilities
invoked, and conclusions omitted because of budget or entitlement.

### 6.2 Tier 0/1 — current stack

Use existing UW, Massive, SEC, livewire, Argon technical/options/flow data, and already entitled news
or event sources. This tier supports:

- descriptive company reports;
- current valuation anchors;
- current chain comparison;
- current analyst target/ratings context;
- earnings calendar, filings, technicals, options, and market structure.

It does **not** support a claim that historical consensus revisions predict returns. Current analyst
targets are not a substitute for a daily PIT consensus history.

### 6.3 Tier 2 — Sharadar research track

Purpose:

- build historical active-plus-delisted universes;
- reduce survivorship bias;
- obtain permanent security identities, corporate actions, and delisting history;
- pair PIT fundamentals with correct future-return labels.

SEP/prices alone is insufficient for fundamental-score validation; the test needs prices, security
master, and PIT fundamentals.

Public personal-use pricing observed on 2026-08-11 was approximately $19/month for fundamentals,
$9/month for prices, and $29/month for the bundle. This is a planning snapshot, not a procurement
promise; pricing must be rechecked. More importantly, the personal license restricts professional,
entity, redistribution, and retention uses. The subscription must not be copied into production
until the actual Argon use and license rights are confirmed.

Procurement gate:

1. use the free sample to validate fields, PIT semantics, identifiers, adjustments, and ingest size;
2. classify Argon's use as personal or professional/entity use;
3. obtain written clarification for internal web display, backend analysis, LLM processing, derived
   report display, and post-termination retention;
4. preregister the active-plus-delisted validation before viewing results;
5. purchase the minimum valid package/license;
6. run the bounded study and persist its full trace under the permitted terms;
7. decide whether to retain, upgrade, or reject the dataset.

Sharadar gates ranking claims; it does not gate the deterministic card or descriptive report.

References:

- <https://data.nasdaq.com/databases/SEP>
- <https://sharadar.com/subscribe>
- <https://sharadar.com/terms>

### 6.4 Tier 3 — LSEG I/B/E/S or FactSet PIT Consensus

Purpose:

- daily historical consensus snapshots;
- EPS/revenue and company-specific estimate revisions;
- revision breadth, acceleration, dispersion, and analyst-count change;
- actuals and, where licensed, company guidance;
- validation of whether expectation changes add predictive or explanatory value.

These are quote-based institutional capabilities. They are not P1b dependencies and must not appear
as required fields in the deterministic v1 card.

Before requesting a trial, freeze a common vendor field contract:

- permanent company and security IDs;
- snapshot/effective timestamp and local-market cutoff;
- fiscal period, period type, horizon, and accounting basis;
- metric, currency, units, mean/median/high/low/dispersion, and analyst count;
- estimate additions, withdrawals, and revisions;
- individual broker estimates if the hypothesis requires them;
- actual value and first-known timestamp;
- guidance range, metric, period, source, and issue timestamp if included;
- corporate-action, currency, dilution, restatement, and correction policy;
- active/delisted coverage;
- API/bulk/non-display rights;
- internal Argon display, LLM processing, derived-report, and retention rights.

Pre-register the tests before the bake-off:

- 20/60/90-day EPS and revenue revision;
- revision breadth and acceleration;
- dispersion and analyst-count changes;
- guidance midpoint versus consensus;
- actual surprise and post-earnings revision drift;
- upstream/downstream revision diffusion;
- incremental value after momentum, surprise, industry, size, and existing fundamental controls.

Purchase one provider only if the trial demonstrates adequate coverage, correct PIT behavior,
incremental out-of-sample value, usable rights, and acceptable total cost. Failure leaves the
expectation-revision block explicitly unsupported without degrading other reports.

References:

- <https://www.lseg.com/en/data-analytics/financial-data/company-data/ibes-estimates>
- <https://insight.factset.com/resources/at-a-glance-factset-estimates-point-in-time-consensus>

### 6.5 Runtime cost policy

Provider resolution order:

```text
persisted compatible result
→ persisted PIT fact
→ free/already-entitled incremental refresh
→ C2 research capability if the run is authorized
→ C3 institutional capability if the run is authorized
→ explicit unsupported/omitted block
```

Each harness/report request has maximum wall time, provider calls, paid units, model tokens, retries,
and freshness. Exceeding a limit produces a partial, labeled draft; it does not silently exceed the
budget or fabricate the missing section.

## 7. Milestones and PR sequence

Each PR below is independently reviewable, has one primary responsibility, and includes tests,
documentation, registry changes, and `[Unreleased]` changelog entry where it changes shipped
behavior. Research-only PRs persist complete artifacts and reproduce commands.

### M0 — close the method and specification boundary

**Purpose:** prevent known research conclusions and stale design text from being encoded as runtime
policy.

#### PR M0.1 — valuation-control research

Scope:

- merge the bounded valuation-control experiment and full artifacts;
- record that controlling for tested valuation ratios does not explain margin inversion;
- mark profitability direction as withheld;
- mark valuation direction as metric-specific/withheld rather than generic cheaper-is-better;
- record single-regime, survivorship, and no-cost limitations;
- no application code.

Exit checks:

- self-check passes;
- artifact regenerates deterministically from the stated command;
- Markdown, JSON, VERDICT, and spec numbers agree;
- no conclusion implies production valuation anchors have been validated.

#### PR M0.2 — source-precedence/spec errata

Scope:

- reconcile A4, canonical views, P1b, source diagrams, tests, and field contract to the measured UW
  backbone/Massive cross-check/SEC gap-fill policy;
- resolve the G2 acceptance wording so core-25 cells cannot be colored by composite ranking;
- distinguish a descriptive-report harness gate from a ranking/action gate;
- reconcile A11's proposed refresh URI with Argon's standing mutation boundary: fundamental read
  endpoints remain on the fundamental router, while enqueue/cancel mutations are owned by
  `api/routers/jobs.py` under `/api/jobs`;
- no ingest implementation.

Exit checks:

- one source policy appears everywhere;
- every acceptance condition can be satisfied simultaneously;
- the primary spec contains no stale claim that already-landed or parallel research is production
  capability.

**M0 gate:** P1b is blocked until M0.2 is merged. Other research may continue.

### M1 — immutable PIT fundamentals backbone

#### PR M1.1 — observation schema and repository domain

Scope:

- migrations for statement, segment, segment-revenue, SEC-document, and violation observations;
- freeze the observation identity/reference contract that later typed result-provenance associations
  will target; result association tables themselves land with the result tables in M2;
- dataset-registry entries and generated policy documentation;
- repository domain module rather than additions to aggregate `repository.py`;
- immutable identity/content-hash and sighting semantics;
- fixtures for restatement, invalid accounting identity, and provider conflict.

#### PR M1.2 — UW backfill and incremental ingest

Scope:

- UW statements and revenue breakdown as the backbone;
- backfill and incremental modes sharing one normalization path;
- per-row validation verdicts;
- idempotent unchanged refresh;
- per-ticker coverage artifact.

#### PR M1.3 — Massive reconciliation and SEC gap fill

Scope:

- Massive filing-date metadata and discrepancy observations;
- SEC XBRL gap fill with `us-gaap` and `ifrs-full` handling;
- foreign issuer currency/ADR/NCI contract;
- canonical PIT views and discrepancy read surface.

M1 exit gate:

- all core names reach their measured source-specific spans;
- unchanged re-ingest writes no new fact;
- simulated restatement preserves predecessor;
- invalid raw values remain inspectable but downstream fields abstain;
- selected canonical facts reproduce from source observations at an arbitrary as-of;
- real worker/database path passes against the correct database tier.

### M2 — deterministic derivation, valuation, and score

#### PR M2.1 — pure derivation engine

Scope:

- TTM, YoY growth/acceleration, margins, FCF, leverage, coverage, return/capital efficiency, and
  concentration primitives;
- pure functions with unit-normalized inputs;
- worked examples and property/identity tests;
- no UI and no model calls.

#### PR M2.2 — company-type and valuation engine

Scope:

- historized company-type registry;
- method registry and per-type implementations;
- bear/base/bull assumptions and five price anchors;
- applicability, abstention, confidence, and sensitivity;
- typed valuation-result → source-observation provenance associations;
- immutable method versions and singleton active pointer.

#### PR M2.3 — score dimensions and run ledger

Scope:

- independent score dimensions, confidence, and research priority;
- explicit missing-dimension/renormalization contract;
- typed score-result → source-observation provenance associations;
- `fundamental_runs`, stage state, typed output associations, and active-run uniqueness;
- cached recompute and external-refresh modes;
- typed enqueue/cancel job API on `api/routers/jobs.py`, returning `202`; the fundamental router stays
  read-only.

M2 exit gate:

- three hand-worked companies reproduce derivations, anchors, and dimensions;
- same inputs/method reuse the same logical result;
- changing company type or any method input changes `inputs_hash`;
- old and new method versions coexist;
- no core-25 endpoint sorts by composite;
- no model is needed for any output.

### M3 — deterministic single-company product

#### PR M3.1 — fundamental API contract

Scope:

- new read-only fundamental router and Pydantic models;
- run status, current compatible result, history, coverage, and provenance endpoints;
- typed fundamental job status linked from the existing jobs surface;
- generated TypeScript contract;
- stale/missing/incompatible version behavior.

#### PR M3.2 — stock-page fundamental card

Scope:

- financial trends and data-quality/coverage;
- independent score dimensions and confidence reasons;
- valuation anchors, scenarios, and method disagreement;
- provenance drill-down, unknowns, and explicit `na` reasons;
- compute/refresh action with queued status;
- loading, stale, partial, error, and provider-unavailable states.

M3 exit gate:

- every rendered number resolves to a persisted deterministic row and source observations;
- provider/model disablement leaves the last compatible deterministic result usable;
- stale result is visibly stale;
- real enqueue → worker → database → API → browser smoke passes.

At M3, the first useful product exists. Later narrative and harness phases must not delay release of
this deterministic card.

### M4 — general industry-chain surface

#### PR M4.1 — versioned domain/exposure model

Scope:

- versioned domain/layer/chain definitions;
- company exposure role, validity, evidence, confidence, and status;
- migration/import from current `watchlist_chain` without pretending old membership has stronger
  evidence than it does;
- additive dual-read parity period: the current watchlist filter continues reading `watchlist_chain`
  until the versioned model reproduces membership and multi-chain behavior, then the read path flips
  behind a flag;
- proposal/review path for inferred relationship changes.

#### PR M4.2 — chain matrix and drill-down

Scope:

- AI as the first content pack;
- compatible-version rollups;
- coverage/confidence/valuation-distribution/financial-trend encodings;
- active-watchlist and broader-research-universe scopes clearly distinguished;
- cell → company → fundamental-card drill-down.

#### PR M4.3 — semiconductor/optical-communication dive-in

Scope:

- prove extension with a narrow sub-chain spanning switch ASIC, DSP, module, EML/laser, silicon
  photonics, fiber/connector, system vendor, and cloud demand;
- add domain metrics through registries/plugins;
- publish evidence and unknowns for every relationship.

M4 exit gate:

- adding the optical sub-chain does not change central run/report orchestration;
- small cells are not ranked by composite;
- every aggregate discloses coverage and version compatibility;
- a user can move from domain to sub-chain to company evidence without a second scoring path.

### M5 — concentration, filings, and catalyst evidence

#### PR M5.1 — discovery gate

Scope:

- read-only core-universe probe for named customer, segment, country, and relationship evidence;
- measured yield, false-positive review, 10-K/20-F coverage, and cost;
- explicit ship/kill recommendation for each extraction class.

#### PR M5.2 — approved SEC/concentration ledger

Scope only for classes that pass M5.1:

- durable filing cache by accession;
- versioned extraction runs and fact membership/retraction;
- segment/customer/country concentration with citations;
- disclosed versus inferred identities;
- bounded retry/rate behavior.

#### PR M5.3 — catalyst/event ledger

Scope:

- earnings dates, guidance where sourceable, filings, product/industry events, and licensed news
  references;
- effective/known-at timestamp, materiality, affected domains/chains/companies, source quality, and
  expiration/resolution;
- no historical revision claim without PIT estimate data.

M5 exit gate:

- failed discovery classes are killed, not carried as perpetual empty UI;
- every shipped concentration/event fact has source and known-at time;
- inferred identities cannot be rendered as disclosed fact;
- reprocessing a filing/event is idempotent.

### M6 — constrained narrative and audit

#### PR M6.1 — domain-isolated narrative queue

Scope:

- `fundamental_narrative_analyses` and dedicated repository/worker role;
- provider-neutral runner interface, with the deployable provider first;
- add `ai-fundamental` to scheduler role validation/group selection, configuration, compose service,
  heartbeat, queue-depth health, and operational documentation; it is not implied by the existing
  `ai-deepseek` role;
- persisted input payload, prompt, schema, resolved model, raw failure output, and status;
- structured company narrative only; no general loop planner.

#### PR M6.2 — deterministic and model audit

Scope:

- numeric equality/tolerance checks;
- evidence existence and source-quality checks;
- PIT/as-of checks;
- disclosed/inferred/unsupported-language checks;
- mandatory unknowns and numeric invalidation conditions;
- claim-level pass/warn/fail/unverifiable;
- fail suppression from published narrative.

M6 exit gate:

- real enqueue → dedicated worker → structured outcome → audits → UI passes;
- model/provider failure leaves M3/M4 surfaces usable;
- model cannot alter any deterministic value;
- audit-failed claims do not appear as report facts;
- fundamental rows never enter the trade-insight outcome ledger.

### M7 — versioned report product

M7 depends on the deterministic M3/M4 products and M5 being resolved. It does **not** depend on a
successful model narrative. M6 may land before or alongside it, and its audited output becomes an
optional report block. This preserves the invariant that reports remain useful when the provider is
disabled.

#### PR M7.1 — report/control ledger

Scope:

- `research_runs`, scopes, task manifests, input manifests, reports/versions, claims, claim-evidence,
  audits, approvals, and feedback;
- enforceable evidence associations; avoid an FK-less polymorphic evidence column;
- company, comparison, chain, sub-chain, earnings, event-delta, and watchlist report types;
- report compatibility and supersession rules;
- cost/usage and omitted-capability fields.

#### PR M7.2 — report assembly and UI

Scope:

- deterministic block assembly plus optional audited narrative;
- previous-version delta;
- evidence/provenance drill-down;
- draft, audit-failed, approval-required, published, superseded, and stale states;
- company and chain report routes in Argon.

M7 exit gate:

- an old report replays from its original manifest after new observations/method versions arrive;
- a new report explains material changes from the prior comparable report;
- every published claim has evidence or is explicitly labeled inference;
- report remains useful with narrative absent;
- cost, coverage, and unsupported capability disclosures are visible.

### M8 — bounded agent harness

M8 starts only after M7 is live. It does not wait for a validated investment ranking because its
first authority is descriptive draft generation, not action on score ordering.

#### PR M8.1 — narrow command/read surface

Scope:

- authenticated, least-privilege read APIs for facts, runs, reports, versions, coverage, and audits;
- typed enqueue commands for already-approved Argon jobs;
- task budget, idempotency key, status, cancellation, and retry policy;
- distinct harness service identity, route-scoped authorization, key rotation/revocation, actor ID on
  every command, and redaction tests proving secrets cannot enter prompts, logs, or report manifests;
- no raw SQL or method/taxonomy mutation endpoint.

#### PR M8.2 — question-to-draft workflow

Scope:

- resolve report type, domain/chain/tickers, as-of, freshness, and budget;
- produce bounded task DAG with maximum tasks/calls/time/tokens/retries;
- prefer compatible cached results;
- assemble a draft and request operator publication;
- persist plan, decisions, tool calls, outputs, and termination reason.

#### PR M8.3 — event-triggered delta drafts

Scope:

- filings and earnings first;
- licensed news and PIT estimate changes only when those capabilities exist;
- impact resolution from event → affected facts → computations → reports;
- deduplication, cooldown, grouping, and no-change suppression;
- drafts only.

#### PR M8.4 — scheduled self-tending mode

Scope:

- stale-report and stale-data monitoring;
- bounded recompute and delta generation;
- provider/model/data cost telemetry;
- operator queue and silence discipline;
- explicit per-report auto-publish policy remains off by default.

M8 exit gate:

- harness cannot mutate facts, methods, score weights, or approved taxonomy;
- every mutation travels through a typed gate and persisted run;
- budget exhaustion terminates cleanly with a labeled partial draft;
- repeated identical triggers deduplicate;
- one week of scheduled operation has no runaway loops, hidden spend, or silent audit bypass;
- all reports remain reproducible without the harness process being present.

### M9 — optional empirical upgrades

These are independent research/procurement tracks. They gate stronger claims, not the descriptive
product.

#### Research M9.A — Sharadar contract/sample probe

- validate sample fields, PIT semantics, permanent IDs, adjustment policy, delisting, and volume;
- obtain license determination for the intended Argon use;
- stop if rights are incompatible.

#### Research M9.B — active-plus-delisted score validation

- construct the historical universe by knowledge date;
- include delisting returns;
- rerun score dimensions and composite;
- test time-series deterioration separately;
- measure turnover, liquidity, transaction-cost assumptions, and regime stability;
- update ranking permission from evidence.

#### Research M9.C — PIT estimates vendor bake-off

- issue the same field/licensing contract to LSEG and FactSet;
- run the preregistered revision studies on the same universe and horizon;
- compare coverage, corrections, PIT integrity, access, rights, total cost, and incremental value;
- buy at most one provider, or reject both.

#### Build M9.D — licensed estimates adapter

Only if M9.C passes:

- immutable PIT estimate observations and actual/guidance observations;
- revision/dispersion/breadth features;
- company and chain report blocks;
- event trigger integration;
- separate method version and data-capability disclosure.

M9 ranking/recommendation gate:

- evidence applies to the exact production universe and feature definition;
- OOS and active-plus-delisted tests pass;
- regime and cost limitations are recorded;
- estimates add incremental value if used;
- operator explicitly approves any new ranking/recommendation authority.

## 8. Dependency graph

```text
M0 method/spec closure
  └── M1 PIT data
       └── M2 deterministic valuation/score
            ├── M3 company card
            └── M4 chain surface
                 └── M5 concentration/events (discovery-gated)

M3 + M5 resolved
  └── M6 constrained narrative/audit (optional report block)

M3 + M4 + M5 resolved
  └── M7 versioned reports (works without M6 output)

M6 + M7
  └── M8 bounded harness

M9 optional datasets/research run alongside M1–M8
  ├── never block descriptive M3/M4/M7
  └── do gate stronger ranking, recommendation, and revision claims
```

M4 can begin its schema/matrix skeleton alongside M2, but the route cannot ship comparative
fundamental encodings until compatible M2 results exist. M5 begins with discovery and can be killed
without blocking M3. M6 waits for M5 to be resolved, not necessarily shipped. M7 may proceed without
M6, but M8 requires both the report ledger and the narrative/audit boundary.

## 9. Program gates

| Gate | Required evidence | Unlocks |
|---|---|---|
| G0 — spec consistent | one source policy, compatible acceptance tests, research limits recorded | P1b implementation |
| G1 — data trustworthy | PIT replay, restatement preservation, violation handling, measured coverage | deterministic engine |
| G2 — method fixed | worked examples, version/hash identity, abstention and confidence rules | UI rendering |
| G3 — deterministic product | worker-path smoke, provenance drill-down, stale/partial behavior | narrative and reports |
| G4 — chain adds information | compatible rollups, evidence-backed exposure, useful dive-in | chain reports |
| G5 — evidence extraction useful | discovery yield and false-positive gate | concentration/event features |
| G6 — narrative constrained | structured output, claim audits, provider-down degradation | publishable narrative |
| G7 — report reproducible | manifest, versions, claims/evidence, delta, cost disclosure | harness |
| G8 — harness bounded | permissions, budgets, dedup, termination, unattended soak | scheduled drafts |
| G9 — ranking supported | broad PIT/OOS, active+delisted, regimes, costs | cross-company ordering |
| G10 — estimates worth cost | trial adds robust incremental value and rights fit | institutional feed adapter |

No gate may be waived by a visually persuasive UI or fluent model narrative.

## 10. Delivery sizing and risk

Sizes describe engineering/review surface, not calendar commitments. Any `L` milestone must be split
into the child PRs already listed; no PR inherits the milestone size as one unit.

| Milestone | Size | Primary risk driver | Lower-risk release shape |
|---|---:|---|---|
| M0 method/spec | S | encoding contradictory research conclusions | docs/research only, no runtime changes |
| M1 PIT data | L | immutable identity, backfill, source disagreement, foreign issuers | additive tables → backfill → verify → canonical views |
| M2 valuation/score | L | method ambiguity and false comparability | pure derivations → anchors → dimensions/runs |
| M3 company card | M | stale/partial state and provenance trust | hidden tab/flag, deterministic only |
| M4 chain surface | L | taxonomy migration and persuasive small-sample ranking | dual-read parity, coverage-first encodings |
| M5 filings/events | M/L | extraction false positives and rate limits | mandatory discovery PR; kill weak classes |
| M6 narrative/audit | M | fluent fabrication and worker isolation | provider off by default until real smoke/audit |
| M7 report product | L | durable version/supersession contract | deterministic reports first, narrative optional |
| M8 harness | L | authority, cost runaway, loops, secret leakage | draft-only, typed commands, bounded soak |
| M9 paid datasets | research-dependent | licensing and unproven incremental value | sample/trial before adapter or contract |

## 11. Rollout, rollback, and compatibility

Every child implementation plan must state its feature flag, migration direction, rollback behavior,
and post-deploy smoke. The program defaults are:

### Schema and data

- migrations are additive and idempotent;
- old read paths remain valid until parity and backfill verification finish;
- no migration drops or rewrites source history in the feature PR;
- canonical-view changes are versioned or flag-switched so rollback means selecting the prior rule,
  not deleting new observations;
- backfills persist run state and resume; aborting a backfill does not publish partial coverage as
  complete;
- new temporal tables join the dataset registry and freshness/gap policy in the same PR.

### Workers and providers

- every new recurring job and provider lane has an off switch defaulting to off until deployed
  migrations and target credentials are verified;
- worker-role validation, compose service, heartbeat, queue age/depth, and restart instructions ship
  together;
- rolling back a worker disables claiming before removing code; queued rows remain inspectable and
  recoverable;
- provider credentials stay in runtime configuration and are never copied to model subprocesses,
  prompts, logs, or evidence manifests.

### API and web

- API additions are backward-compatible until generated clients and web consumers have shipped;
- mutation endpoints remain under `/api/jobs`; read routers do not accumulate ad-hoc writes;
- new routes/tabs stay out of navigation behind a flag until their real worker/data path passes;
- turning a feature flag off preserves stored evidence and renders a clear unavailable/stale state;
- chain migration uses dual-read parity before changing the existing watchlist filter source.

### Reports and harness

- the report ledger is append-only/versioned; rollback never overwrites published history;
- narrative and harness flags can be disabled independently of deterministic reports;
- auto-publication is off by default and requires a separate policy decision;
- revoking the harness identity stops new commands without removing report readability;
- budget, authorization, audit, or task-loop failure ends in a persisted failed/partial draft, not a
  half-published report.

Post-deploy verification is milestone-specific but always reads from a newly opened connection or
fresh browser request; in-process success alone is not evidence of durable state.

## 12. Verification strategy by layer

### Research

- preregister hypotheses, universe, horizon, features, controls, and kill conditions;
- persist every configuration and metric, not only the headline;
- keep exact reproduce command and data/version manifest;
- verify realized cross-section width and knowledge-time bucketing;
- separate factor ordering, investment strategy, and live utility claims.

### Storage and compute

- migration idempotence;
- immutable observation/restatement tests;
- repository tests against the correct database tier;
- pure-function unit/property tests;
- version/hash identity and result-reuse tests;
- registry and data-gap policy checks.

### API and workers

- enqueue/idempotency/concurrency/retry/resume tests;
- provider failure and partial-stage recovery;
- real worker smoke through persisted rows;
- OpenAPI and generated TypeScript contract checks;
- no synchronous multi-provider writes from read routes.

### Web

- deterministic number and provenance rendering;
- loading, stale, partial, unsupported, audit-failed, and provider-down states;
- accessibility and responsive behavior;
- Playwright for company, chain, report, and evidence drill-down paths;
- screenshots under `output/playwright/` only.

### Harness

- golden research questions with expected scope and task bounds;
- adversarial prompts attempting fact/method/taxonomy mutation;
- budget exhaustion and cancellation;
- repeated-trigger deduplication;
- provider outage and partial-result behavior;
- audit bypass attempts;
- one-week soak before increasing authority.

### Standard child-PR quality gates

Every child implementation plan narrows these commands to its changed surface during development,
then runs the applicable full gates before review:

```text
uv run pytest
uv run ruff check .
uv run python scripts/check_no_yahoo.py
cd web && npm run typecheck
cd web && npm run test
cd web && npm run lint
cd web && npm run build
```

Database work also runs migrations twice to prove idempotence and executes its integration tests on
the correct test database. API contract changes regenerate `web/lib/types.ts`. User-visible routes
run the named Playwright flows. Worker changes run the real enqueue → claim → persist → API/UI smoke
after restarting the worker process.

Pure documentation/research PRs do not claim application validation from these commands. They run
their reproduce/self-check, link any known baseline failures, and verify the exact diff and artifact
consistency appropriate to their scope.

## 13. Observability and operating model

Every production stage publishes:

- heartbeat and last successful completion;
- queue depth and oldest age;
- run counts by status/stage/provider;
- data freshness and coverage;
- provider calls, official counters where available, failures, 429s, and cost estimates;
- model calls/tokens/latency/failure and audit-fail rates;
- report staleness and unpublished-draft counts;
- harness suppression/dedup/cooldown and termination reasons.

Alerts should target conditions requiring action, not ordinary `na` or no-change runs. Provider
outages, stale facts, audit-fail spikes, budget exhaustion, stuck runs, and report publication
failures are actionable. A company legitimately lacking a field is a report disclosure, not an ops
page.

## 14. Program completion criteria

The program is complete at its intended descriptive-research scope when a user can ask:

> Research the US optical-communication chain. Compare switch silicon, DSP, lasers, modules, system
> vendors, and cloud customers; show where operating momentum, valuation pressure, catalysts, and
> concentration risk sit; then dive into three companies.

Argon can then:

1. freeze the domain, chain, company universe, as-of, taxonomy version, method version, and budget;
2. state data coverage and unsupported paid capabilities before making conclusions;
3. run or reuse deterministic financial, valuation, score, technical, and chain calculations;
4. generate a versioned draft whose claims link to exact evidence;
5. distinguish facts, derivations, inferences, disputes, and unknowns;
6. show price anchors, scenarios, catalysts, risks, and numeric invalidation conditions;
7. audit numbers, sources, time boundaries, inference language, and coverage;
8. publish through the Argon UI with prior-version delta and provenance drill-down;
9. refresh only affected work when a filing, earnings event, or licensed signal changes;
10. stay within recorded data/model budgets and degrade explicitly when a capability is unavailable;
11. avoid cross-company ranking where the exact production universe lacks supporting evidence;
12. remain reproducible even if the model provider or external harness is unavailable.

Completion does not imply automatic investment recommendation or trade execution. Those require a
new program decision after G9, not a silent extension of this one.

## 15. Plan maintenance protocol

This file is the program-level source of truth. It changes only when evidence, scope, dependency, or
authority changes.

For every milestone:

1. create a child design/spec if the contract is not already fixed;
2. create a child implementation plan with exact files, tests, commands, and PR boundary;
3. record the branch/PR and status here;
4. update the program gate with actual evidence, not “implemented” prose;
5. record killed ideas and why;
6. move completed child plans to `docs/superpowers/archive/plans/` under existing conventions;
7. keep this program plan active until M8 descriptive harness completion or an explicit stop ruling.

Status vocabulary:

```text
proposed → researched → specified → planned → in_progress → verified → merged
                                      └────────→ killed
```

No phase becomes `verified` from unit tests alone when its exit gate requires a real worker, database,
provider, or browser path.
