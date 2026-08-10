# Fundamental analysis method — design

*Status: ACCEPTED, awaiting implementation plan · 2026-08-10 · branch `feat/fundamental-pm-agent`*

## 1. Goal

**A fixated, extensible fundamental-analysis method — plus the two surfaces that render it.**
The method (§5) is the deliverable. The surfaces are how it is read.

| | Shipment | Surface | Question it answers |
|---|---|---|---|
| **S1** | Fundamental card | new tab on `/stock/{ticker}` | *Is this one name attractive, and what would prove me wrong?* |
| **S2** | Chain heatmap | new screen `/industry_graph` | *Where in the AI stack is the value, and where is risk piled up?* |

**Python computes every number. DeepSeek writes prose over those numbers and nothing else.** The
narrative stage is in v1 (§5.1 stage 5) — it is a provider call inside a deterministic job, not an
agent. It cannot move a single value produced by stages 3–4 (invariant I1), and a numeric auditor
diffs its prose against the backing rows before the card renders.

**What is deferred is the loop harness, not the model call** (§10). Nothing in argon decides on its
own when to recompute, re-analyse or re-plot; every stage stays cron- or request-triggered. The
autonomous layer arrives later as an external **pi agent** harness driving these jobs, which is
argon goal-ladder Stage 2 (self-tending desk) and out of scope here. User ruling, 2026-08-10.

S1 → S2 is a real dependency, not a preference: argon already ships a layer-rail chain filter on the
watchlist (v0.11.4), so a surface that only redraws membership duplicates existing capability. What
makes `/industry_graph` new is that every cell carries a *computed fundamental attribute*. S2 without
S1's engines is a colouring book with no colours.

Explicitly **not** in scope: a ranked long/short book — it needs both surfaces as inputs.

Fits argon's Stage-1 lane ("trustworthy foundation"): the deliverable is honest fundamental
data with per-fact provenance, not more surface area. Keeping the model out of the numbers is what
makes that true —
every number on both surfaces is reproducible from an `inputs_hash`.

## 2. Blueprint and what we take from it

Modeled on @sunlc_crypto's "BewinQuant Terminal" AI investment radar (5-part X series,
part 5 = 2086014788187164904). His taxonomy is 黄仁勋's AI 五层蛋糕理论 — 5 layers × ~20 chains
over a 188-name universe. argon's `watchlist_taxonomy.py` is already the same shape
(9 layers, 38 chains, 235 memberships), so the taxonomy is not new work.

**The load-bearing idea is the constraint on the AI, not the AI.** His stated rule:
*"AI 只能使用系统提供的证据，不能修改系统算出的价格区间，也不能编造新闻或财务数字"* and
*"产业链结果主要由固定规则计算，不是 AI 自由判断"*.

| Take | Why |
|---|---|
| Deterministic fixed score, LLM cannot move it | The whole point. Score = **research priority**, never a return forecast |
| Multi-anchor valuation (`buy_below / observe_low / observe_mid / observe_high / risk_above`) | Company-type-routed; a defensible price *range*, not a prediction |
| Evidence ledger — `source · quality · timestamp` per fact | argon already persists prompt/schema/model/hash; this extends it to per-fact |
| Numeric 失效条件 (invalidation conditions) | The single most useful output field; forces falsifiability |
| 数字审计 — audit prose against backing data | The only mechanism that makes the arrangement falsifiable |

| Reject | Why |
|---|---|
| 增长假设 H0–H5, 买方研究备忘录 | Render **empty** in his own screenshots — claimed, not demonstrated |
| "Warren Composite" as headline | argon's theta-harvester lesson: a score that *orders* (IC +0.075) can still select a losing set |
| Technical score inside the fundamental composite | Violates his own display-only principle; argon's technicals are deeper |
| 4-tier universe, PDF reports, Social Monitor, ClickHouse, FMP subscription | argon has equivalents or better; Postgres is law here |
| His options module | argon's is materially better |
| 预期差 as *estimate* gap | Forward estimates are Advanced+-gated. Ship the **price-target** gap (`uw_positioning.target_avg` vs anchors); never fake the estimate gap |
| 供应链瓶颈分 as a hand-assigned score | Replaced by the **measured** ASC 280 concentration metric — same shape, real provenance |

He has **no backtest, no hit-rate, no P&L**, and says so. This is a research organizer, not
validated alpha. We inherit that limitation and must not oversell it.

## 3. Feasibility verdict

Buildable, mostly from parts argon already owns. Two findings gate it.

### 3.1 BLOCKER — `fundamentals_refresh` has never persisted a row (verified)

- `_repo()` (`worker/scheduler.py:498`) does `psycopg.connect(...)` with **no `autocommit=True`**,
  yields a `Repository`, and `finally: conn.close()`.
- `worker/jobs/fundamentals_jobs.py` and `storage/fundamentals.py` contain **zero `.commit()`**.
- psycopg 3.3.4 defaults `autocommit=False`; `close()` without commit discards the transaction.
- The sibling `positioning_refresh_once` survives only because `insert_scan_run` /
  `finish_scan_run` commit internally on the same connection. Fundamentals has no such rescue.
- `tests/integration/worker/test_fundamentals_job.py` passes because it asserts on the **same
  open connection**. The test is the second bug.

Nightly since migration 066, logging `"fundamentals_refresh refreshed %d tickers"` while rolling
everything back. **`massive_fundamentals` is empty or stale in production.**

