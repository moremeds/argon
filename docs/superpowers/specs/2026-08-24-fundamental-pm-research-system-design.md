# Fundamental PM Research System — Reconciled Design

> **Status:** approved program direction; implementation is gated by the child plans named here.
>
> **Authority:** this document reconciles and continues
> `2026-08-10-fundamental-pm-agent-design.md`. It does not erase the earlier design or its measured
> research record. Where the two conflict, this document governs work begun after 2026-08-24.
>
> **Baseline:** Argon `v0.12.16`, commit `86161f1d`.

## 1. Decision

Build the original Fundamental PM program as one evidence-driven research system. Do not redefine
the program as an observation-as-of repair, a single stock card, a score, or a Radar page.

The system has six connected products:

1. an immutable, point-in-time evidence foundation;
2. a deterministic company analysis engine;
3. a Fundamental PM Research Radar for prioritizing what deserves human attention;
4. a general industry-chain and company-exposure research surface;
5. versioned, evidence-linked company, comparison, chain, and event reports;
6. a bounded agent harness that can refresh and draft research but cannot change facts or methods.

`fundamental-observation-asof` becomes **Pre-Job 0**. It is a correctness prerequisite for later
historical claims, not the project definition.

## 2. North-star user outcome

The operator can ask:

> Research a company, compare a group of companies, or map a narrow industry chain as of a stated
> date. Show the operating evidence, valuation, research-priority dimensions, catalysts, risks,
> chain exposures, disagreements, missing data, and what would invalidate the thesis. Preserve the
> answer as a versioned report that can later explain what changed.

The system must answer without pretending that:

- a research-priority score forecasts returns;
- current-vintage financial history is true point-in-time history;
- taxonomy membership proves a supplier/customer relationship;
- a generated narrative is evidence;
- a visually persuasive page is a completed research method;
- unavailable institutional data was approximated by an LLM.

## 3. Relationship to Argon's desk master plan

This program is subordinate to the repository-wide goal ladder, not a replacement for it.

- Stage 1: trustworthy evidence, deterministic calculations, company/Radar/chain decision surfaces.
- Stage 2: durable report control plane, bounded refresh/draft harness, self-tending research loops.
- Stage 3 and beyond: no automatic proposal or trade authority is granted by this program.

The program does not displace Argon's Stage-1 signal-to-alert deliverable. Fundamental research may
later emit evidence-change alerts, but alert plumbing and this research program remain separate
lanes with explicit integration points.

## 4. Products and boundaries

### 4.1 Evidence foundation

Stores what a source said, when the underlying economic period occurred, when the specific content
version became knowable, when Argon first observed it, and what evidence supports the availability
claim. It preserves source conflicts and restatements.

### 4.2 Deterministic company engine

Computes normalized statements, features, independent research dimensions, valuation anchors,
confidence, abstentions, coverage, and invalidation inputs. Every number is reproducible without a
model provider.

### 4.3 Fundamental PM Research Radar

Answers: **what deserves research attention now, and why?**

It is a triage surface over independently interpretable dimensions such as operating quality,
growth, balance-sheet resilience, valuation position, estimate/catalyst evidence when licensed,
data quality, and change since the prior compatible run. It may order names only inside scopes where
the exact ordering claim has passed its evidence gate. Otherwise it remains a filterable descriptive
surface.

It is never labeled expected return, buy score, conviction, or portfolio weight.

### 4.4 Industry-chain research surface

Answers: **where in a chain are evidence, valuation pressure, concentration, catalysts, and unknowns
clustering?**

The data model is general:

```text
research_domain
  -> industry
    -> layer
      -> chain
        -> company_exposure
          -> evidence
```

AI infrastructure is the first content pack. Semiconductor/optical communication is the required
extensibility proof. Adding a later domain must not require a new scoring engine, report schema, or
agent orchestration path.

