# Fundamental PM Research System — Master Program Plan

> **Status:** active program source of truth from 2026-08-24.
>
> **Purpose:** deliver the complete Fundamental PM research system through gated child projects.
> This is not a one-PR implementation plan and not a claim that unbuilt milestones are committed.
>
> **Governing design:**
> `docs/superpowers/specs/2026-08-24-fundamental-pm-research-system-design.md`
>
> **Historical sources:**
> `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md` and
> `docs/superpowers/plans/2026-08-12-fundamental-pm-agent-program.md` remain evidence of the original
> decisions and shipped work. This plan supersedes the older plan for future sequencing and status.

## 1. Executive outcome

Build one evidence-driven system in which an operator can move among four research levels without
changing methods or losing provenance:

```text
Fundamental PM Research Radar
    -> company / comparison analysis
    -> industry / chain / sub-chain analysis
    -> versioned research report
    -> bounded refresh and draft agent
```

The data foundation and deterministic engine support all four. The Radar is the attention-routing
entry point, not the entire product. Industry-chain research is a first-class product, not ticker
tags attached after a single-stock page. Reports are durable research objects, not generated prose.
The agent is a bounded consumer of these products, not an authority over their facts or methods.

## 2. Program rules

1. **Preserve the goal.** Inadequate data narrows authority or produces `na`; it does not silently
   shrink the project to a prettier card.
2. **Evidence before direction.** Theory, prototype, historical research, product behavior, and live
   reproducibility are separate states.
3. **Research priority is not expected return.** No score receives stronger language without the
   exact production scope passing its gate.
4. **As-of means version availability.** Period dates and original filing dates do not date a later
   restatement.
5. **Deterministic first.** Every number and categorical rule is computed and versioned outside the
   model.
6. **Reports work without narrative.** Models add optional audited prose only.
7. **Agent mutations are typed and gated.** No raw SQL, method edit, taxonomy edit, or automatic
   publication.
8. **Every milestone is independently reviewable.** Large milestones split into child PRs; the next
   milestone does not start merely because code exists.
9. **No hidden data loss.** Backtests, sweeps, comparisons, and reconciliation persist full traces
   and reproduce commands.
10. **No automatic trading scope.** This plan ends at descriptive research and bounded drafts.

## 3. Current baseline and review verdict

### 3.1 Baseline

- repository baseline: `v0.12.16`, commit `86161f1d`;
- feature worktree: `.worktrees/fundamental-pm-research-system`;
- branch: `feat/fundamental-pm-research-system`;
- existing lane: immutable statement observations, deterministic features/scores/valuation anchors,
  scheduled refresh, fundamentals/statements APIs, and a stock-page fundamentals tab;
- relevant targeted baseline suite: 209 tests passed again after the worktree rename and environment
  rebuild;
- production health and release workflow were verified on 2026-08-24.

The production filing-date recovery evidence is presently recorded in uncommitted user-owned files
in the primary checkout. It reported 450 tickers processed, 89,553 observations touched, zero
inserts, zero failures, 8,520 tolerance-path dates recovered, and 2020+ statement-date coverage at
91.1%. These are dated operational facts, not branch artifacts; reverify before using them as a
release claim.

### 3.2 What is already useful

- normalized content hashing excludes changing provider envelope timestamps;
- changed payload content creates immutable observation versions;
- same-content refresh is idempotent and may fill a missing filing date;
- scoring withholds future knowledge-date estimates;
- valuation anchors use corrected Silver split-only price inputs in production;
- single-company deterministic cards and statement history exist;
- concentration discovery disproved an earlier false `0/257` availability conclusion;
- research already distinguishes broad cross-sectional ordering from failed within-name direction;
- industry membership exists as many-to-many `watchlist_chain` data.

### 3.3 Blocking correctness gaps