Blast radius is narrow: `ohlc_pull` writes through `market_data.py` (4 commits, safe).
`fundamentals_jobs` is the confirmed case. Other `_repo()` consumers were not individually
traced — worth a follow-up audit, out of scope here.

### 3.2 Data inventory

**Available and unused (currently costs zero UW calls/day):**

| Source | Content | Integrated? |
|---|---|---|
| massive `/v2/reference/financials` | **103 fields, quarters back to 1997** | No — argon uses `/vX` (55 fields), persists ~13, `limit=8` |
| UW `/stock/{t}/income-statements`, `/balance-sheets`, `/cash-flows` | 94 quarters each | No |
| UW `/stock/{t}/fundamental-breakdown` → `rev_breakdown` | **revenue by product AND geography** | No |
| UW `/stock/{t}/info` | sector, marketcap, beta, issue_type | No |
| SEC EDGAR `data.sec.gov` + `efts.sec.gov` FTS | filings, XBRL, concentration language | No |

**Already shipped and reusable:** `uw_positioning` (analyst targets/ratings, insider net flow,
13F aggregates, short interest, earnings reactions) — daily, correctly committed, live on the
stock page.

**Gated (Advanced+/Premium, unavailable):** forward analyst estimates, earnings-call transcripts,
company profile, IPO calendar, UW dividends/splits, macro series.

**Absent at any tier from every provider:** supply-chain relationship graph, forward guidance,
backlog/bookings, KPI disclosures, unit economics. Every stage **must be able to emit `na`** for
these, and both surfaces must render the absence (§5 I4, §7 coverage block). This is a hard ceiling,
not a backlog item.

**Budget:** live ceiling 80k, research 30k, account guard 105k. Current burn ≈45.5k/day
(173 × ~263). ≈60k/day headroom; segment pulls for a 25-name core are noise against it.

### 3.3 The edge-graph reality (measured, 2026-08-10)

Live EDGAR full-text probes. Controls pass (`"CoWoS"` → 10 hits, all NVDA 10-Ks).

| Query | Hits | Note |
|---|---:|---|
| `"one customer accounted for"` (10-K) | **9,261** | unnamed |
| `"no customer accounted for more than 10%"` (10-K) | **3,281** | unnamed |
| `"customer accounted for"` (**20-F**) | **459** | unnamed; reaches TSM/ASML/STM |
| `"NVIDIA accounted for"` | **0** | |
| `"Taiwan Semiconductor accounted for"` | **0** | |
| `"Broadcom accounted for"` / `"Tesla accounted for"` | **0** | |
| `"Meta Platforms accounted for"` | **1** | Arista Networks 2023 |
| `"revenue from NVIDIA"` | 2 | Rambus 2018/2019 |
| `"Amazon accounted for"` | 115 | Emerson Radio etc. — *marketplace sellers*, not AWS |

Two structural causes:

1. **ASC 280-10-50-42 requires the amount, not the identity.** Modern mega-caps uniformly do
   not name. Boilerplate outnumbers named disclosures ~200:1.
2. **The upstream tier files 20-F/6-K, not 10-K.** TSM's SEC mix: 6-K ×741, 20-F ×15,
   **zero 10-Ks** (verified via `data.sec.gov/submissions/CIK0001046179.json`). 20-Fs *are* in
   the FTS corpus, so this is a corpus-selection fix. Korea (Samsung, SK Hynix) files nothing
   with the SEC and is **permanently unreachable**.

**Consequence, stated plainly:** a dense EDGAR-anchored *named* edge graph for the AI chain does
not exist. The filing-citation discipline stays mechanically enforced; only the density
expectation is revised. The primary artifact becomes a **per-company customer-concentration
ledger** (dense, citable, trend-bearing), with a **sparse named-edge overlay** where small/mid-cap
suppliers name their mega-cap customers.

Note the convergence: the blueprint author independently landed on a per-company
供应链瓶颈分 rather than a graph. Two builders hitting the same wall is evidence about the data.

## 4. Architecture

### 4.1 Decisions

| # | Decision | Rationale |
|---|---|---|
| A1 | **Third lane** `analysis_kind='fundamental'` on the existing `trade_insights_ai` queue — stage 5, phase P5 | Verified live: migration `067`, per-row dispatch at `trade_insights_ai.py:142`. A separate queue would duplicate SKIP-LOCKED claim logic, heartbeats, per-provider workers and the UI polling hook for no gain |
| A2 | New pure-compute package **`src/uw_scan/fundamentals/`** | Follows `theta_harvester/` / `chanlun/` precedent. Not `reports/` — those are read-time reshapes; these are nightly persisted computations |
| A3 | New API router **`api/routers/fundamental.py`** | `routers/trade_insights.py` is already ~600 lines; module-size budget |
| A4 | **massive `/v2`** for the statements backbone, **UW `fundamental-breakdown`** for segments | The IB→UW→FMP→massive rule is scoped to *live quotes/greeks*; massive is already the fundamentals source. Preserves UW headroom. UW 94q statements become the cross-check |
| A5 | **`fundamental_company_type`** persisted separately, seeded from sector+chain, hand-overridable | `watchlist_chain` is many-to-many — a ticker in 3 chains has no unique layer. Valuation methods must not silently flip when taxonomy is edited |
| A6 | **DeepSeek only** for stage 5 | `docker-compose.yml:10` — "AI Codex/Claude are OFF"; only `worker-ai-deepseek-0/1` are deployed. Codex/Claude runners are subprocess CLIs reading macOS keychain OAuth; there is no keychain in a container. DeepSeek is in-process `httpx` + bearer token |
| A7 | **Core 25** universe in v1 (§4.3) | Every valuation anchor stays hand-verifiable while the method is still being fixated |
| A8 | **Staged numeric audit** — deterministic always, model auditor conditional | Two things get audited, and they arrive at different times. Stages 1–4 are validated from P2 (anchors ordered, percentages in range, `inputs_hash` reproducible). Prose auditing starts at P5; clean narratives cost nothing extra, suspicious ones get the deep check |
| A9 | `asc280_inferred` identities are **stored and rendered flagged as inference** | The "NVDA's top customer is probably a hyperscaler" fact is the most important fundamental fact about NVDA. In v1 the flag is a UI label; when the agent lands (§10) it also becomes an audit rule that FAILS prose stating an inferred identity as fact |