The first comparative rendering remains a layer/chain matrix because row position has supply-chain
meaning and the present taxonomy does not justify a dense causal node-link graph. Named edges may be
added only when supported by typed evidence.

### 4.5 Versioned report product

Assembles deterministic blocks and optional audited narrative into a replayable report. A report
freezes scope, as-of, evidence manifest, taxonomy, method versions, computations, claims, audits,
costs, omissions, and prior-version relationship.

Reports remain useful when all model providers are disabled.

### 4.6 Bounded agent harness

Plans and invokes already-approved jobs, reuses compatible outputs, drafts reports, and records every
decision. It has no raw database write access and cannot change method parameters, company type,
canonical-source policy, taxonomy evidence, score weights, or published history.

## 5. Evidence and time contract

### 5.1 Four clocks

Every fact or observation version must distinguish:

| Clock | Meaning |
|---|---|
| `period_end` | economic period described by the fact |
| `published_at` | source/publication time for the specific content version, when known |
| `available_at` | earliest instant the selected evidence class permits a consumer to use it |
| `first_observed_at` | when Argon captured the version; never silently equal to publication time |

`as_of` selection is based on version availability, not period end, fetch order, maximum observation
ID, or the original filing date of a later restatement.

### 5.2 Evidence classes

The minimum closed vocabulary is:

- `true_pit`: positive version-level publication/amendment evidence supports `available_at`;
- `capture_bounded`: Argon can prove it observed the version by a capture time but cannot recover the
  original market publication time;
- `current_vintage`: a historical snapshot with no defensible version-availability timeline;
- `unknown`: insufficient evidence even for a bounded availability claim.

Each class has a documented reader policy. A `true_pit` replay fails closed for all other classes.
No migration default upgrades old rows to `true_pit`.

### 5.3 Two statement readers

- `current_statement_panel(...)`: newest accepted content version for today's deterministic page.
- `statement_panel_as_of(as_of, evidence_policy, ...)`: only versions admitted by an explicit
  availability policy, with selection metadata returned to the caller.

An ambiguous `statement_panel()` must not remain the contract for both purposes. Compatibility may
temporarily route the old name to the current reader, with deprecation made explicit.

### 5.4 Restatements and corrections

A changed normalized payload creates a new immutable observation. Availability belongs to that
specific content version. A later restatement must never enter an earlier `true_pit` replay. Source
date corrections are preserved as evidence events or a typed claim; they do not silently rewrite
the past.

### 5.5 Canonical selection

Raw source observations are never deleted merely because another source wins. Canonical selection
is a versioned rule over eligible source observations and must record:

- selected observation;
- alternative observations;
- rule and rule version;
- discrepancies and tolerance;
- selection reason;
- as-of and evidence policy.

The expected source roles are UW statement backbone, Massive metadata/cross-check where current,
SEC filing/XBRL gap fill and amendment evidence, and explicit `na` otherwise. Actual provider roles
must be revalidated before implementation; the design does not confer rights or coverage.

## 6. Deterministic method contract

The computation order is:

```text
INGEST -> VALIDATE -> CANONICALIZE -> DERIVE -> VALUE -> DIMENSIONS -> PRIORITIZE
```

Every stage consumes typed upstream outputs and emits an immutable result with:

- `run_id`;
- `engine_version` or rule version;
- `inputs_hash`;
- typed source/result associations;
- as-of and evidence policy;
- coverage and abstention reasons;
- created/computed timestamps;
- compatibility/supersession state.

Python owns every number. A model cannot create or change a source fact, feature, score dimension,
valuation anchor, confidence, exposure, or invalidation threshold.

### 6.1 Input validity

Data-quality violations affect computation eligibility, not only display. The engine must define per
feature which violation classes:

- exclude the field;
- exclude the statement/version;
- reduce confidence;
- permit use with a visible warning.

The current behavior—compute from a value and only suppress it on the page—is not acceptable for a
new engine version.

### 6.2 Company-type routing