| ID | Gap | Why it matters | First resolving milestone |
|---|---|---|---|
| B1 | historical scoring reads maximum `obs_id`, not the version available as of the historical cutoff | later restatements can leak backward | Pre-Job 0 |
| B2 | old provider snapshots have no honest version-publication timeline | current-vintage history can be mislabeled PIT | Pre-Job 0 / M1 |
| B3 | statement integrity violations suppress display but still enter score math | attractive output may be computed from rejected inputs | M1 |
| B4 | UW is effectively the only implemented backbone; canonical Massive/SEC reconciliation is incomplete | coverage gaps and provider conflicts lack a durable rule | M1 |
| B5 | `source_obs_ids BIGINT[]` is weak, FK-less result provenance | outputs cannot enforce or richly explain lineage | M1/M2 |
| B6 | most names remain without a governed company type (319/450 in the latest review snapshot) | valuation method comparability and refusal are incomplete | M1/M2 |
| B7 | historical valuation research mixed raw close with shares restated to today's split basis | the existing result cannot be promoted without rerun | M3 |
| B8 | current score authority is easy to overread; exact return/strategy evidence is absent | Radar can accidentally become an alpha claim | M3/M4 |
| B9 | UI conflates transport failure, no data, no compatible result, and stale result | operator cannot tell absence from system failure | M4 |
| B10 | concentration is only a first snapshot, not a durable multi-period evidence ledger | catalyst/risk and chain claims remain shallow | M6 |
| B11 | the current taxonomy is membership, not an evidence-backed exposure graph | it cannot answer supplier/customer dependence or propagation | M5 |
| B12 | no versioned report/control ledger exists | narrative rows cannot replay or explain deltas | M7 |
| B13 | no bounded fundamental agent command surface exists | automated research would bypass durable controls | M9 |
| B14 | `fundamentals/valuation.py` and `fundamental_anchors.py` are near the module-size limit | further feature growth risks another monolith | M2 |

### 3.4 Claims that remain forbidden

Until their specific gate passes, do not claim:

- true point-in-time historical results from current-vintage UW snapshots;
- within-company deterioration predicts price weakness;
- the composite is expected return, a buy signal, or a portfolio input;
- generic cheaper-is-better direction across all valuation metrics;
- industry membership proves supply/customer exposure;
- the current filing-date recovery reconstructs amendment history;
- current production coverage equals an older MacBook/local research count;
- a model-generated catalyst or risk exists without evidence.

## 4. Product architecture and dependency map

```text
P0  observation-version time contract
 |
 v
M1  canonical evidence + validity + governed entities/provenance
 |
 v
M2  deterministic engine v2 + run ledger
 |
 v
M3  corrected research + claim/permission registry
 |                 \
 v                  v
M4 company v2 + Radar    M5 chain/exposure model + matrix
 |                  /
 v                 v
M6 filings/catalysts/risks/concentration evidence
 |
 v
M7 deterministic versioned reports
 |
 v
M8 optional narrative + claim audit
 |
 v
M9 bounded agent harness

MX optional licensed PIT estimates / active+delisted / stronger validation
   runs alongside the program but unlocks only its own stronger claims
```

M5 schema and content discovery may run alongside M2/M3, but comparative chain output cannot ship
before compatible deterministic company outputs exist. M7 must precede M8 so a report never depends
on a successful model response. M9 requires the report control plane and audit boundaries.

## 5. Pre-Job 0 — observation-version as-of correctness

**Objective:** make version availability explicit and provide separate current and fail-closed as-of
readers before any historical research is rerun.

**Child plan:** `docs/plans/2026-08-24-fundamental-observation-asof.md`.

### P0.1 Contract and migration

- freeze `true_pit`, `capture_bounded`, `current_vintage`, and `unknown` semantics;
- add an additive, idempotent version-availability/evidence schema;
- keep `filing_published_at` as the original filing fact rather than overloading it;
- preserve every existing observation and old result;
- explicitly classify legacy rows without inventing historical publication timestamps;
- index the as-of selection path.

### P0.2 Reader split

- add an explicit current-panel reader;
- add as-of reader with mandatory evidence policy;
- return selection/evidence metadata;
- keep old current-page consumers compatible;
- make `true_pit` exclude rows whose version availability is not positively established.

### P0.3 Historical consumer integration

- route historical scoring/research through the as-of reader behind explicit mode/version control;
- preserve existing old results and method versions;
- bind `inputs_hash` to the selected observation versions and evidence policy;
- document which historical spans remain unavailable for true-PIT replay.

### P0 gate

- a 2023 restatement cannot enter a 2021 `true_pit` read;
- unknown restatement timing does not inherit the original filing date;
- capture-bounded behavior matches a documented cutoff rule and is never labeled true PIT;
- current page still selects the newest accepted content;
- unchanged refresh and filing-date recovery remain idempotent;
- migration reruns are no-ops;
- real SQL integration tests, not mocks alone, prove selection order;
- historical claims remain blocked until M3 reruns.