### 4.2 Module split (`src/uw_scan/fundamentals/`)

| Module | Responsibility | ~lines |
|---|---|---|
| `statements.py` | normalize massive/UW rows, derive TTM / growth / margins | 300 |
| `company_type.py` | routing classification (chips / software / power / high-risk-growth) | 100 |
| `scoring.py` | subscores + composite | 250 |
| `valuation.py` | anchor blending, confidence downgrades | 300 |
| `valuation_methods.py` | per-company-type method implementations | 350 |
| `concentration.py` | ASC 280 extraction + edge overlay (Phase 4) | 400 |

S2's chain/layer rollups are a **read-time reshape of S1 rows**, so by A2's own seam they live in
`reports/industry_graph.py` (~150 lines), not in this package. No second scoring path exists.

### 4.3 Core 25 universe (v1)

Spans every taxonomy layer L1–L5 so chain context is meaningful from day one. Stored as a
`fundamental_universe` flag rather than a new tier scheme — argon already has watchlist + `hot`
+ research cohorts, and a fourth tiering scheme would be pure admin.

| Layer | Tickers |
|---|---|
| L1 Chip & System | NVDA AMD AVGO MRVL TSM ASML AMAT MU |
| L2 Cloud & Data | MSFT GOOGL AMZN META ORCL |
| L3 Datacenter Infra | ANET VRT ETN GEV CEG VST |
| L4/L5 App & Model | DELL SMCI PLTR CRWD NOW APP |

**Membership must intersect the active watchlist** (`removed_at IS NULL`) — the SPX precedent
shows captures silently skip anything off the active list. Any name here that is not on the
watchlist either gets added or is dropped from the core before P1. Verify at build time; do not
assume.

### 4.4 Storage

Each in its own `storage/<domain>.py`. Never extend `repository.py`.

| Table | Key columns | Registry |
|---|---|---|
| `fundamental_statements` | PK `(ticker, period_end, period_type)`; ~40 wide columns + `raw_jsonb` (full 103-field payload), `source` | temporal → **DatasetRegistryEntry** |
| `fundamental_segments` | PK `(ticker, period_end, dimension, segment_name)`; `dimension ∈ {product, geography}`, revenue, `source` | temporal → **DatasetRegistryEntry** |
| `fundamental_score_daily` | PK `(ticker, as_of)`; one column per subscore, composite, `engine_version`, `inputs_hash` | temporal → **DatasetRegistryEntry** |
| `valuation_anchors_daily` | PK `(ticker, as_of)`; `company_type`, `method`, the 5 anchors, base/bear/bull × 1y/3y, `confidence`, `confidence_reasons_jsonb`, `inputs_jsonb`, `engine_version` | temporal → **DatasetRegistryEntry** |
| `customer_concentration` | PK `(ticker, fiscal_period, filing_form)`; `top_customer_pct`, `customers_over_10pct`, `none_over_10pct`, `magnitude_basis`, `filing_accession`, `filing_date`, `excerpt` | event-temporal → **DatasetRegistryEntry** |
| `fundamental_edges` | see §6 | event-temporal → **DatasetRegistryEntry** |
| `fundamental_audit_results` | PK `(analysis_id, claim_seq)`; `claim_text`, `extracted_value`, `backing_source`, `backing_value`, `verdict ∈ {pass,warn,fail,unverifiable}`, `stage ∈ {deterministic,model}` | keyed by analysis — dimension, exempt |
| `fundamental_company_type` | PK `(ticker)`; `company_type`, `source ∈ {rule,manual}`, `set_at` | dimension, exempt |
| `fundamental_method_params` | PK `(param_set, param_key)`; `param_value NUMERIC`, `active BOOLEAN`, `note`, `updated_at`. Holds §5.2 weights + §5.4 thresholds. Seeded `param_set='v1_prior'` | dimension, exempt |

Exactly one `param_set` carries `active=true` — enforced by a partial unique index, not by
convention. Two active sets would make `engine_version` ambiguous and every downstream row
unattributable.

Registry entries and the regenerated data-gap policy doc ride the **same PR** as each table.

## 5. The method (fixated)

What is being shipped is a **method**. The two screens are how it is viewed; the method is what has
to survive the universe going 25 → 220 names, 4 → N company types, and 7 → more subscores without
a rewrite.

**The rule that makes it extensible: everything that varies by ticker is DATA, not control flow.**
A new company type is a registry row plus one function. A new subscore is a registry row plus one
function. Neither edits the pipeline. If adding a name requires an `if ticker ==` anywhere, the
method has been broken.

