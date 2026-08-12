# Top-Down Macro Context — Program Plan

> **Status:** in progress. MC0 implementation is verified on branch
> `feat/macro-evidence-contract`; repository and PR history are authoritative for merge status. This
> is the macro program source of truth and child-plan registry. It does not authorize implementation
> on the active Fundamental PM ingest branch.

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
| MC1 | planned | `2026-08-12-macro-mc1-fomc-sep-policy-paths.md` | official FOMC/SEP evidence and four independent policy paths replay PIT |
| MC2 | planned | `2026-08-12-macro-mc2-inflation-rates-state.md` | inflation/rates states abstain honestly and reproduce from exact observations |
| MC3 | planned | `2026-08-12-macro-mc3-usd-gold-state.md` | USD/Gold states reuse shared inputs and Gold provenance is complete |
| MC4–MC6 | planned | `2026-08-12-macro-mc4-mc6-context-pm-validation.md` | snapshot, context-only PM integration, then separate PIT/OOS promotion verdict |

Every child is implemented through its own branch/PR sequence. Status changes only after its stated
verification evidence exists. Child plans are implementation-ready but do not imply authorization to
commit or publish.

## 7. Dependency and release sequence

```text
MC0 evidence contract
  └── MC1 official policy evidence
       └── MC2 inflation + rates
            └── MC3 USD + gold
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