**Stop condition:** if no source evidence can date a content version, retain it as current-vintage.
Do not solve the problem with a guessed lag.

## 6. M1 — canonical evidence, validity, and governed inputs

**Objective:** turn the existing observation table into a trustworthy multi-source evidence layer
whose selected facts, exclusions, entities, and provenance are reproducible.

### M1.1 Input-eligibility engine version

Likely files:

- `src/uw_scan/fundamentals/statements.py`;
- a new focused validity/policy module under `src/uw_scan/fundamentals/`;
- `src/uw_scan/storage/fundamental_obs.py` or a split domain module;
- `src/uw_scan/worker/jobs/fundamental_scoring.py`;
- score/method migrations and fixtures.

Work:

- define each violation's effect: field exclusion, observation exclusion, confidence downgrade, or
  warning-only;
- prevent excluded values entering feature and composite calculations;
- record exclusion reasons and counts in results;
- create a new method/engine version rather than rewriting old score rows;
- verify accounting identities and plausible shares/currency/unit contracts at ingest and derive.

Exit proof:

- a deliberately violated field cannot influence a new score or anchor;
- the raw source row and violation remain inspectable;
- valid fields in a partially invalid observation follow the declared policy;
- old engine rows replay unchanged.

### M1.2 Source reconciliation and canonical facts

Work:

- re-probe UW, current Massive capabilities, and SEC on a representative issuer matrix;
- persist source roles, coverage, rate/cost/license constraints, and payload identities;
- add SEC filing/accession/amendment evidence required for PIT upgrades and gap fill;
- preserve raw disagreements;
- implement a versioned canonical-selection rule and as-of reader;
- cover `us-gaap`, `ifrs-full`, foreign issuers, ADR ratio, currency, NCI, and current-debt behavior;
- make explicit `na` the terminal fallback.

Exit proof:

- three hand-inspected issuers, including one foreign private issuer, reproduce canonical facts;
- conflicting values and the selected winner are both queryable;
- selection changes create a new rule/result version;
- provider outage leaves prior evidence readable and reports stale/partial, not blank;
- no source is called from an ordinary page read.

### M1.3 Typed provenance foundation

Work:

- introduce result-specific association tables with foreign keys;
- preserve `source_obs_ids` as a compatibility field until all consumers migrate;
- record exclusions, alternatives, canonical rule, and transformation stage;
- supply repository methods for evidence drill-down;
- join tables to the dataset registry/freshness policy.

Exit proof:

- deleting or inventing a referenced observation is prevented by schema;
- a result can enumerate used, excluded, and conflicting observations;
- old array-backed rows remain readable with a visibly legacy provenance state.

### M1.4 Governed company identity and type

Work:

- historize issuer identity, security/share-class mapping, ticker changes, currency, ADR ratio, sector,
  and company type;
- seed deterministic candidates but require evidence/override status;
- separate company type from chain membership;
- define refusal for unclassified/incompatible issuers;
- close the measured classification gap before broad valuation comparisons.

Exit proof:

- classification coverage and unclassified list are persisted;
- a type change creates a new validity interval and invalidates dependent results;
- one issuer with multiple securities does not silently duplicate fundamentals;
- type-dependent valuation refuses rather than using a generic fallback.

### M1 gate

Canonical facts reproduce at arbitrary allowed as-of cutoffs; violated inputs cannot leak into new
math; provenance is enforceable; issuer/type mappings are historized; real ingest → DB → canonical
read passes on the correct database tier.

## 7. M2 — deterministic engine v2 and run ledger

**Objective:** create one pure, modular, versioned engine used by company, Radar, chain, and report
products.

### M2.1 Module split and pure derivations

- split the current near-1,000-line valuation and anchor-job modules by cohesive domain seam before
  adding new behavior;
- preserve public imports, Pydantic identities, and OpenAPI names;
- implement unit/currency/share normalization, TTM, growth/acceleration, margins, FCF, leverage,
  coverage, capital efficiency, concentration primitives, and feature validity;
- add worked examples and property/accounting-identity tests;
- keep DB/job orchestration outside pure computation modules.