### 5.1 Pipeline contract

Five stages. Every ticker, every run, no exceptions:

```
1 INGEST   raw statements + segments        → fundamental_statements, fundamental_segments
2 DERIVE   TTM, growth, margins, ratios     → pure functions, no I/O
3 SCORE    subscores → composite            → fundamental_score_daily
4 ANCHOR   company-type-routed valuation    → valuation_anchors_daily
5 NARRATE  DeepSeek prose over 3+4, audited → trade_insight_ai_analyses + fundamental_audit_results
```

Stages 1–4 are deterministic and reproducible from `inputs_hash`. Stage 5 is a **provider call
inside a job**, not an agent: it is triggered by cron or by request, never by its own judgement, and
it consumes 3+4 as read-only inputs. Nothing in the pipeline decides when to run itself — that is
the loop harness, deferred to §10.

Stage 5 degrades cleanly. If DeepSeek is unavailable, disabled, or its output fails the audit, the
card renders stages 1–4 with the narrative block marked absent. **The deterministic surfaces never
depend on the model.**

**Trigger: ad-hoc first, cron later** (user ruling, 2026-08-10). v1 runs the whole pipeline
on-demand per ticker from a button on the card, following the shipped
`POST /stock/{ticker}/technicals/refresh` "Compute now" precedent — an explicit, deliberate write on
an otherwise read-only router. A nightly job over the whole universe is added only once the method
has stopped moving; scheduling an unstable method just fills tables with rows carrying dead
`engine_version`s. The job function takes a `ticker_filter` from day one so the cron, when it comes,
is a scheduler entry and not a rewrite.

Invariants, in force at every stage:

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Stage 5 may not alter any output of stages 3–4 | the audit stage — mechanism, not trust |
| I2 | Stages 2–4 are pure: same inputs → same outputs | `inputs_hash` equality on re-run. **`inputs_hash` covers `company_type` and the active parameter set**, not only the financial inputs — see §5.3 |
| I3 | Every stage persists before returning | argon standing rule; CI-visible via row counts |
| I4 | Any stage may emit `na`; a missing input never becomes a fabricated one | absence propagates to `unknowns` + downgrades `confidence` |
| I5 | The composite is a **sort key**, never a return forecast | labelled "research priority" on every surface |

I5 is not cosmetic. argon's theta-harvester ordered correctly (IC +0.075) and still selected a
losing set. A composite that is allowed to read as a forecast will be traded as one.

### 5.2 Subscore rubric — parameters live in Postgres

Seven subscores, each `0–100`, each computed from a named input set, each independently overridable.

**Weights are rows in `fundamental_method_params`, not constants in code** (user ruling, 2026-08-10).
Three reasons, in order of weight:

1. They are **unvalidated priors** — no backtest sits behind the seed values below, and the spec must
   not pretend otherwise. Data that is known to be provisional does not belong in a deploy artifact.
2. argon already owns a sweep harness (`backtest/` + `backtest_sweep_runs` / `_results`). Weights as
   rows means a named `param_set` is directly sweepable, with the full trace persisted, the day
   there is enough history to sweep against. Weights as constants means a code branch per trial.
3. Retuning becomes a row update, not a release.

| Subscore | Inputs (derived at stage 2) | Direction | seed weight |
|---|---|---|---:|
| `growth` | revenue TTM YoY, 2-quarter YoY acceleration | higher better | 0.20 |
| `profitability` | gross + operating margin, level and 4-quarter trend | higher better | 0.20 |
| `capital_efficiency` | FCF conversion, return on invested capital | higher better | 0.15 |
| `balance_sheet` | net debt / EBITDA, interest coverage, current ratio | lower leverage better | 0.15 |
| `valuation_position` | spot vs `observe_low..observe_high` band from stage 4 | cheaper better | 0.15 |
| `concentration_risk` | top-customer %, its multi-year trend (§6) | lower better | 0.10 |
| `expectations_gap` | our 1Y anchor vs `uw_positioning.target_avg`, insider net, short interest | wider positive gap better | 0.05 |

Seeded by migration as `param_set='v1_prior'`, `active=true`. The table also holds the §5.4
downgrade thresholds — anything a future sweep might want to move.

**Mutable parameters force `engine_version` to be derived, not hand-written.** It is
`{code_version}:{param_hash[:8]}`, where `param_hash` covers the active parameter set. A hand-bumped
version would let someone edit a weight while the version stayed put, silently destroying
comparability across `fundamental_score_daily` rows — the exact question §5.6 exists to answer.

Ordering constraint: `valuation_position` consumes stage 4, so within stage 3 it is computed
**last**, and stage 4 must never read the composite back. The dependency is one-directional or the
score becomes self-referential.

`concentration_risk` returns `na` until S2 P4 lands; `na` subscores are dropped and the remaining
weights renormalize. Renormalization, not zero-fill — a zero would read as "no concentration risk",
which is a fabricated fact.

Field-level mapping onto massive `/v2`'s 103 columns is P1's job and is deliberately not guessed
here.

### 5.3 Company-type routing — a second axis, and its invalidation cascade

`company_type` selects the valuation method. Persisted per ticker (`fundamental_company_type`,
decision A5), seeded from sector+chain, hand-overridable, **never** derived live from the
many-to-many taxonomy — a ticker in three chains has no unique layer, and valuation methods must
not silently flip when someone edits a chain.