Company type is historized, separately governed, and evidence-linked. It cannot be inferred anew on
every read from a mutable many-to-many watchlist taxonomy. Unclassified names abstain from methods
that require a type; they do not silently receive a generic valuation.

### 6.3 Valuation

Valuation produces scenarios, ordered anchor bands, applicability, sensitivity, method disagreement,
confidence, and refusal reasons. Research and runtime must share a corporate-action reference frame:
prices, shares, per-share values, and split adjustments cannot mix current split-basis shares with
unadjusted historical close.

### 6.4 Research-priority dimensions

Persist dimensions independently. Composite or priority aggregation must carry scope and permission:

- `descriptive`: render and filter, no ordering claim;
- `research_priority`: order within a validated scope for analyst attention only;
- `directional_monitor`: allowed only for a separately validated within-name direction;
- `investment_ranking`: unavailable until broad PIT/OOS, active-plus-delisted, regime, cost, and
  operator approval gates pass.

The default program authority stops at `research_priority`.

## 7. Provenance and run control

`source_obs_ids BIGINT[]` may remain readable for compatibility but is not the final provenance
contract. New result domains use typed association tables with foreign keys. Provenance must answer:

1. Which exact observations supported this value?
2. Which versions/rules transformed them?
3. Which values were excluded and why?
4. Which alternative source facts disagreed?
5. Can the result be replayed after new data arrives?

A shared fundamental run ledger owns scope, requested as-of, evidence policy, method versions,
stage state, row counts, retries, failure, cost, and termination. Jobs are idempotent by logical
scope and input identity. Read routes remain read-only; mutations go through typed job endpoints.

## 8. Surface contracts

### 8.1 Single-company view

Must render:

- current compatible status and computed/stale timestamps;
- financial trends with per-period evidence status;
- independent dimensions and their inputs;
- valuation anchors, assumptions, sensitivity, and disagreement;
- catalysts, risks, concentration, and explicit unknowns when supported;
- version/as-of/evidence policy;
- provenance drill-down and source disagreement;
- `na`, partial, stale, incompatible, provider-unavailable, and failed-run states.

Transport error, no coverage, no compatible result, and stale result are distinct states.

### 8.2 Radar

Must support:

- universe and membership snapshot;
- as-of, method version, and evidence-policy lock;
- filterable independent dimensions;
- coverage/confidence as first-class filters;
- change since prior compatible run;
- explicit ordering permission and explanation;
- jump to company, comparison, chain, and report workflows.

No Radar row is considered comparable if it silently mixes engine versions or incompatible as-of
bases.

### 8.3 Industry-chain matrix

Every cell reports numerator and full membership denominator. A cell with no common compatible
version/as-of renders unavailable. Coverage or data quality may be the first fill encoding;
comparative score color requires a validated scope. Exposure strength and named relationships must
be evidence-linked, historized, and distinguish disclosed fact from analyst inference.

### 8.4 Reports

Supported types include company, comparison, industry, chain, sub-chain, earnings, filing/event
delta, and watchlist review. Published reports are append-only. New versions explain material
changes from the prior comparable version.

## 9. Narrative and claim audit

Narrative is an optional report block produced from a persisted, bounded payload in a dedicated
fundamental queue. It is not a reuse of the trade-insight outcome ledger.

Claims are typed as:

- disclosed fact;
- deterministic derivation;
- bounded inference;
- disputed/conflicting;
- unsupported unknown.

Audit checks numeric equality/tolerance, evidence existence, as-of compliance, source quality,
fact/inference wording, missing unknowns, and invalidation conditions. A failed claim is suppressed
or visibly fails; fluent text cannot override the verdict.

## 10. Agent authority

The harness may:

- resolve a user request into an approved report scope;
- inspect coverage and freshness;
- enqueue approved ingest/compute/report jobs;
- reuse compatible results;
- draft and compare report versions;
- stop on budget, evidence, audit, or capability limits.