### M2.2 Valuation engine v2

- route by historized company type;
- define per-method applicability and refusal;
- compute bear/base/bull scenarios and ordered price anchors;
- include sensitivity, method disagreement, stale inputs, FX/share-basis evidence, and confidence;
- bind historical research/runtime to the same split/corporate-action reference frame;
- make no universal value-direction assumption across metrics with negative/zero numerators.

### M2.3 Independent dimensions and priority aggregation

- persist operating quality, growth, balance-sheet resilience, cash conversion/capital efficiency,
  valuation, evidence quality, and supported change/event dimensions independently;
- make missing-dimension and renormalization rules explicit;
- store scope/authority (`descriptive`, `research_priority`, etc.) with the aggregate;
- do not turn technical context into the fundamental composite;
- expose why a name was prioritized, not merely its rank.

### M2.4 Fundamental run ledger

- persist requested scope/as-of/evidence policy/method versions/stage state/input and output hashes;
- typed result associations and stage-level retries;
- cached recompute versus external refresh modes;
- active-run uniqueness and idempotency;
- enqueue/cancel/status under the jobs mutation surface;
- heartbeat, queue age/depth, coverage, exclusion, and cost telemetry.

### M2 gate

- three hand-worked issuers reproduce features, anchors, dimensions, abstentions, and provenance;
- same inputs and versions reuse the same logical result;
- changing source version, availability policy, company type, method, or validity decision changes
  `inputs_hash` or compatibility;
- old and new engines coexist;
- engine output is complete with all models disabled;
- module-size budget is respected.

## 8. M3 — corrected research and claim-permission registry

**Objective:** rerun the research on the corrected evidence/method contract and translate evidence
into explicit product permissions without downgrading the product goal.

### M3.1 Reproduce the old research under old semantics

- freeze the original universe, features, horizons, adjustment policy, and artifacts;
- prove the old results reproduce from the old method;
- identify any irrecoverable input or environment difference;
- never overwrite the old verdict.

### M3.2 Rerun under corrected semantics

- use `true_pit` where available and report unavailable coverage separately;
- rerun a clearly labeled capture-bounded sensitivity rather than mixing it with true PIT;
- use split-consistent Silver/lake price inputs and compatible shares;
- persist every row, exclusion, configuration, metric, and reproduce command;
- report cross-sectional width per date, survivorship, delisting, turnover, liquidity, and regime
  limits;
- repeat leakage, reversal, valuation-control, and multiple-testing checks;
- compare old/current-vintage, capture-bounded, and true-PIT conclusions.

### M3.3 Product claim registry

For every dimension/composite define:

- production universe and membership rule;
- method/version and data capability;
- allowed surface behavior;
- allowed language;
- prohibited inference;
- expiry/revalidation rule;
- supporting research artifact;
- kill or downgrade condition.

Possible outcomes are all valid:

- validated research-priority ordering;
- descriptive/filter-only dimension;
- supported directional risk monitor;
- null or mixed result that forbids direction;
- insufficient PIT coverage requiring data procurement.

### M3 gate

- corrected runs are durable and self-checking;
- old versus corrected results are reconciled, not silently replaced;
- every UI ordering/label has a registry permission;
- a null result preserves the deterministic company/chain/report products while withholding the
  unsupported direction;
- no return or strategy claim is promoted from software-test success.

## 9. M4 — company product v2 and Fundamental PM Research Radar

**Objective:** expose the trustworthy engine as the company research surface and the PM's
cross-universe attention-routing surface.

### M4.1 API contract and state model

- current compatible result, history, coverage, provenance, conflicts, and run status endpoints;
- explicit `computed_at`, source freshness, as-of, evidence policy, engine/rule versions;
- distinguish no coverage, no compatible run, stale run, unsupported capability, failed run, and
  transport error;
- generated TypeScript contract and backward compatibility.

### M4.2 Single-company view v2

- trends with period-level evidence/violation state;
- independent dimensions with input drill-down;
- valuation scenarios/anchors/sensitivity/disagreement/refusal;
- coverage, confidence reasons, unknowns, and source conflicts;
- compatible history and change view;
- queued compute/refresh through jobs;
- real UI smoke and accessibility/responsive states.

### M4.3 Radar data product