**It is not a layer, and merging the two would be a mistake.** They are orthogonal partitions of the
same node set:

| Axis | Means | Example of divergence |
|---|---|---|
| `layer` (L1–L5) | position in the supply chain — who sells to whom | L3 holds both ANET (networking hardware) and CEG (merchant power) |
| `company_type` | which valuation math is correct | those two need entirely different methods despite sharing a layer |

Keeping them separate buys something concrete: **S2's matrix can pivot rows between the two** (§8).
Rows-by-layer answers "where in the stack is the value"; rows-by-company-type answers "which
valuation regime is stretched". Same cells, same engine, one more axis — nearly free once the matrix
exists, and impossible if the axes were merged.

**Editing either axis recalculates the graph — this is a real cascade, not a re-label.** The user's
observation of 2026-08-10, and it exposes a requirement:

```
company_type change → valuation method changes → anchors recompute
                    → valuation_position subscore → composite → S2 cell fill
```

Therefore `company_type` is an **input to stage 4 and must be inside `inputs_hash`** (I2). Without
it, changing a ticker's type produces different anchors under an identical hash — the recompute
looks like a no-op, the stale row survives, and reproducibility is silently broken. Same for the
active `param_set` (§5.2).

Invalidation rules, mechanical:

| Change | Recompute | Scope |
|---|---|---|
| a ticker's `company_type` | stages 3–4 for that ticker; S2 cells containing it | one ticker |
| add / remove a `company_type` | stages 3–4 for every ticker holding it | affected tickers |
| any active weight or threshold | stages 3–4 for **all** tickers — `engine_version` moves | whole universe |
| chain/layer membership | S2 rendering only — S1 is untouched | render |

Only the last is a pure re-render. The first three change persisted numbers, so they append new
`(ticker, as_of)` rows rather than mutating history; the old rows keep their old `engine_version`
and stay valid as history under §5.6.

| `company_type` | Method | Anchor basis |
|---|---|---|
| `chips_cyclical` | through-cycle EV/Sales with peak/trough margin normalization | cycle-normalized, not spot |
| `platform_scale` | FCF multiple + segment-weighted sum | segment revenue from UW |
| `software_growth` | EV/Sales banded by Rule-of-40 score | growth+margin composite |
| `power_infra` | EV/EBITDA + contracted-backlog floor | asset-heavy, dividend-aware |
| `high_risk_growth` | revenue multiple band, **mandatory confidence downgrade** | wide bands, stated as wide |

Every method emits the same five anchors — `buy_below / observe_low / observe_mid / observe_high /
risk_above` — plus base/bear/bull × 1y/3y. **Identical output contract across methods** is what
makes the type extensible: the card, the schema, and the map read anchors without knowing which
method produced them.

### 5.4 Confidence — downgrades are mechanical

`confidence ∈ {high, medium, low}`, starting at `high` and downgraded by rule, with every reason
recorded in `confidence_reasons_jsonb`. Never assigned by judgement.

| Trigger | Downgrade |
|---|---|
| < 8 quarters of statements | → `low` |
| latest filing older than 120 days | one step |
| `company_type = high_risk_growth` | one step, floor `medium` |
| any subscore `na` | one step per two `na`s |
| segment revenue missing | one step |

A `low`-confidence analysis still ships. It ships *labelled*. Suppressing it would hide the
coverage gap that the label exists to expose.

### 5.5 Extension points

The payoff. To add each thing, touch only the listed seam:

| To add… | Touch | Do NOT touch |
|---|---|---|
| a ticker | `fundamental_universe` flag (must intersect the active watchlist) | anything else |
| a company type | one row in the routing table + one method fn in `valuation_methods.py` | pipeline, schema, UI, prompt |
| a subscore | one row in the rubric + one pure fn in `scoring.py` | composite logic — weights renormalize |
| a data source | one fetcher + a `source` value on the row | derive/score/anchor stages |
| a chain or layer | `watchlist_taxonomy.py` + re-seed `watchlist_chain` | S1 entirely |
| a provider | a `RUNNERS` registry entry — the lane is already provider-parameterized | everything else |
| an output field | the Pydantic model + one audit rule | storage — the outcome is JSONB |

### 5.6 Versioning and comparability

`engine_version` is stamped on `fundamental_score_daily` and `valuation_anchors_daily`, and bumps
on **any** change to weights, rubric, routing, or a method. `inputs_hash` covers the derived inputs.
Together they answer the only question that matters when the method evolves: *did this score move
because the company changed, or because I changed the method?*

Cross-version comparison is invalid by default. Rows carrying different `engine_version` values may
be charted on the same axis only with the version break marked.

## 6. Concentration ledger + edge overlay

An anonymous-counterparty disclosure is a **concentration row, not an edge**. `dst_ticker` is
`NOT NULL` on edges; the `curated` tier does not exist.

