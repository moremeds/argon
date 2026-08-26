# Top-Down Macro Context — Program Plan

> **Status:** **PHASE 1 CLOSED 2026-08-26.** MC0–MC4 shipped (v0.12.17), F2 additive evidence
> invalidation shipped (migration `131`, PR #391), MC5 and MC6 closed by the operator. Nothing in this
> program is open. The descriptive chain is complete and the program carries **no** score, ranking,
> sizing or PM-integration authority — that boundary is a measured finding, not a pending decision.
> The only path that could reopen MC5/MC6 is a release-**event** preflight, which is unauthorized and
> unstarted. Repository and PR history are authoritative for merge status. This is the macro program
> source of truth and child-plan registry; the closure verdict against this plan's own completion
> criteria is §10.

**Goal:** replace four disconnected dashboards with a reproducible top-down research system that
explains inflation → policy/rates → USD transmission → gold, preserves every source and vintage,
and publishes a stable context snapshot that the Fundamental PM Agent can consume without changing
fundamental facts or scores.

**Architecture:** official/free evidence lands in one immutable macro evidence store. Four typed
domain engines derive state, direction, velocity, confidence, and contradictions in causal order;
they do not collapse into one unexplained score. A versioned `MacroContextSnapshot` references exact
observations and is joined to companies/chains through separately versioned exposure mappings.

**Tech stack:** Python 3.13 via `uv`, psycopg/Postgres, FastAPI/Pydantic v2, APScheduler workers,
Next.js/React/TypeScript, existing rates/Gold Compass modules, and the shared walk-forward harness.

---

## 1. Product boundary

The system has six successive products:

1. immutable macro source artifacts and observations;
2. official FOMC/statement/SEP evidence plus independently typed policy paths;
3. inflation and rates state engines;
4. USD-transmission and gold state engines;
5. a versioned top-down context snapshot and decision surface;
6. a context-only Fundamental PM overlay, followed by a separate empirical promotion gate.

Explicit non-goals for MC0–MC5:

- one master macro score;
- automatic asset allocation, duration sizing, gold sizing, or trade proposals;
- treating static/demo/mock values as observed facts;
- inferring which anonymous SEP dot belongs to the Fed Chair;
- treating a third-party FedWatch page as official Federal Reserve guidance;
- using yield-curve slope as a term-premium substitute;
- putting macro observations in `fundamental_statement_obs`;
- allowing macro state to move fundamental valuation anchors or dimensions;
- claiming forecast or ranking value before MC6.

## 2. Why the existing framework cannot be promoted as-is

The original public framework is a useful hypothesis map, not evidence. Its author later identified
short samples, IC decay, target leakage, nonlinear fragility, and regime instability. The live pages
also mix real observations with mock/static/demo inputs while emitting exact probabilities, stance,
and allocation-like outputs. That makes the current UI more confident than its evidence.

Repository evidence confirms structural problems beneath the presentation:

| Finding | Repository evidence | Required response |
|---|---|---|
| rates vintages overwrite | `052_rates_tables.sql` keys `(series_id, obs_date, source)`; `rates_repository.py` updates value and realtime fields on conflict | append-only macro observation identity |
| policy payloads are mutable | `053_rates_policy_sources.sql` upserts by date/source without content identity | immutable artifact/path releases |
| rates stance uses hard thresholds | `rates/scorecard.py` turns a partially populated scorecard into BUY/SELL/NEUTRAL | state/confidence first; no promoted stance until validated |
| Gold provenance is incomplete | `gold_posture.py` consumes flows, COT, CB, inventory, DXY, GPR, LBMA and UW, but `inputs_used` pins only four macro series | typed snapshot-to-observation evidence |
| shared inputs can be counted twice | inflation expectations, real yields and USD appear in multiple dashboards/lenses | one shared observation, explicit causal role per domain |
| third-party path has weaker authority | `fed_funds_futures_path.py` uses Frenzy Capital SSR as free/delayed futures-derived data | keep as shadow market path, never official truth |

No existing history is deleted during migration. Legacy rates/gold tables remain readable until
dual-read parity is proven.

## 3. Core contracts

### 3.1 Evidence reference

Every consumed datum resolves to:

```text
domain
source
source_url
source_record_id
period_end / obs_date
published_at
available_at
first_observed_at
content_hash
parser_version
quality_status
cost_class
```

`available_at <= as_of` is the universal PIT predicate. `published_at` describes the publisher's
release time; `first_observed_at` describes Argon's first sighting. A correction or changed payload
creates a new observation with a new content hash. It never mutates the row used by an older
snapshot.

### 3.2 Domain state

Each domain publishes, independently:

```text
state                 descriptive regime label
direction             rising / falling / mixed / unknown
velocity              typed change over a stated horizon
confidence             mechanical completeness/quality score plus reasons
contradictions         list of evidence conflicts
evidence_refs          exact observation IDs grouped by causal role
engine_version
inputs_hash
as_of
computed_at
```

Confidence is not model certainty. Missing load-bearing inputs produce `unknown` or `partial`; they
do not trigger neutral-by-default arithmetic.

### 3.3 Four policy paths

Rates must keep these separate:

| Path | Meaning | Preferred free source |
|---|---|---|
| `policy_actual` | decisions, target range, votes, statements | Federal Reserve FOMC releases |
| `committee_projection` | anonymous participant distributions/medians | Federal Reserve SEP tables |
| `dealer_expectations` | primary-dealer/market participant distributions | New York Fed Survey of Market Expectations |
| `market_implied` | futures/OIS pricing | exchange/OIS derivation; Frenzy only as labeled delayed shadow |

Differences between paths are a first-class output. No weighted merge produces a fictional “Fed
path.” A Chair's public communication is narrative evidence and cannot be assigned to an anonymous
dot.

### 3.4 Snapshot and PM boundary

`MacroContextSnapshot` contains the four domain-state IDs, shared contradictions, cross-domain
transmission statements, freshness/coverage, `engine_version`, `inputs_hash`, and exact evidence
associations. The PM report/card stores or references:

```text
macro_context_snapshot_id
macro_exposure_version
```

Those identifiers enter the report/card `inputs_hash` for the macro block only. A missing snapshot
or exposure mapping yields an explicit omitted block. Fundamental statements, derivations, anchors,
and scores remain byte-for-byte identical.

## 4. Free-first source policy

Runtime resolution order:

1. already persisted compatible PIT result;
2. already persisted official observation;
3. free authoritative publisher;
4. already-entitled provider under its budget;
5. free third-party derived source as a labeled shadow/cross-check;
6. authorized paid capability;
7. explicit unsupported/omitted.

| Domain | Preferred free/official sources | Secondary/cross-check |
|---|---|---|
| Inflation | BLS, BEA, FRED/ALFRED, Cleveland Fed, NY Fed SCE, Philadelphia Fed SPF, Atlanta Fed | already-entitled structured feeds |
| Policy/rates | Federal Reserve, NY Fed, Treasury/FiscalData, Cleveland Fed, CFTC, TIC | Frenzy delayed futures path; authorized exchange/OIS source |
| USD | Federal Reserve broad-dollar/H.10, BIS effective exchange rates, official central-bank policy rates, CFTC | already-entitled market data |
| Gold | FRED, CFTC, SPDR issuer archive, LBMA, IMF IFS, GPR publisher | authenticated WGC; already-entitled UW options |

Yahoo/yfinance remains prohibited. HTML or workbook endpoints are accepted only with artifact hash,
parser version, schema-drift tests, and an official fallback or explicit degraded state.

## 5. Target architecture

```text
OFFICIAL / FREE PUBLISHERS
  └── raw artifact + request audit
       └── immutable macro observation + quality verdict
            ├── InflationState
            ├── PolicyRatesState
            ├── USDTransmissionState
            └── GoldState
                 └── MacroContextSnapshot
                      ├── top-down macro UI/replay
                      └── company/chain exposure overlay
                           └── Fundamental PM report context
```

Storage boundaries:

- `macro_source_artifacts` preserves publisher payload identity and retrieval audit;
- `macro_observations` preserves releases/revisions and time semantics;
- typed domain-state tables preserve deterministic outputs;
- `macro_context_snapshots` and `macro_context_evidence` preserve assembly and provenance;
- `company_macro_exposures` preserves effective-dated sensitivity mappings;
- existing rates/gold tables remain legacy read models until parity and cutover.

## 6. Milestones and child plans

| ID | Status | Child plan | Exit gate |
|---|---|---|---|
| MC0 | implementation verified | `2026-08-12-macro-mc0-evidence-contract.md` | two migration replays; immutable hash/time/quality/SQL guards; 19-relation read-only inventory self-check; lint/format/diff gates |
| MC1 | merged | `2026-08-12-macro-mc1-fomc-sep-policy-paths.md` | official FOMC/SEP evidence and four independent policy paths replay PIT — PR #348. Verdict PASS with residuals: two statements publish a tally without a roster, and the 2025-07-30 `Absent and not voting` form is uncaptured |
| MC2 | merged | `2026-08-12-macro-mc2-inflation-rates-state.md` | inflation/rates states abstain honestly and reproduce from exact observations — PR #359, v0.12.10 |
| MC3 | merged | `2026-08-12-macro-mc3-usd-gold-state.md` | rates market layer resolves to real evidence; USD/Gold states reuse shared inputs — PRs #363/#369/#372/#377. **Semantically bounded:** USD observes only the US policy leg (no foreign differential), and Gold's state owns two citable inputs and borrows the rest. Gold provenance is NOT complete; the wider Compass path stays separate |
| MC3.5 | merged | — | `/macro` renders the four domain states in causal order — PR #378, v0.12.16. Descriptive chain viewer only: it composes four independent latest responses and is **not** MC4's atomic snapshot |
| MC4 | merged | `2026-08-24-macro-mc4-mc6-sequenced.md` | one persisted snapshot owns the four-domain composition and renders its refusal — PRs #384/#386/#387, v0.12.17. Status comes from dependency-edge identity, never timestamp proximity, and a snapshot may never repair an incompatible chain by substituting a fresher upstream. First production snapshot: id 1, `as_of` 2026-08-25 19:40 ET, `complete`, four domains present |
| MC5 | killed | `2026-08-12-macro-mc4-mc6-context-pm-validation.md` | **Closed by the operator 2026-08-26**, never started. It required the MC6 preflight to return something other than `descriptive_only`; it did not, so nothing measured justifies putting macro into the Fundamental PM surface. The hold stopped being procedural and became the finding. Reopening requires the release-event preflight below to produce a testable object AND a fresh authority decision |
| MC6 | killed | `2026-08-12-macro-mc4-mc6-context-pm-validation.md` | **Closed by the operator 2026-08-26.** The preflight (`docs/research/2026-08-24-macro-continuous-feature-preflight/`) produced `descriptive_only`, which is one of MC6's own three designated verdicts — so MC6 reached its exit without building the walk-forward harness, and the harness must not be built for this panel. Every economically meaningful feature lands at `eff_n` 0.9–27 over 5.6 years; `usd change.DTWEXBGS`, which the whole USD engine rests on, is 12.8 and would need 42 years to reach 100. Neither longer history nor faster sampling rescues it — faster sampling is what the AR(1) correction measures |
| F2 | shipped | `2026-08-24-macro-mc4-mc6-sequenced.md` §P0-b | additive, point-in-time evidence invalidation — migration `131`, PR #391. Not an MC: a foundation repair found while sequencing MC4. The overlay carries its OWN clock (`invalidated_at <= as_of`, the same shape as `available_at <= as_of`), so a replay of an instant before the discovery still returns the row Argon believed then, and a current read excludes it. It never rewrites a value and the audit view never filters itself. Zero production instances — verified against a frozen FRED rebasing fixture, because there is nothing in the store to exclude |

Every child is implemented through its own branch/PR sequence. Status changes only after its stated
verification evidence exists. Child plans are implementation-ready but do not imply authorization to
commit or publish.

> **Migration numbers.** This plan's child reserved `117_macro_context_snapshots.sql` for MC4 and
> `118_company_macro_exposures.sql` for MC5. Both numbers were taken by the Fundamental lane
> (`117_fundamental_scores.sql`, `118_valuation_anchors.sql`). The tail is `129` as of 2026-08-24, so
> MC4 starts at `130`. Re-check the tail before writing a migration; do not read a reserved number
> from either plan.

> **MC6 sequencing changed, then MC6 ended.** `docs/research/2026-08-23-macro-state-replay-flip-census.md`
> replayed 68 monthly instants (2021-01..2026-08) and found the categorical state label is not a viable
> validation unit: inflation flips 4 times, rates 8, `usd/2` 13 after the boundary move, and gold cannot
> replay at all before its retrieval-clock evidence began. That forced a continuous-feature availability
> and target preflight BEFORE MC5 or the MC6 harness — a step the original child plan did not contain.
> The preflight ran 2026-08-24 (`docs/research/2026-08-24-macro-continuous-feature-preflight/`) and
> returned `descriptive_only`, closing both. Do not backfill replayed states to manufacture sample size —
> those rows are immutable, would bake in today's engine version, and the preflight showed sample size
> is not the binding constraint anyway: **the features with the largest effective sample are the ones
> carrying no economic content**, because a high `eff_n` comes from being noisy rather than informative.

## 7. Dependency and release sequence

```text
MC0 evidence contract
  └── MC1 official policy evidence
       └── MC2 inflation + rates
            └── MC3 rates market layer → USD + gold
                 └── MC4 context snapshot
                      ├── MC5 PM context-only integration
                      └── MC6 empirical promotion research
```

MC2 may start its pure domain calculations while MC1 source fixtures are reviewed, but its release
waits for MC1. MC3 waits for shared-input ownership from MC2. MC5 waits for a verified MC4 snapshot
and the PM surface/report contract; it never waits for MC6. MC6 gates only numeric score/ranking or
sizing influence.

## 8. Validation and promotion gates

| Gate | Required evidence | Unlocks |
|---|---|---|
| GM0 | immutable revision fixtures, `available_at` PIT query, source/cost registry, mock rejection | production source adapters |
| GM1 | official statement/SEP fixtures, table-total checks, four-path type tests, replay | policy/rates state |
| GM2 | domain golden fixtures, missing/stale/contradiction tests, evidence completeness | context snapshot/UI |
| GM3 | real worker → DB → API → browser smoke, replay hash equality, PM byte-invariance test | context-only PM release |
| GM4 | preregistered PIT walk-forward, ablation, regime splits, full trace, cost assumptions | separately approved score/ranking influence |

MC6 must test the exact proposed target. A descriptive state does not become predictive because it
looks intuitive. Tests include incremental value over simple baselines, factor ablation, overlapping
horizon handling, multiple-testing control, regime stability, and source-vintage availability.

## 9. Rollout, rollback, and failure behavior

- migrations are additive and idempotent;
- new macro jobs default off until migrations and source checks pass;
- source failure writes an audit event and retains the last compatible snapshot with stale labeling;
- parsing failure never converts to zero, neutral, or unchanged;
- legacy rates/gold readers remain behind a dual-read flag until row/value/provenance parity is
  measured;
- rollback selects the prior engine version/read path; it never deletes observations;
- a partial domain may publish only when load-bearing omissions and confidence reasons are explicit;
- a PM macro block can be disabled independently without changing fundamental outputs;
- provider calls, freshness, coverage, parser failures, revision counts, snapshot lag, and PM
  omission rate are observable.

## 10. Completion criteria

At the descriptive scope, a user can ask:

> What changed from inflation through policy/rates and the dollar into gold, what evidence supports
> each link, where do official projections, dealers, and markets disagree, and which portfolio
> companies are exposed?

Argon can then:

1. freeze `as_of`, source vintages, engine versions, and budget;
2. show realized inflation, expectations, policy/rates, USD transmission, and gold state separately;
3. distinguish policy actuals, SEP, dealer expectations, and market-implied pricing;
4. show direction, velocity, confidence, contradictions, freshness, and explicit unknowns;
5. replay every output from exact evidence without later revisions leaking backward;
6. attach a versioned company/chain exposure overlay to a Fundamental PM report;
7. remove that overlay without changing any fundamental number;
8. decline score/ranking/sizing claims until MC6 and operator approval pass.

### Phase-1 closure verdict (2026-08-26)

Scored against the eight criteria above, as they were written on 2026-08-12:

| # | Criterion | Outcome |
|---|---|---|
| 1 | freeze `as_of`, vintages, engine versions, budget | **met** — `macro_context_snapshots` freezes the instant, `inputs_hash` the composition, `assembler_version` the code |
| 2 | show the domains separately | **met** — `/macro` renders four domain cards in causal order and refuses as a chain, never as four fresh-looking cards |
| 3 | distinguish actuals, SEP, dealer, market-implied | **met** — MC1 types four independent policy paths and never promotes the third-party futures path to official |
| 4 | direction, velocity, confidence, contradictions, freshness, unknowns | **met** — each domain abstains rather than guessing; the snapshot's status comes from dependency-edge identity, not timestamp proximity |
| 5 | replay every output without revisions leaking backward | **met** — `available_at <= as_of` throughout, and after F2 an accepted-then-wrong artifact is excluded going forward without altering what a past replay returns |
| 6 | attach a versioned exposure overlay to a Fundamental PM report | **not delivered — killed** |
| 7 | remove that overlay without changing any fundamental number | **not delivered — moot**, nothing is attached |
| 8 | decline score/ranking/sizing claims until MC6 passes | **met, and now permanent for this panel** |

**6 and 7 were answered, not skipped.** They were gated on MC6, and MC6's preflight returned
`descriptive_only` — one of MC6's own three designated verdicts. The criterion reached its exit and
the exit said do not build the overlay. Recording them as "incomplete" would misread a measurement as
a backlog item: every economically meaningful feature in the panel lands at `eff_n` 0.9–27 over 5.6
years, and `usd change.DTWEXBGS` — the observation the whole USD engine rests on — is 12.8 and would
need 42 years to reach 100. Sample size is not the binding constraint; the features with the largest
effective sample are the ones carrying no economic content.

**What phase 1 therefore delivers is narrower than the 2026-08-12 goal and honest about it:** a
replayable, evidence-cited, refusal-capable description of inflation → policy/rates → USD → gold,
with no consumer downstream of it. The Fundamental PM surface is byte-identical to what it was before
this program started, by construction rather than by flag.

**Carried forward, unstarted and unauthorized:** the release-**event** preflight is the only named
path that could reopen MC5/MC6. It is a different unit of analysis (a discrete surprise at a known
timestamp) from the monthly state label the flip census and the preflight both rejected. Nothing in
this program authorizes starting it.

## 11. Plan maintenance protocol

This document owns macro scope, milestone status, dependency, and authority. Child plans own exact
files, tests, commands, and PR boundaries. After each implementation PR:

1. link the PR and exact verification evidence in the milestone row;
2. update source status and any endpoint/schema drift;
3. record killed sources or factors rather than leaving permanent mock fields;
4. update the Fundamental PM program only if the integration boundary or dependency changed;
5. archive a child plan only after its exit gate passes;
6. never mark `verified` from unit tests when a real source, database, worker, or browser gate is
   required.

Status vocabulary:

```text
proposed → researched → specified → planned → in_progress → verified → merged
                                      └────────→ killed
```