- freeze universe membership snapshot, as-of, evidence policy, and compatible method version;
- expose independent dimensions, confidence, coverage, freshness, and change since prior run;
- filtering and saved research scopes;
- ordering only according to M3 permission;
- no hidden renormalization across rows with different missing dimensions;
- link to company, comparison, chain, and report creation.

### M4.4 Radar UI

- dense but explainable research table/matrix;
- priority reason and largest evidence change visible without opening the name;
- full provenance and method basis one drill-down away;
- partial/unavailable names stay visible with their denominator state;
- descriptive mode has neutral visual language and cannot imply buy/sell ranking;
- version/as-of mixing is rejected rather than silently rendered.

### M4 gate

- all displayed numbers trace to persisted typed results and evidence;
- current/stale/partial/error states are distinguishable in API and browser;
- a name with invalid inputs shows the engine abstention, not a polished value;
- Radar ordering and labels exactly match the M3 registry;
- real enqueue → worker → DB → API → browser path passes after worker restart;
- screenshots live under `output/playwright/`.

## 10. M5 — general industry-chain and exposure product

**Objective:** move beyond ticker membership to a versioned, evidence-backed model of where companies
participate in a chain and how research conditions cluster across it.

### M5.1 Versioned domain taxonomy

- tables for research domain, industry, layer, chain, taxonomy version, validity, aliases, and
  membership provenance;
- migrate/dual-read existing `watchlist_chain` without breaking the shipped filter rail;
- separate semantic membership from economic exposure and named relationship;
- persist who/what approved a taxonomy assertion and its evidence class;
- AI infrastructure content pack first.

### M5.2 Company exposure model

Represent exposure separately from membership:

- role: supplier, manufacturer, component, integrator, customer, beneficiary, competitor, or other
  controlled vocabulary;
- direction and counterparty when evidenced;
- magnitude basis: disclosed revenue, customer concentration, segment share, capacity, capex, or
  qualitative/unknown;
- confidence and disclosed/inferred status;
- source observation/document and validity interval;
- disagreement/supersession.

No hand-authored percentage masquerades as measured exposure.

### M5.3 Compatible chain aggregates

- roll up current compatible company results at read time or through a versioned cache;
- common as-of/engine/evidence-policy basis;
- full membership denominator and observed numerator;
- coverage/data-quality first encoding;
- valuation pressure, dimension distributions, concentration, and change only where allowed;
- abstain when no common compatible basis exists.

### M5.4 Matrix and drill-down

- layer × chain matrix with domain/industry navigation;
- click cell → company/exposure list → company/comparison/report;
- pivots by layer, company type, and supported exposure role;
- provenance for memberships and exposures;
- hatched unavailable cells, never invisible missing names;
- no causal propagation display without an evidence-backed edge model.

### M5.5 Optical-communication extensibility proof

- add an optical-communication chain using only general schema/ingest/report contracts;
- cover representative upstream components, DSP/switch silicon, lasers, modules, systems, and cloud
  customers where evidence permits;
- record unsupported relationships and data gaps;
- prove no domain-specific orchestration or scoring fork is needed.

### M5 gate

- matrix membership equals the versioned taxonomy snapshot;
- every exposure or named relationship links to evidence and type;
- cell calculations reproduce from compatible company outputs and report numerator/denominator;
- optical communication is added without schema or workflow special casing;
- the product answers more than the existing watchlist chain filter;
- node-link/propagation work stays killed if measured named-edge yield is too low.

## 11. M6 — filing, catalyst, risk, and concentration evidence

**Objective:** build durable event and concentration ledgers that can update company and chain
research without letting a model invent events.

### M6.1 Discovery gate

- preregister issuer/document sample and extractable classes;
- measure filing availability, field/document coverage, extraction precision, false-positive rate,
  foreign-issuer behavior, and runtime/cost;
- persist complete discovery artifacts;
- kill weak classes instead of filling them with generated guesses.

### M6.2 Filing and concentration ledger

- SEC document/accession/version storage;
- customer, segment, geographic, supplier, backlog, capex, debt/maturity, and guidance facts only
  where reliably extractable;
- multi-period trend with exact document citations;
- disclosed versus inferred identity;
- idempotent reprocessing and amendment handling;
- current page and chain exposure consumers.

### M6.3 Catalyst/event ledger

- typed events: earnings, guidance, filing/amendment, product/regulatory/capacity/capital-allocation
  events where sources and rights support them;