```sql
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_edges (
    edge_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    src_ticker         TEXT NOT NULL,             -- the FILER making the disclosure
    dst_ticker         TEXT NOT NULL,
    edge_type          TEXT NOT NULL CHECK (edge_type IN
                         ('customer','supplier','manufacturer','licensor','distributor','other')),
    trust_tier         TEXT NOT NULL CHECK (trust_tier IN
                         ('asc280_named','asc280_inferred','filing_mention')),
    magnitude_pct      NUMERIC,
    magnitude_basis    TEXT,
    identity_inference TEXT,
    filing_form        TEXT NOT NULL,             -- '10-K' | '20-F'
    filing_accession   TEXT NOT NULL,             -- lock enforced: no accession, no row
    filing_date        DATE NOT NULL,
    fiscal_period      TEXT,
    excerpt            TEXT NOT NULL,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_confirmed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    status             TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active','stale','retired')),
    CONSTRAINT inferred_needs_basis CHECK
      (trust_tier <> 'asc280_inferred' OR identity_inference IS NOT NULL),
    UNIQUE (src_ticker, dst_ticker, edge_type)
);
```

**Pipeline** — one weekly pass, `edge_graph_refresh`:

1. Per core ticker, `edgartools` pulls the newest **10-K or 20-F** (form chosen from
   `data.sec.gov` submissions). Section-scoped scan (Item 1 / 1A / 7 + concentration-of-credit-risk
   note) for concentration language. **Every** hit writes a `customer_concentration` row —
   including `none_over_10pct` boilerplate, because absence of concentration is signal.
2. The same sentences are re-scanned for proper-noun counterparties → the rare named hit becomes
   an `asc280_named` edge. FTS co-mention search adds `filing_mention` candidates.
3. **Deterministic gate before persist**: `magnitude_pct` must literally appear in `excerpt`, and
   the accession must resolve. Extraction is regex-first. An LLM may optionally be used *offline in
   this batch job* to locate ambiguous sentences — that is not the deferred live agent of §10, and
   it never authors a row the gate did not verify. If regex recall proves adequate at P4, the LLM
   step is not built at all.
4. Refresh/expire: re-found in a newer filing → bump `last_confirmed_at`. Absent from the newest
   same-form filing → `stale`. Stale > 400 days → `retired`. **Never DELETE** — audit trail.

**Ops (runbook line):** every `sec.gov` / `efts.sec.gov` call **must bypass the local proxy** —
`httpx(trust_env=False)`. Through `127.0.0.1:7897` the TLS handshake fails outright (curl exit 35,
HTTP 000); DNS resolves fine. This mirrors the documented massive-WS `proxy=None` rule. The
SEC-required `User-Agent` header (contact email) is mandatory.

**Prompt payload block:**

```json
"supply_chain": {
  "as_of": "2026-08-10",
  "concentration": {
    "top_customer_pct": 19.0, "basis": "pct_total_revenue", "named": false,
    "filing": "10-K FY2026, acc 0001045810-26-000029, filed 2026-02-26",
    "excerpt": "one direct customer accounted for 19% of total revenue...",
    "trend": [{"period": "FY2025", "top_customer_pct": 13.0},
              {"period": "FY2026", "top_customer_pct": 19.0}]
  },
  "edges_outbound": [],
  "edges_inbound": [
    {"counterparty": "ANET", "type": "customer_of_dst_disclosed_by_src",
     "trust": "asc280_named", "filing": "10-K 2023, acc ...", "excerpt": "..."}
  ],
  "coverage_note": "Edges are sparse by construction: US GAAP does not require naming customers. Absence of an edge is NOT evidence of no relationship. KR-domiciled suppliers (Samsung, SK Hynix) file nothing with the SEC and are structurally absent.",
  "rules": "Cite concentration and edges only by filing reference. trust='asc280_inferred' identities are inference — state as such, never as fact."
}
```

The `trend` array carries the alpha: NVDA top-customer concentration rising 13% → 19% across
fiscal years is a citable, deterministic risk trajectory that needed no graph. The
`coverage_note` is load-bearing anti-hallucination text — without it the model reads sparse edges
as "no dependencies".

## 7. S1 — the fundamental card

Every numeric element traces to a persisted row. The narrative block is the only generated content,
and it renders *below* the numbers, never in place of them.

| Block | Content | Source |
|---|---|---|
| composite + subscores | seven bars, each with its inputs on hover | `fundamental_score_daily` |
| anchor band | spot marked against `buy_below / observe_low / observe_mid / observe_high / risk_above`; base/bear/bull × 1y/3y | `valuation_anchors_daily` |
| method + confidence | `company_type`, method name, `confidence` and **every reason** | `valuation_anchors_daily.confidence_reasons_jsonb` |
| target gap | our 1Y anchor vs `uw_positioning.target_avg`, as a number | join on the shipped `uw_positioning` |
| concentration | top-customer %, multi-year trend, filing citation | `customer_concentration` (P4) |
| coverage | what is `na` and why — the explicit absence list | `na` propagation from I4 |
| provenance | `engine_version`, `inputs_hash`, `as_of` per block | every persisted row |
| **narrative** | `headline` · `thesis` · `price_view` · `target_gap` · `bear_case` · numeric `invalidation` · `monitorables` · `evidence_ledger` · mandatory `unknowns` | stage 5, DeepSeek — Pydantic → `model_json_schema()` → strict function-calling, matching `TradeInsightAiOutcome` |
| audit verdicts | per-claim `pass / warn / fail / unverifiable` | `fundamental_audit_results` |

The narrative block carries its audit state visibly. A `fail` verdict suppresses the offending claim
rather than the whole block, and says so — silent suppression would make the audit unfalsifiable to
the reader.

The coverage block is mandatory, not a footer, and it is computed from `na` propagation rather than
written by the model. It is the deterministic backstop behind the narrative's `unknowns`: a card
that renders only what it has, without stating what it lacks, reads as complete when it is partial.