The harness may not:

- write raw facts or SQL;
- change canonical selection, taxonomy, company type, methods, or weights;
- turn a descriptive dimension into a directional claim;
- publish automatically by default;
- stage or execute trades;
- conceal partial work, unsupported capabilities, or provider failures.

Every command has actor, authorization, idempotency key, budget, status, retry, cancellation, and
termination reason.

## 11. Failure behavior

The system fails closed at the claim boundary, not by making the whole product blank.

- Unknown version availability: excluded from `true_pit`; current view may still use it with class.
- Violated numeric input: abstain or downgrade according to versioned rule.
- Source disagreement: retain alternatives, select by rule, show conflict.
- Missing company type: type-dependent valuation abstains.
- Thin cross-section: no comparative ordering; descriptive dimensions remain.
- Model outage: deterministic pages and reports remain usable.
- Agent timeout/budget: persisted partial draft with omissions and termination reason.
- No common chain basis: unavailable cell with coverage detail, never mixed values.

## 12. Rollout and compatibility

- Migrations are additive and idempotent.
- Existing observations and outputs remain immutable and readable.
- Current pages retain current-vintage behavior until an explicit product change.
- As-of consumers opt into the new reader; old research is not silently relabeled.
- New engine/rule versions coexist with old versions.
- Feature flags separate deterministic pages, Radar, chain, narrative, reports, and harness.
- A rollback switches readers/rules/workers; it does not delete evidence or published reports.
- Every production milestone includes the real enqueue/worker/DB/API/UI path where applicable.

## 13. Delivery sequence

```text
Pre-Job 0: honest observation-version availability and fail-closed as-of reader
    -> M1: canonical evidence, data validity, company-type and typed provenance foundation
        -> M2: deterministic engine v2 and run ledger
            -> M3: corrected research and permission registry
                -> M4: company v2 + Fundamental PM Research Radar
                    -> M5: general industry-chain/exposure product
                        -> M6: filing, catalyst, risk and concentration evidence
                            -> M7: versioned deterministic reports
                                -> M8: optional narrative and claim audit
                                    -> M9: bounded agent harness

Optional procurement/long-horizon validation can run alongside the build,
but only its own passed gates unlock stronger claims.
```

## 14. Design acceptance gates

| Gate | Proof required | Unlocks |
|---|---|---|
| P0 | restatements select correctly by version availability; unknowns fail closed | any corrected historical replay |
| G1 | canonical facts replay, violations affect inputs, provenance is enforceable | engine v2 |
| G2 | worked examples, hash identity, company-type coverage/refusal | product outputs |
| G3 | corrected persisted research trace and explicit authority decision | Radar ordering modes |
| G4 | current/stale/partial/error/provenance surfaces pass real data smoke | company/Radar release |
| G5 | exposure evidence and compatible rollups add information beyond membership | chain release |
| G6 | event/concentration extraction passes yield and false-positive gate | catalyst/risk blocks |
| G7 | old report replay and report delta pass | narrative/harness consumers |
| G8 | claim audits and provider-down degradation pass | optional narrative publication |
| G9 | permissions, budgets, dedupe, termination and soak pass | scheduled drafts |
| GX | active-plus-delisted PIT/OOS/regime/cost evidence passes | any investment-ranking proposal |

No gate is satisfied by UI screenshots, unit tests alone when durable state is required, or model
agreement with the intended conclusion.

## 15. Completion definition

The descriptive-research program is complete when the optical-communication north-star request can
be run end to end with frozen scope/as-of/version/budget, deterministic calculations, evidence-backed
chain exposures, a reproducible report, explicit disagreements and unknowns, prior-version delta,
and bounded refresh/draft behavior—while remaining fully usable without a model provider.

Completion does not imply alpha, recommendation, portfolio construction, order staging, or trading
authority. Those require a new decision after the stronger empirical gate, not a silent extension of
this project.