- event time, first-known time, affected facts/companies/chains, evidence, status, and supersession;
- deterministic materiality/routing rules;
- no unlicensed news dependence and no generated event facts.

### M6.4 Risk and invalidation contract

- deterministic risk facts and thresholds separated from narrative inference;
- numeric invalidation conditions trace to engine/report inputs;
- unknown risk blocks remain visible;
- change events identify which computations/reports are stale without automatically publishing.

### M6 gate

- required extraction classes pass the preregistered yield/precision gate or are explicitly killed;
- a real filing produces versioned facts, exposures/events, affected-result routing, and UI evidence;
- an amendment preserves the predecessor and updates only compatible downstream work;
- foreign-issuer example works or visibly abstains;
- no generated prose is required to establish a catalyst or risk fact.

## 12. M7 — deterministic versioned report product

**Objective:** create the durable research object before adding narrative or autonomous orchestration.

### M7.1 Report/control ledger

- research run, scope, task manifest, input manifest, report, version, block, claim, claim-evidence,
  audit, approval, feedback, usage/cost, and omitted-capability tables;
- company, comparison, industry, chain, sub-chain, earnings, event-delta, and watchlist report types;
- enforceable typed evidence associations;
- compatibility, supersession, stale, and prior-comparable rules;
- append-only published history.

### M7.2 Deterministic assembly

- assemble coverage, statements, dimensions, valuation, chain exposure, catalysts, risks,
  invalidations, disagreements, and unknowns from compatible outputs;
- freeze all versions/as-of/evidence policy in the manifest;
- render an explicit unsupported-capability section;
- compute material delta against the previous comparable report;
- refuse mixed/incompatible blocks.

### M7.3 Report UI and workflow

- draft, partial, audit-failed, approval-required, published, superseded, and stale states;
- evidence/provenance drill-down;
- prior-version comparison;
- operator approval and feedback;
- company and chain entry points;
- printable/readable presentation without making PDF the canonical record.

### M7 gate

- an old report replays byte-for-value from its original manifest after new data/methods arrive;
- a new version explains material changes;
- every factual block has typed evidence or a declared derivation;
- mixed versions/as-of bases are rejected;
- report remains complete enough to use without narrative;
- real report run → persisted version → API/UI path passes.

## 13. M8 — optional narrative and claim audit

**Objective:** add constrained explanatory prose without making the model part of the evidence or
deterministic method.

### M8.1 Dedicated fundamental narrative lane

- separate queue/repository/models/worker role from trade insights;
- provider-neutral runner interface, deployable provider first;
- persisted bounded payload, prompt, schema, resolved model, raw failure, usage, and output;
- provider feature flag, heartbeat, queue depth/age, restart and outage behavior;
- no secrets or unapproved raw source payloads in model context.

### M8.2 Claim model and deterministic audit

- disclosed fact, derivation, inference, dispute, and unknown claim types;
- numeric equality/tolerance, evidence existence, source quality, PIT/as-of, wording, coverage, and
  invalidation checks;
- per-claim pass/warn/fail/unverifiable;
- failed facts suppressed or visibly rejected;
- provider output can never change deterministic blocks.

### M8.3 Report integration

- audited narrative is an optional versioned block;
- provider failure leaves deterministic report publishable;
- prior narrative is never silently reused against changed inputs;
- model/version/prompt changes are visible in provenance and delta.

### M8 gate

- real enqueue → dedicated worker → structured output → audits → report/UI passes;
- numeric hallucination and fact/inference language adversarial tests fail closed;
- disabled/down provider leaves M4/M5/M7 usable;
- fundamental outputs never enter the trade-insight outcome ledger;
- audit-failed claims cannot appear as report facts.

## 14. M9 — bounded agent harness

**Objective:** allow an agent to plan bounded research refresh/draft workflows over approved Argon
surfaces after reports and audits are durable.

### M9.1 Least-privilege command/read surface

- authenticated reads for facts, coverage, compatible results, runs, reports, audits, and versions;
- typed enqueue/cancel commands only for approved jobs;
- distinct service identity, route authorization, rotation/revocation, actor ID, and redaction;
- idempotency, time/call/token/cost budgets, retries, cancellation, and termination.

### M9.2 Question-to-draft workflow