**The card is fully usable with the narrative absent** — model disabled, provider down, or audit
failed. That is the practical meaning of "the deterministic surfaces never depend on the model".

Confidence reasons render in full rather than collapsing to a badge. "medium because segment
revenue is missing and the latest filing is 140 days old" is actionable; "medium" is not.

## 8. S2 — `/industry_graph`

**Goal, stated narrowly:** show where in the stack valuation and revenue-concentration risk are
*clustering*, so attention goes to the right **layer** rather than the loudest **ticker**. S1 can say
NVDA looks rich; only S2 can say all six L3 infra names are rich at once. Secondary goals: coverage
(what is unanalysed) and crowding (how concentrated the watchlist's own attention is).

**Form: a layer × chain heatmap, not a node-link diagram.** The name is `/industry_graph`; the v1
rendering is a matrix.

```
          GPU  Foundry  Memory  Networking  Power  ...
  L1  ▓▓▓   ▓▓      ▓▓▓▓      ·        ·
  L2   ·     ·        ·        ·        ·
  L3   ·     ·        ·       ▓▓▓      ▓▓▓▓
  L4   ·     ·        ·        ·        ·
  ↑ rows are supply-chain depth (L1 upstream → L5 downstream): position carries meaning
```

Cell = aggregate over that (layer, chain) — median composite, share rich vs cheap, or mean
top-customer concentration, switchable. Click → the names in that cell → click again → S1.

**Rows pivot between `layer` and `company_type`** (§5.3). By layer: *where in the stack is the
value*. By company type: *which valuation regime is stretched*. Same cells, same engine, one extra
axis — available only because the two classifications were kept orthogonal.

**Why a matrix and not a graph.** The test for a visualization is whether *position* encodes
anything. In a node-link layout of this taxonomy, node position would be decided by a force
algorithm — arbitrary. In the matrix, row position is supply-chain depth — informative. A node-link
diagram would also draw lines implying a *measured* supply chain, when the adjacency is a
hand-authored ontology in `watchlist_taxonomy.py` plus the handful of edges §6 actually found. The
matrix makes the same structural claim without the false precision, at roughly a fifth of the work.

Every other question the map is asked — cheapest layer, worst concentration trend, what is
unanalysed — is a `GROUP BY`, not a topology. Only propagation ("if L2 capex stops, what breaks and
in what order") genuinely needs a graph, and propagation needs edges we do not have.

**Skeleton (dense, exists today).** Measured 2026-08-10 from `watchlist_taxonomy.py`: **220 tickers,
38 chains, 235 memberships across 7 populated layers** (L1 58 · L2 38 · L3 60 · L4 44 · L5 23 · X 7
· THM 5), 10 tickers holding multiple chains. Already normalized into `watchlist_chain` by migration
`113`, indexed in both directions. The structure needs no new ingestion — only the render.

The module enumerates 220 tickers while the table is scoped to the watchlist; the rendered set is
the **intersection with the active watchlist** (`removed_at IS NULL`), same rule as §4.3.

**Encodings — the reason this is not the existing filter rail.** argon already ships a layer-rail
chain filter (v0.11.4). Redrawing membership adds nothing. What is new is that every cell is
computed from S1's engines:

| Encoding | Source | Reads as |
|---|---|---|
| cell fill | median `fundamental_score_daily.composite` | research priority (§5 I5 — a sort key, not a forecast) |
| cell texture | share of names rich vs cheap in the band | is this pocket stretched |
| corner mark | mean `customer_concentration.top_customer_pct` + trend | revenue-concentration risk |
| hatched | no S1 rows yet, or all `confidence = low` | not analysed / not trustworthy |

Unanalysed cells render hatched rather than blank. A map that silently drops uncovered names
misrepresents coverage as completeness.

**Node-link graph: deferred behind a kill criterion.** Build it only if P4's named-edge yield comes
back materially above the handful measured in §3.3. If it does not, the matrix was always the correct
artifact and the renderer was never owed.

**Aggregation.** All rollups are computed **read-time from S1 rows** (`reports/industry_graph.py`) —
no new persisted table, no second scoring path. One engine, two renderings.

## 9. Phases

Two tracks plus a deferred one. S1 P0–P2 gate everything; S2 G1 is independent and can run in
parallel from day one; the loop harness (§10) starts only after both surfaces are trusted.

Every phase is **ad-hoc triggered** (§5.1). No cron is added until the method stops moving.

### S1 — fundamental card

| Phase | Ships | Gate | Verification |
|---|---|---|---|
| **P0** | Commit-bug fix + a test asserting on a **fresh connection** | Own PR — independent prod data-loss bug, deploys ahead of feature work | Mini's `massive_fundamentals` row count > 0 after a manual run |
| **P1** | massive `/v2` migration (103 fields, full history) + UW segment revenue; registry entries | Scoring over 8 shallow quarters is the weakest possible imitation | NVDA quarters reach the 1990s; FY2026 segment revenue matches the filed 10-K to the dollar |
| **P2** | `fundamental_score_daily` + `valuation_anchors_daily`; `fundamental_method_params` seeded; company-type routing; confidence downgrades; on-demand refresh endpoint | The method must be fixated before anything renders it | 3 hand-checked tickers reproduce hand-computed anchors; re-run with unchanged inputs is idempotent; **flipping one ticker's `company_type` changes `inputs_hash` and produces new anchors**; editing a weight row moves `engine_version` for every ticker |
| **P3** | The card's deterministic blocks (§7) — subscores, anchor band, confidence reasons, coverage, provenance | — | Every rendered number resolves to a persisted row; the coverage block lists a real `na` |
| **P4** | Concentration ledger + sparse edge overlay (§6) | After the card; the concentration block ships empty in P3 | NVDA yields a concentration row with a real accession and multi-year trend; ANET→META exists as the reference `asc280_named` edge; TSM yields a 20-F-sourced row proving the corpus extension |
| **P5** | Stage 5 narrative — `analysis_kind='fundamental'`, DeepSeek, evidence ledger, staged numeric audit | Needs P3 (numbers to constrain it) and P4 (concentration facts worth citing) | Real worker-path smoke: enqueue from the card → worker claims → narrative renders with audit verdicts persisted; **disabling the provider leaves the card fully usable** |

### S2 — `/industry_graph`

| Phase | Ships | Gate | Verification |
|---|---|---|---|
| **G1** | Layer × chain matrix from `watchlist_chain`, cells empty, drill-down to ticker list → S1 | none — skeleton exists, runs parallel to S1 P0–P2 | Cell membership matches `watchlist_chain ∩ active watchlist`; the 10 multi-chain tickers appear in each of their cells |
| **G2** | Cell encodings from S1 + read-time rollups | needs S1 P2 | A cell's fill equals the median of its members' `fundamental_score_daily`; uncovered cells hatch, never blank |
| **G3** | Concentration corner marks | needs S1 P4 | Every mark traces to `customer_concentration` rows with real accessions |

**Deferred:** ranked long/short book, congress/13F enrichment, true estimate gap (blocked on gated
tier), cross-chain flow/weight sizing, node-link graph (kill criterion above).

## 10. The loop harness (pi) — next stage, not this one

The distinction that scopes this spec (user ruling, 2026-08-10):

| | In v1 | Deferred |
|---|---|---|
| **Model call** — DeepSeek writes stage 5 prose over fixed numbers | ✅ §5.1 | |
| **Loop harness** — decides *when* to recompute, re-analyse, re-plot; runs research loops | | ⏭ pi agent |

A provider call inside a job is not an agent. Every stage here is triggered by a human clicking
"Compute now" or, later, by cron. Nothing forms an intention. What is deferred is the layer that
does: an external **pi agent** harness driving these jobs on its own schedule and judgement.

**What this spec owes that harness — and already provides:** every stage is a callable job function
with a `ticker_filter` · every output is a persisted, addressable row · `engine_version` +
`inputs_hash` make any recompute decision checkable · §5.3's invalidation table tells a harness
exactly what a change dirties. A harness driving this needs no new argon surface; it needs these
jobs to be callable and their results durable, which they are by construction.

**What it must not be handed:** write access to `fundamental_method_params`. A harness that can
retune the weights it is also evaluating closes a loop nobody is watching. Parameter changes stay a
human action — consistent with argon's invariant that every mutating agent action routes through a
gate.

**Entry gate — do not start before all three hold:** S1 P4 and S2 G2 are live; the composite has been
inspected against outcomes for at least one quarter; and the per-subscore `na` rate is known, so
coverage can be stated honestly rather than plausibly.

This is argon goal-ladder **Stage 2** (self-tending desk). Scoping it here would import a stage-2
problem into stage-1 work.

## 11. Risks

1. **The method is fixated on unvalidated priors.** The §5.2 weights have no backtest behind them
   and the spec says so. Holding them in `fundamental_method_params` makes them sweepable and
   `engine_version` makes a revision auditable; neither makes the current values right. Do not let
   the composite acquire authority it has not earned.
   Inherited from the blueprint, which also ships no backtest, hit-rate or P&L. The composite is a
   **sort key** and must be labelled research priority on every surface — argon's own theta-harvester
   precedent is correct ordering with a losing selection.
2. **The concentration ledger is decorative rather than decision-useful.** MED confidence it
   earns its place. The `trend` array is the specific bet; if concentration trends turn out flat
   and uninformative across the core 25, P4 should be cut rather than extended.
3. **S2 duplicates the existing filter rail.** Its defence is that cells carry computed attributes
   (§8). If G2's encodings turn out to say nothing G1's drill-down list did not, S2 is a
   `GROUP BY` with a colour ramp. Judge this at G2, before G3 is built.
4. **The `na` rate makes the method look thinner than it is — or hides how thin it is.** Coverage is
   rendered, not suppressed (§7), so this is a visible risk rather than a silent one. Measure the
   per-subscore `na` rate at P2; it is also the harness entry gate (§10).
5. **Fluent fabrication in the P5 narrative.** Real but bounded: it lands last, over numbers that
   already exist and are already rendered; the audit stage diffs it; and the card works without it.
   The `unknowns` field is mandatory, not optional. If audit `fail` rates stay high after prompt
   iteration, ship the card without the narrative — that was a complete product at P4.

## 12. Open items

- Confirm massive has no segment-revenue endpoint before P1 locks segments to UW
  (`[INFERRED]` from the capability audit's silence — MED-HIGH, needs a 2-minute live probe).
- The UW capability audit is dated 2026-05-15 (~3 months stale). The live MCP surface exposes
  `get_income_statement_screener` / `get_earnings_screener` names absent from local docs —
  re-probe before assuming either availability or gating.
- Audit the other `_repo()` consumers for the same no-commit pattern (out of scope here).