- resolve report type, domain/chain/tickers, as-of, freshness, and budget;
- freeze scope before work begins;
- build a bounded task DAG;
- prefer compatible cached results;
- persist plan, calls, outputs, omissions, and termination reason;
- create draft only; operator publication by default.

### M9.3 Event-triggered delta drafts

- filing and earnings triggers first;
- event → affected facts → computations → reports routing;
- deduplication, cooldown, grouping, and no-change suppression;
- licensed news/estimate triggers only after their capability gate;
- never publish or alert on an unaudited generated claim.

### M9.4 Scheduled self-tending mode

- stale evidence/report patrol;
- bounded recompute and delta drafting;
- provider/data/model budget telemetry;
- operator queue and silence discipline;
- one-week unattended soak before any authority increase;
- auto-publication remains off absent a separate policy decision.

### M9 gate

- harness cannot mutate facts, methods, weights, company types, canonical rules, or approved taxonomy;
- every mutation routes through a typed persisted job;
- repeated identical triggers deduplicate;
- cancellation and budget exhaustion end cleanly with a partial/failed record;
- adversarial prompts cannot escalate authority or leak secrets;
- one-week soak shows no runaway loops, hidden spend, or audit bypass;
- reports remain reproducible with the harness absent.

## 15. MX — optional empirical and licensed-data upgrades

These tracks do not block the descriptive company, chain, report, or harness products. They do gate
stronger directional claims.

### MX.A Active-plus-delisted validation

- construct historical universe by knowledge date with permanent identifiers;
- include delisting returns and membership changes;
- rerun corrected dimensions/composite and quantify survivor-only bias;
- measure OOS stability, regimes, turnover, liquidity, costs, and capacity;
- update only the exact claim permissions supported.

### MX.B PIT estimates vendor bake-off

- common field, PIT correction, history, entitlement, retention, display, and LLM-processing contract;
- same preregistered revision/dispersion/breadth study across vendors;
- compare coverage, timing, corrections, incremental value, operational access, and total cost;
- buy at most one provider or reject all.

### MX.C Licensed estimates adapter

Only after MX.B passes:

- immutable estimate, actual, and guidance observations;
- revision/dispersion/breadth features with separate method version;
- company/Radar/chain/report blocks and event triggers;
- explicit capability disclosure when unavailable.

### MX gate

No provider contract, successful API call, or attractive in-sample result alone unlocks a directional
product claim. Rights, PIT integrity, exact-universe OOS evidence, and incremental value must all
pass.

## 16. Program gates and authority ladder

| Gate | Required evidence | Product authority unlocked |
|---|---|---|
| P0 | version-level as-of selection, fail-closed unknowns, migration/reader proof | corrected replay capability |
| G1 | canonical PIT facts, validity exclusions, typed provenance, governed identities | engine v2 inputs |
| G2 | worked examples, deterministic version/hash/refusal behavior, real run ledger | deterministic products |
| G3 | corrected durable research and claim registry | allowed Radar ordering/wording |
| G4 | company/Radar API+UI states and real worker smoke | company/Radar release |
| G5 | evidence-backed exposures, compatible aggregates, optical proof | chain release |
| G6 | extraction yield/precision and amendment/event routing | catalyst/risk blocks |
| G7 | replayable report and prior-version delta | durable research product |
| G8 | claim audit and provider-down degradation | optional narrative |
| G9 | least privilege, budgets, adversarial tests, soak | scheduled drafts |
| GX | active+delisted PIT/OOS/regime/cost/operator approval | separate ranking proposal only |

Authority advances monotonically:

```text
raw evidence
  -> descriptive calculation
    -> research-priority ordering
      -> directional monitor (separate evidence)
        -> investment ranking (GX + new decision)
```

Failure at one authority level does not delete lower-level products. It prevents stronger language
and behavior.

## 17. Standard child-plan requirements

Before code begins on any milestone after Pre-Job 0, write a child plan that names:

- exact scope and explicit non-goals;
- files/modules/migrations/API models/routes/jobs/UI paths;
- data and time contracts;
- failing tests first and expected failure;
- migration/backfill/rollback/feature-flag behavior;
- real worker/database/API/UI smoke where relevant;
- dataset registry, freshness, observability, budget, and licensing changes;
- completion gate and what remains blocked;
- milestone commit/PR boundaries, while respecting the standing rule that no commit occurs without
  explicit user authorization.

Applicable verification baseline:

```text
uv run pytest
uv run ruff check .
uv run python scripts/check_no_yahoo.py
cd web && npm run gen:types        # after API contract change
cd web && npm run typecheck
cd web && npm run test
cd web && npm run lint
cd web && npm run build
```

Database work runs migrations twice and repository integration tests against the test database.
Provider-sensitive research names the host/source snapshot. User-visible routes get Playwright
coverage and artifacts under `output/playwright/`. Pure docs/research work runs its exact artifact
self-check and does not claim application behavior from prose review.

## 18. Rollout, rollback, and operations

### Data and schema

- additive idempotent migrations;
- no source-history rewrite in a feature PR;
- backfills persist run state, resume, and never advertise partial coverage as complete;
- canonical-rule rollback selects the prior rule/version rather than deleting observations;
- dataset registry and gap/freshness policy ship with each new persisted domain.

### Jobs and providers

- new jobs/providers start behind independent flags until schema, credentials, and smoke pass;
- worker role, scheduler/compose wiring, heartbeat, queue telemetry, restart procedure, and budget ship
  together;
- stopping a worker preserves queued rows and inspection;
- provider keys never enter local model subprocesses, prompts, logs, manifests, or reports.

### API and UI

- additions remain backward compatible through client generation and consumer release;
- reads do not acquire hidden writes;
- feature-off state preserves evidence and renders unavailable/stale clearly;
- dual-read parity precedes replacement of the watchlist taxonomy path;
- browser success follows fresh API/database reads, not in-process objects.

### Reports and harness

- published reports are append-only;
- narrative and harness can be disabled independently;
- revoking the harness identity stops commands but not report readability;
- budget/auth/audit failure creates a persisted terminal state, never a half-published report.

## 19. Observability

Each production domain exposes:

- last attempted/successful run and heartbeat;
- queue depth and oldest age;
- rows by evidence class, source, coverage, violation/exclusion, compatibility, and staleness;
- provider calls, failures, throttles, official counters where available, and estimated cost;
- method/rule versions and active-pointer drift;
- report draft/publish/stale/audit-fail counts;
- agent dedup/cooldown/budget/termination counts.

Alerts target actionable failure: provider outage, stale facts beyond policy, stuck run, PIT-class
regression, exclusion spike, incompatible active version, audit-fail spike, budget exhaustion, or
publication failure. Legitimate `na` is a research disclosure, not an operations incident.

## 20. Program completion test

The program reaches its intended descriptive-research completion when the operator can request:

> As of a stated date, research the US optical-communication chain. Compare upstream components,
> switch silicon/DSP, lasers, modules, systems, and cloud customers. Show operating momentum,
> valuation pressure, concentration, catalysts, risks, evidence conflicts, and missing capabilities;
> then dive into three companies and explain what changed from the prior report.

Argon must then:

1. freeze scope, universe, as-of, evidence policy, taxonomy, methods, and budget;
2. disclose coverage and unsupported capabilities before conclusions;
3. run or reuse compatible deterministic company and chain calculations;
4. route attention through the Radar without exceeding its claim permission;
5. preserve every fact, derivation, inference, dispute, and unknown with provenance;
6. assemble a versioned report and prior-version delta;
7. optionally add only audited narrative;
8. refresh only affected work through typed bounded commands;
9. remain reproducible with the model and agent disabled;
10. make no automatic investment or trade decision.

## 21. Immediate execution order in this worktree

1. Execute Pre-Job 0 from its child plan.
2. Review its evidence and classify the usable true-PIT/capture-bounded/current-vintage spans.
3. Write the M1 child design/plan using the observed P0 distribution—do not guess it now.
4. Complete M1 gate before creating engine-v2 output.
5. Continue milestone by milestone, updating this status table with reviewed evidence.

| Work item | Status on 2026-08-24 | Next proof |
|---|---|---|
| Design reconciliation | written, uncommitted | reviewer acceptance |
| Pre-Job 0 plan | written, not implemented | P0 integration tests and migration |
| M1–M9 | planned at program level | child design/plan after predecessor gate |
| Production/reference-doc drift | known | reverify before release claims |

No commit, push, PR, or change to the primary checkout is authorized by this document.
