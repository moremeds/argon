# Fundamental analysis method — design

*Status: DRAFT — revised after review · 2026-08-10 · branch `feat/fundamental-pm-agent`*

> **Revision note (2026-08-10).** A review found two hard errors in the first draft, both verified
> against source before acceptance: the narrative lane cannot use `trade_insight_ai_analyses`
> (`snapshot_id` is `NOT NULL` with a cascade to `trade_insight_snapshots`, so a fundamental row has
> no legal parent), and massive `/v2` is **frozen at 2020-Q1** per argon's own probe — using it as the
> backbone would have rendered FY2020 financials as current. Both decisions are reversed below.
> Point-in-time observation storage is **mandatory in v1** (user ruling), not deferred.

---

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
| 预期差 as *estimate* gap | Forward estimates are Advanced+-gated. Ship the **price-target** gap (`uw_positioning.analyst_target_avg` vs anchors); never fake the estimate gap |
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
everything back.

**The production table is stale, not empty** — corrected 2026-08-10 from a live mini query:
**669 rows across 86 tickers, latest `fetched_at` 2026-06-01**, latest period 2026-05-03. Those rows
arrived through some other historical or manual path; the scheduled job has contributed nothing. The
first draft said "empty or stale", and the distinction turns out to matter enormously — see the P0
exit criterion in §9, which the row count would have satisfied *without the bug being fixed*.

Blast radius is narrow: `ohlc_pull` writes through `market_data.py` (4 commits, safe).
`fundamentals_jobs` is the confirmed case. Other `_repo()` consumers were not individually
traced — worth a follow-up audit, out of scope here.

### 3.2 Data inventory

**Available and unused (currently costs zero UW calls/day):**

| Source | Content | Integrated? |
|---|---|---|
| massive `/vX/reference/financials` | **current production endpoint** — quarters 2009-06-27 → 2026-03-28, live | Partially — argon persists ~13 fields, `limit=8`. The endpoint is right; the depth is not |
| massive `/v2/reference/financials` | 103 pre-computed fields, quarters 1997-09-30 → **2020-03-31, frozen** | No — and it must never be the current-data backbone |
| UW `/stock/{t}/income-statements`, `/balance-sheets`, `/cash-flows` | 94 quarters each | No |
| UW `/stock/{t}/fundamental-breakdown` → `rev_breakdown` | **revenue by product AND geography** | No |
| UW `/stock/{t}/info` | sector, marketcap, beta, issue_type | No |
| SEC EDGAR `data.sec.gov` + `efts.sec.gov` FTS | filings, XBRL, concentration language | No |

**Already shipped and reusable:** `uw_positioning` (analyst targets/ratings, insider net flow,
13F aggregates, short interest, earnings reactions) — daily, correctly committed, live on the
stock page. The target column is **`analyst_target_avg`** (`065_uw_positioning.sql:26`), not
`target_avg`.

**Source roles, with a fallback chain — massive is not universal.** Live probe of the core 25
(2026-08-10) found `/vX` current coverage for **23 of 25**:

**MEASURED — full core-25 matrix committed** at
`docs/research/2026-08-10-fundamental-source-coverage/` (probe:
`scripts/research/fundamental_source_coverage.py`). Quarterly counts only; the pipeline is quarterly
and an unfiltered `/v2` count mixes annual/trailing rows and overstates usable coverage.

| State | Meaning | Tickers |
|---|---|---|
| `covered` | current `/vX` quarterly data | **23 of 25** |
| `history_only` | no current data; `/v2` quarterly history exists | **ASML** — 93 rows to 2019-12-31 |
| `annual_only` | **unusable by a quarterly pipeline** | **TSM** — `/vX` 0, `/v2` quarterly 0, 76 annual/trailing |

The gap is **not uniform**: ASML needs a fallback for 2020→present; TSM needs one for *everything*.
`/vX` depth also varies **8–69 quarters** (GEV 8, META 16, PLTR 25, GOOGL 38), so "history reaches
199x" is a per-ticker claim and never a universal one — this is what "ticker-relative" means
operationally. META/GEV/PLTR/APP show zero `/v2` rows, consistent with the FB→META rename, a 2024
spinoff and post-freeze IPOs; flagged for P1a follow-up rather than assumed.

**Four successive readings of this endpoint were wrong**, which is why P1a's output is a committed
matrix rather than a claim. The failure modes, recorded so they are not repeated:

1. **`/v2` takes the ticker in the URL path** (`/v2/reference/financials/{ticker}`) while **`/vX`
   takes it as a query parameter** — querying `/v2` in `/vX` form returns **404**, read as "no
   coverage".
2. An unfiltered count is not a quarterly count.
3. Probe limits must be constant across tickers (an earlier run reported NVDA at 5 rows against
   ASML's 391).
4. **Limits are per-endpoint**: `/vX` rejects `limit>100` with **HTTP 400** while `/v2` accepts 1000.
   A shared `limit=1000` 400s `/vX` for all 25 names — which a bare row-count probe records as "no
   current coverage anywhere". The committed probe caught this only because it persists HTTP status.

**A zero must be distinguished from an error, and a count from a filtered count, before either
becomes evidence.** Anything probing a provider persists the status code alongside the count.

**A plausible common cause, flagged as inference.** §3.3 records that the upstream tier files
**20-F, not 10-K** (TSM: 6-K ×741, 20-F ×15, zero 10-Ks), and the two names missing from `/vX` are
exactly the two foreign private issuers in the core 25. `[INFERRED, MED]` — the correlation is
measured; the provider's actual derivation path is **not**, and "massive builds `/vX` from domestic
XBRL" remains an unverified explanation that P1a must confirm or discard. What is established is
narrower and sufficient to design against: **these two tickers lack current `/vX` coverage.** If the
inference does hold, one structural fact — foreign-issuer filing status — breaks both the named-edge
graph and the statements backbone, and any name reachable only via 20-F should be assumed thin at
every provider until probed, not just at EDGAR. Treat that as a hypothesis to test in P1a, not a
rule to design around yet.

| Precedence | Source | Role |
|---|---|---|
| 1 | massive `/vX` | **backbone** for current figures — 23/25 of the core |
| 2 | UW statements (94q) | **fallback when `/vX` is absent**, not merely a cross-check (revises A4) |
| 3 | SEC XBRL `companyconcept` | last resort; reaches 20-F filers massive cannot |
| — | explicit `na` | when all three fail. A covered-looking card over an uncovered name is the worst outcome |
| history | massive `/v2` | pre-2020 tail **where it exists** — availability and span are ticker-relative, not universal |
| overlap | `/vX` ∩ `/v2` | reconcile and persist disagreements, never silently prefer one |

**Foreign issuers emit `na` for anchors in v1 — units before valuation.** A fallback returning
statement values without a currency, XBRL-unit, FX-date and ADR-ratio contract would divide a
non-USD revenue figure by a USD market cap and produce an anchor wrong by an order of magnitude —
silently, and with full provenance attached, which is worse than no anchor. Foreign-issuer names
render `na` with the reason stated; their statements still ingest, only valuation abstains.

**The measured coverage narrows this sharply.** Every one of the 23 `covered` tickers reports XBRL
units `USD` and `USD / shares` — **there is no non-USD unit anywhere in the set argon will actually
ingest.** The FX/ADR contract is therefore *not* a P1b prerequisite; it is owed only if and when the
UW/SEC fallback is built for TSM and ASML, which are precisely the two names without `/vX` data. The
currency work defers with the fallback, and `na` is the whole of v1's obligation.

When that fallback is built, `/v2` already answers part of it: it exposes USD-normalized variants
(`revenuesUSD`, `debtUSD`, `shareholdersEquityUSD`, …) plus `foreignCurrencyUSDExchangeRate`. That
covers the historical window; the current window still needs UW or SEC XBRL units resolved
explicitly.

Coverage expectations are **per ticker**, never global: "history reaches 1997" is a claim about NVDA,
not about the core 25, and the card must render each name's real span.

**Quarter identity uses `/vX.end_date` = `/v2.reportPeriod`**, never `calendarDate` — the latter
diverges for non-calendar fiscal issuers such as NVDA and AMD, which would silently mismatch quarters
in the overlap zone.

The overlap zone is not incidental: it is the only place field-name parity between the two endpoints
can be validated, and it is what makes the pre-2020 tail trustworthy enough to score against.

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
| A1 | **Own queue** `fundamental_narrative_analyses` — stage 5, phase P5. **Not** a lane on `trade_insight_ai_analyses` | The first draft claimed this lane was "verified live" on the strength of `analysis_kind` existing (migration `067`) and per-row dispatch at `trade_insights_ai.py:142`. Both are true and both are irrelevant: `017:9` makes `snapshot_id` `NOT NULL REFERENCES trade_insight_snapshots ON DELETE CASCADE` and `run_id` `NOT NULL`, so a fundamental row has no legal parent; dispatch is binary `is_blast`, so `'fundamental'` would silently run the trade prompt; `TradeInsightAiOutcome` demands scenario cards / VRP / preferred expression; and `fetch_unscored_analyses` filters only `status='succeeded'`, so every fundamental row would enter the trade outcome ledger. **The cost of this reversal is real** — the new queue re-pays the SKIP-LOCKED claim logic, heartbeats, per-provider workers and polling hook that A1 originally existed to avoid. That is the price of domain isolation, not an oversight; do not "simplify" it back |
| A2 | New pure-compute package **`src/uw_scan/fundamentals/`** | Follows `theta_harvester/` / `chanlun/` precedent. Not `reports/` — those are read-time reshapes; these are nightly persisted computations |
| A3 | New API router **`api/routers/fundamental.py`** | `routers/trade_insights.py` is already ~600 lines; module-size budget |
| A4 | **massive `/vX` → UW statements → SEC XBRL → explicit `na`**, a fallback chain rather than a single backbone; `/v2` for the pre-2020 quarterly tail where it exists; **UW `fundamental-breakdown`** for segments | Reversed twice. First draft picked `/v2` for its field count — argon's probe records it frozen at 2020-Q1, so a "current" card would have shown FY2020. Then a live core-25 probe found `/vX` covers only 23/25: **TSM and ASML have no current `/vX` coverage** — ASML retains quarterly `/v2` history to 2019, TSM has *no quarterly `/v2` rows at all* (its 76 rows are annual/trailing, which the quarterly pipeline cannot consume). Both are foreign private issuers, which is a measured correlation but `[INFERRED]` as a cause — P1a confirms or discards it. UW is therefore a **fallback**, not a cross-check. The IB→UW→FMP→massive priority rule is scoped to *live quotes/greeks* and does not govern here |
| A10 | **Immutable point-in-time observations** for statements, segments and filings; canonical views derived on top | User ruling. Two sources that disagree by six years (A4) make reconciliation mandatory regardless, and PIT is most of the same work. Retrofitting it after rows exist means rebuilding history that was never captured — restatements overwrite the evidence an old `inputs_hash` was computed from |
| A11 | **On-demand refresh enqueues a persisted run**, returns `202` — never a synchronous router write | The technicals precedent (`stock.py:285`) is deliberately bounded and says to promote it once work becomes async or batched. This stage calls massive, UW and SEC and writes many tables; a synchronous handler leaves partial state with no retry record. argon's rule is mutations route through `/jobs` |
| A12 | **Own worker role `ai-fundamental`** for the narrative queue | argon already pins roles per lane (`ai-codex`, `ai-claude`, `ai-deepseek`). A shared worker polling two queues needs fair-polling and independent heartbeats to avoid one lane starving the other; a separate role gets that for free and lets the fundamental lane be scaled or disabled without touching trade insights |
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

Three tiers, and the separation is the point: **observation payloads are immutable, canonical views
are derived, outputs are versioned.**

Precise immutability contract, because "nothing is ever updated" was overstated: **the payload and
its identity columns are immutable; sighting metadata (`last_seen_at`) is mutable.** An unchanged
refresh updates one timestamp and writes no new fact. If that distinction ever becomes load-bearing
for audit, sightings move to their own append-only table — but not before, since a row per unchanged
poll is a lot of rows to prove nothing changed.

**Tier 1 — immutable source observations (A10).** One row per thing a provider actually said. A
restatement is a new row; the old one is never altered or deleted.

| Table | Key columns | Registry |
|---|---|---|
| `fundamental_statement_obs` | PK `obs_id`; **UNIQUE `(source, ticker, period_end, period_type, content_hash)`**; `provider_record_id`, `filing_accession`, `filing_published_at`, `first_observed_at`, `last_seen_at`, `raw_jsonb`, `field_map_version` | event-temporal → **DatasetRegistryEntry** |
| `fundamental_segment_obs` | PK `obs_id`; **UNIQUE `(source, ticker, period_end, dimension, segment_name, content_hash)`**; revenue, `filing_accession`, `first_observed_at`, `last_seen_at` | event-temporal → **DatasetRegistryEntry** |
| `fundamental_edge_obs` | see §6 — PK `obs_id`, UNIQUE on `(filing_accession, fact_hash)` | event-temporal → **DatasetRegistryEntry** |
| `sec_filing_documents` | PK `filing_accession`; `ticker`, `form`, `filing_date`, `filing_published_at`, `document` (compressed `BYTEA`), `fetched_at` | dimension, exempt |

**Identity is content, not fetch time.** The previous draft keyed observations on `observed_at`,
which is when *we* fetched — so every unchanged refresh would have inserted another row, directly
contradicting P1b's own idempotence gate. Dedupe is on `content_hash` over the normalized payload:
an unchanged refresh bumps `last_seen_at` and writes **no new fact row**; a restatement hashes
differently and becomes a new immutable observation. `provider_record_id` is stored when the provider
supplies one, because a stable upstream ID beats a hash we computed.

`content_hash` is computed over a **normalized** payload with an explicit exclusion list — provider
response envelopes carry request IDs and generation timestamps that differ on every call, and hashing
those would make every refresh look like a restatement. The normalization rule is committed with the
field map in P1a, and the period key is `end_date` (`/vX`) ≡ `reportPeriod` (`/v2`), never
`calendarDate`.

`first_observed_at` is when we first saw it; `filing_published_at` is when the world could have known
it. Point-in-time queries filter on the latter — that is what stops look-ahead in a future sweep.

**Filing documents live in Postgres, not on disk** (F-6). The pipeline caches by accession because
filings are immutable once accepted, but the only volume in `docker-compose.yml` is the lake at
`:ro` — a container-local cache dies on every redeploy. **R2 is not the alternative:** it is retired,
and per CHANGELOG "the worker refuses to boot when retired R2 settings are present", added after a
dead R2 bucket silently froze `vol_index_daily` for 13 days. Compressed documents for the core 25 are
tens of megabytes; Postgres is durable, already the persistence rule here, and needs no new
infrastructure.

**Tier 2 — canonical views, derived not stored.** `fundamental_statement_current` resolves the
newest non-superseded observation per `(ticker, period_end, period_type)` under a documented source
precedence (the §3.2 chain: `/vX` for current, **UW then SEC XBRL where `/vX` is absent**, `/v2` for
the pre-2020 tail where it exists, explicit `na` when all fail).
Overlap-zone disagreements are surfaced, never silently resolved: a materialized
`fundamental_source_discrepancies` row records both values and the delta.

**Tier 3 — versioned outputs.** `engine_version` identifies the *method*; `inputs_hash` identifies the
*inputs*. Result identity needs both — a `company_type` flip or a restatement arriving on the same
date changes the inputs while leaving `engine_version` untouched, so a key without `inputs_hash`
collides and the second result is lost.

| Table | Key columns | Registry |
|---|---|---|
| `fundamental_runs` | PK `run_id`; `ticker`, `mode ∈ {refresh_external_facts, recompute_from_cached_facts}`, `status`, per-stage status/timing, `rows_written`, `error`, `attempt`. **Partial unique index on `(ticker) WHERE status IN ('queued','running')`** | run ledger — dimension, exempt |
| `fundamental_run_outputs` | PK `run_id`; **`anchor_result_id REFERENCES valuation_anchors`**, **`score_result_id REFERENCES fundamental_scores`**, `reused BOOLEAN` — one row per run, typed columns so both links are real foreign keys | run ledger — dimension, exempt |
| `valuation_anchors` | PK `result_id`; **UNIQUE `(ticker, as_of, engine_version, inputs_hash)`**; `company_type`, `method`, 5 anchors, base/bear/bull × 1y/3y, `confidence`, `confidence_reasons_jsonb`, `inputs_jsonb`, `inputs_hash`, `source_obs_ids`, `run_id` | temporal → **DatasetRegistryEntry** |
| `fundamental_scores` | PK `result_id`; **UNIQUE `(ticker, as_of, engine_version, inputs_hash)`**; one column per subscore, composite, `inputs_hash`, `source_obs_ids`, `run_id` | temporal → **DatasetRegistryEntry** |
| `customer_concentration` | PK `(ticker, fiscal_period, filing_form, filing_accession)`; `top_customer_pct`, `customers_over_10pct`, `none_over_10pct`, `magnitude_basis`, `filing_date`, `excerpt` | event-temporal → **DatasetRegistryEntry** |
| `fundamental_narrative_analyses` | own queue (A1) — PK `analysis_id`; `ticker`, `run_id`, `provider`, `prompt_version`, `prompt_text`, `prompt_payload_jsonb`, `output_schema_jsonb`, `status`, `outcome_jsonb`, `markdown`, timings. **No `snapshot_id`** | keyed by analysis — dimension, exempt |
| `fundamental_audit_results` | PK `(analysis_id, claim_seq)`; `claim_text`, `extracted_value`, `backing_source`, `backing_value`, `verdict ∈ {pass,warn,fail,unverifiable}`, `stage ∈ {deterministic,model}` | dimension, exempt |
| `fundamental_company_type` | PK `(ticker, effective_from)`; `company_type`, `source ∈ {rule,manual}` — historised, because it is an `inputs_hash` input | dimension, exempt |

`source_obs_ids` is what makes I2 real: it records the exact tier-1 rows a computation consumed, so
an old `inputs_hash` can be reconstructed even after later restatements arrive.

**The current-result view resolves through `fundamental_run_outputs`, not through a `run_id` column
on the result.** An identical rerun is supposed to produce one logical output (T4), which means the
second run *reuses* the first run's immutable row. If the result carried a single `run_id`, that row
would still be stamped with run 1, so a view joining "latest successful run" to its outputs would
find nothing for run 2 and the current result would vanish — while updating the stamp would mutate
history. The bridge resolves both: run 2 gets its own association row with `reused = true`, pointing
at the same `result_id`. The bridge uses **typed columns** (`anchor_result_id`, `score_result_id`)
rather than one polymorphic `result_id` — a single column pointing at either table can carry no
enforceable foreign key, which is how dangling references get in.

Resolution is then: active `engine_version` (from the pointer below) → latest successful run for that
ticker and date → its associated `result_id`.

**Method versioning — immutable versions plus a singleton pointer.** A `BOOLEAN active` column with
a partial unique index guarantees *at most* one active version, not exactly one: a failed activation
or a stray manual update leaves zero, and every computation silently has no method. A NOT NULL
foreign key from a one-row table makes zero unrepresentable.

| Table | Key columns |
|---|---|
| `fundamental_method_versions` | PK `engine_version`; `code_version`, `param_hash`, `created_at`, `note`. **No `active` flag** |
| `fundamental_method_params` | PK `(engine_version, param_key)`; `param_value NUMERIC`. **Immutable** — retuning inserts a new version, never edits rows |
| `fundamental_method_state` | `singleton_id INT PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1)`; `active_engine_version TEXT NOT NULL REFERENCES fundamental_method_versions`. **Seeded by migration; a `BEFORE DELETE` trigger raises** |

`CHECK (singleton_id = 1)` constrains the row's *value*, not its *existence* — it happily permits
`DELETE`, which would leave zero active versions and every computation silently method-less. The
NOT NULL FK removes the null case; the delete trigger removes the empty case; and stage 2 raises
loudly rather than defaulting if the pointer cannot be read. Three mechanisms because "exactly one"
needs both bounds enforced, and the first draft claimed it with only one.

Activation is one atomic `UPDATE` of the pointer. `engine_version` is derived
`{code_version}:{param_hash[:8]}` and written once at version creation. An "active version" view
backs S1 and S2 so neither surface reimplements the resolution rule.

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

Five stages, run as one of two **modes**. A run executes its mode's full stage list — the mode
selects where the run *starts*, never which stages it may skip in the middle:

```
1 INGEST   source observations, immutable   → *_obs tables (§4.4)
2 DERIVE   TTM, growth, margins, ratios     → pure functions, no I/O
3 ANCHOR   company-type-routed valuation    → valuation_anchors
4 SCORE    subscores → composite            → fundamental_scores
5 NARRATE  DeepSeek prose over 3+4, audited → fundamental_narrative_analyses + fundamental_audit_results

refresh_external_facts        : 1 → 2 → 3 → 4 → (5 if requested)
recompute_from_cached_facts   :     2 → 3 → 4 → (5 if requested)
```

A refresh that stopped at stage 1 would hand the user new facts and stale numbers — the opposite of
what "refresh" means. Both modes always land on fresh anchors and scores; only NARRATE is optional,
and it is enqueued rather than run inline.

**ANCHOR precedes SCORE.** The first draft ran SCORE at 3 and ANCHOR at 4 while the
`valuation_position` subscore consumed the anchors — a cycle that no ordering *within* a stage could
resolve. Anchors are computed from derived fundamentals only and never read the composite back, so
the dependency is a straight line: `DERIVE → ANCHOR → SCORE`.

Stages 1–4 are deterministic and reproducible from `inputs_hash`. Stage 5 is a **provider call
inside a job**, not an agent: it is triggered by cron or by request, never by its own judgement, and
it consumes 3+4 as read-only inputs. Nothing in the pipeline decides when to run itself — that is
the loop harness, deferred to §10.

Stage 5 degrades cleanly. If DeepSeek is unavailable, disabled, or its output fails the audit, the
card renders stages 1–4 with the narrative block marked absent. **The deterministic surfaces never
depend on the model.**

**Trigger: ad-hoc first, cron later** (user ruling, 2026-08-10). No nightly job until the method
stops moving — scheduling an unstable method just fills tables with rows carrying dead
`engine_version`s. Job functions take a `ticker_filter` from day one so the cron, when it comes, is a
scheduler entry and not a rewrite.

**Ad-hoc means enqueued, not synchronous** (A11). `POST /fundamental/{ticker}/refresh` writes a
`fundamental_runs` row and returns `202`; a worker executes the stages and updates per-stage status.
The technicals "Compute now" precedent is a *shape* precedent, not a licence — that handler is
bounded to one cached-data recompute, and `stock.py:285` says to promote it the moment work becomes
async or batched. This pipeline calls massive, UW and SEC and writes across a dozen tables.

The two modes differ only in whether they pay a provider:

| Mode | Starts at | Costs |
|---|---|---|
| `refresh_external_facts` | stage 1 — pull and persist new observations, then recompute | provider quota, latency, rate limits |
| `recompute_from_cached_facts` | stage 2 — existing observations only | nothing external; safe on every parameter change |

Splitting them is what makes a weight change cheap: retuning re-runs 2→4 across the universe without
touching a provider. Conflating them would put an API bill behind every parameter edit.

Concurrency: one active run per ticker. A second request while a run is `queued` or `running`
returns the existing `run_id` rather than starting a duplicate. A failed run resumes from its first
incomplete stage — completed stages are not re-executed, which is the practical payoff of persisting
stage status rather than only a final state.

Invariants:

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
3. Retuning becomes a new immutable method version plus a pointer flip — no deploy, and the old
   version's outputs stay valid and comparable rather than being silently reinterpreted.

| Subscore | Inputs (derived at stage 2) | Direction | seed weight |
|---|---|---|---:|
| `growth` | revenue TTM YoY, 2-quarter YoY acceleration | higher better | 0.20 |
| `profitability` | gross + operating margin, level and 4-quarter trend | higher better | 0.20 |
| `capital_efficiency` | FCF conversion, return on invested capital | higher better | 0.15 |
| `balance_sheet` | net debt / EBITDA, interest coverage, current ratio | lower leverage better | 0.15 |
| `valuation_position` | spot vs `observe_low..observe_high` band from stage 4 | cheaper better | 0.15 |
| `concentration_risk` | top-customer %, its multi-year trend (§6) | lower better | 0.10 |
| `expectations_gap` | our 1Y anchor vs `uw_positioning.analyst_target_avg`, insider net, short interest | wider positive gap better | 0.05 |

Seeded as version `v1_prior` (header + child rows, §4.4). Parameter rows are **immutable**: retuning
creates a new `engine_version` and flips the header pointer. The set also holds the §5.4 downgrade
thresholds — anything a future sweep might want to move.

**Parameters as data force `engine_version` to be derived, not hand-written.** It is
`{code_version}:{param_hash[:8]}`, computed once at version creation. A hand-bumped version would let
someone change a weight while the version stayed put, silently destroying comparability across
`fundamental_scores` rows — the exact question §5.6 exists to answer.

`valuation_position` consumes stage 3 (ANCHOR) and is computed in stage 4 (SCORE). ANCHOR must never
read the composite back; the dependency is a straight line or the score becomes self-referential.

`concentration_risk` returns `na` until S1 P4 lands; `na` subscores are dropped and the remaining
weights renormalize. Renormalization, not zero-fill — a zero would read as "no concentration risk",
which is a fabricated fact.

**This table is a rubric, not an implementation.** Direction and weight do not determine a score:
normalization, winsorization, breakpoints, lookback windows and the spot-date rule are all still
free, and two conforming implementations would disagree. **P2 does not exit without a method
appendix** carrying, for every subscore and every company type, the exact transformation and a
worked example reproducible by hand. Until that exists the method is named, not fixated — the
review's F-1, and it stands.

Field-level mapping onto massive `/vX` (and `/v2` for the pre-2020 quarterly tail) is the P1 data-contract
spike's job and is deliberately not guessed here.

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
| `power_infra` | EV/EBITDA, asset-base anchored | asset-heavy, dividend-aware. **No backlog term** — §3.2 records backlog as unavailable at every tier, so a method requiring it would return `na` for every name it routes |
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

`engine_version` is stamped on `fundamental_scores` and `valuation_anchors`, and bumps
on **any** change to weights, rubric, routing, or a method. `inputs_hash` covers the derived inputs.
Together they answer the only question that matters when the method evolves: *did this score move
because the company changed, or because I changed the method?*

Cross-version comparison is invalid by default. Rows carrying different `engine_version` values may
be charted on the same axis only with the version break marked.

## 6. Concentration ledger + edge overlay

An anonymous-counterparty disclosure is a **concentration row, not an edge**. `dst_ticker` is
`NOT NULL` on edges; the `curated` tier does not exist.

**Edges are observations, not relationships** (F-7 fix). The first draft made
`(src_ticker, dst_ticker, edge_type)` unique *and* promised "never DELETE — audit trail". Those
contradict: a later filing restating the same relationship would have had to overwrite the accession,
excerpt and magnitude that justified the earlier one. One filing fact = one immutable row.

```sql
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_edge_obs (
    obs_id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filing_accession   TEXT NOT NULL,             -- lock enforced: no accession, no row
    fact_hash          TEXT NOT NULL,             -- over normalized (dst, type, magnitude, excerpt)
    extractor_version  TEXT NOT NULL,             -- NOT part of identity; records how it was found
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
    filing_date        DATE NOT NULL,
    filing_published_at TIMESTAMPTZ NOT NULL,     -- PIT boundary (A10)
    fiscal_period      TEXT,
    excerpt            TEXT NOT NULL,
    observed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT inferred_needs_basis CHECK
      (trust_tier <> 'asc280_inferred' OR identity_inference IS NOT NULL),
    UNIQUE (filing_accession, fact_hash)
);
```

Identity is `fact_hash`, not extraction order. A positional `fact_seq` is stable only while the
extractor never changes — improve the regex and every fact renumbers, so re-processing the same
filing writes duplicates that look like new disclosures. `extractor_version` is recorded but
deliberately excluded from the uniqueness key: a better extractor finding the same sentence must
recognise it, not re-file it.

**But hash identity alone cannot retract.** If extractor v1 emits a false META edge and v2 correctly
emits *nothing*, there is no new row to supersede the false one — absence cannot overwrite presence,
so a known-wrong edge stays current forever. Fixing duplicate-on-improve created
cannot-retract-on-improve; both need the same missing concept, **the extraction run**:

```sql
CREATE TABLE IF NOT EXISTS uw_scan.filing_extraction_runs (
    extraction_run_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filing_accession   TEXT NOT NULL,
    extractor_version  TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    fact_count         INT,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at        TIMESTAMPTZ,
    UNIQUE (filing_accession, extractor_version)
);
```

**Ownership is not membership** — and getting that wrong retracts valid facts. If each observation
carried a single `extraction_run_id`, then for v1 emitting `{A, B}` and v2 correctly emitting `{A}`:
A already exists (deduped by `fact_hash`) still stamped with v1, so v2 owns nothing, and a
"latest-run's observations" projection drops **both** facts. The valid one dies with the false one.

Facts and sightings are separate relations:

```sql
CREATE TABLE IF NOT EXISTS uw_scan.filing_extraction_run_facts (
    extraction_run_id  BIGINT NOT NULL REFERENCES uw_scan.filing_extraction_runs,
    obs_id             BIGINT NOT NULL REFERENCES uw_scan.fundamental_edge_obs,
    PRIMARY KEY (extraction_run_id, obs_id)
);
```

The fact row stays deduplicated and immutable; each run records **which facts it saw**. **The current
projection is the latest *succeeded* run's membership set** — so v2 re-asserts A and simply omits B,
retracting the false edge while the true one survives, and v1's full result stays queryable for
audit. A failed run never becomes current, so a crashed extraction cannot empty a filing.

The same rule governs `customer_concentration`. Retraction is a projection concern, never a `DELETE`.

This is the third form of one problem. `fact_seq` duplicated facts when the extractor improved;
`fact_hash` alone could not retract; run *ownership* retracted too much. Each fix was locally correct
and structurally incomplete because the missing concept was never the key — it was that **"what the
fact is" and "who saw it" are different relations**, and any single table conflates them.

**Current-relationship projection** — a view, not a table:
`fundamental_edge_current` reads the **membership set of the latest succeeded `filing_extraction_run`
per accession**, then takes the newest surviving one per `(src_ticker, dst_ticker, edge_type)` and
derives `status` from filing recency (`active` / `stale` after absence from the newest same-form
filing / `retired` past 400 days). Nothing is mutated to compute it; the full observation history
stays queryable, which is what "audit trail" was supposed to mean.

**Pipeline** — one pass per run, `edge_graph_refresh`:

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
4. Re-processing a filing is idempotent by `(filing_accession, fact_hash)`. Nothing expires by
   mutation; recency is resolved in the view. **No row is ever updated or deleted.**

**Ops — all mandatory before P4 writes a row:**

| Requirement | Detail |
|---|---|
| dependency | **`edgartools` is not in `pyproject.toml`** — adding it (with a pinned version) is a P4 task, not an assumption |
| proxy bypass | every `sec.gov` / `efts.sec.gov` call uses `httpx(trust_env=False)`. Through `127.0.0.1:7897` the TLS handshake fails outright (curl exit 35, HTTP 000) while DNS resolves fine — mirrors the documented massive-WS `proxy=None` rule |
| User-Agent | SEC-required contact email, from config; requests without it are refused |
| rate limit | SEC's published ceiling is 10 req/s; the client throttles below it and is the only path to `sec.gov` |
| retry | bounded exponential backoff on 429/5xx, capped attempts, failures recorded on the `fundamental_runs` row rather than raised into the UI |
| cache | filings are immutable once accepted — cache by accession in **`sec_filing_documents`** (§4.4) and never re-fetch the same document. Not container disk: the only compose volume is the lake at `:ro` |

**Discovery gate before build.** P4 starts with a read-only probe over the core 25 that reports
concentration-row yield and named-edge yield. If the ledger's `trend` arrays come back flat and
uninformative, P4 is cut rather than extended (Risk 2), and the node-link graph question (§8)
resolves itself.

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
| composite + subscores | seven bars, each with its inputs on hover | `fundamental_scores` |
| anchor band | spot marked against `buy_below / observe_low / observe_mid / observe_high / risk_above`; base/bear/bull × 1y/3y | `valuation_anchors` |
| method + confidence | `company_type`, method name, `confidence` and **every reason** | `valuation_anchors.confidence_reasons_jsonb` |
| target gap | our 1Y anchor vs `uw_positioning.analyst_target_avg`, as a number | join on the shipped `uw_positioning` |
| concentration | top-customer %, multi-year trend, filing citation | `customer_concentration` (P4) |
| coverage | what is `na` and why — the explicit absence list | `na` propagation from I4 |
| provenance | `engine_version`, `inputs_hash`, `as_of` per block | every persisted row |
| **narrative** | `headline` · `thesis` · `price_view` · `target_gap` · `bear_case` · numeric `invalidation` · `monitorables` · `evidence_ledger` · mandatory `unknowns` | stage 5 — a **`FundamentalNarrativeOutcome`** Pydantic model → `model_json_schema()` → DeepSeek strict function-calling. Borrows the *mechanism* of `TradeInsightAiOutcome`, never its schema: that model demands scenario cards, VRP assessment and preferred expression, none of which a fundamental analysis has |
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
| cell fill | median `fundamental_scores.composite` | research priority (§5 I5 — a sort key, not a forecast) |
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

**Every aggregate needs a stated basis.** A cell median is meaningless across mixed engine versions
or stale `as_of` values, so G2 fixes four rules before it aggregates: a common `as_of` (the latest
date on which the cell's members share the active `engine_version`), rows on superseded versions are
excluded rather than mixed, the **coverage denominator is the cell's full membership** — not the
subset that happens to have rows — and **a cell whose members share no common date/version renders
`unavailable`**, never a silently mixed number. A cell where 2 of 6 names are analysed shows the
2-name aggregate *and* says 2/6.

## 9. Phases

Two tracks plus a deferred one. Every phase is **ad-hoc triggered** (§5.1); no cron until the method
stops moving.

### S1 — fundamental card

| Phase | Ships | Gate | Verification |
|---|---|---|---|
| **P0** | Commit-bug fix + a test asserting through a **freshly opened connection**. Commit **per successful ticker**, rolling back only the failing ticker's transaction | Own PR — independent prod data-loss bug, deploys ahead of feature work | **Freshness delta, not row count**: record a ticker's `fetched_at` before the run, invoke the *real scheduled function*, then assert from a **new connection** that its `fetched_at` advanced past the run start. Plus a regression proving one ticker's DB error does not discard the tickers already processed |
| **P1a** | **Data-contract spike** (no schema). ✅ **coverage matrix DONE** — `docs/research/2026-08-10-fundamental-source-coverage/` + `scripts/research/fundamental_source_coverage.py`. Remaining: the exact `/vX`→column field map, the `content_hash` normalization/exclusion rule, and a `/vX`∩`/v2` overlap reconciliation on one quarter. The **currency / XBRL-unit / FX-date / ADR-ratio** contract is **deferred with the UW/SEC fallback** — all 23 covered tickers are USD-only (§3.2) | The first draft chose a frozen endpoint for its field count; the second mis-probed `/v2` and read 404s as absence; the third shared a limit across endpoints and 400'd `/vX` for all 25. No ingestion is designed until every source is measured per ticker, not read about | ✅ every core ticker's real span and state recorded, reproducibly. Still open: an overlap-zone quarter agrees across `/vX` and `/v2` field-for-field (or the disagreement has a resolution rule); the field map is committed |
| **P1b** | Immutable observation tables + canonical views + backfill/incremental modes; registry entries | Scoring over 8 shallow quarters is the weakest possible imitation | Each core ticker reaches **its own** measured span (NVDA current via `/vX`; TSM/ASML history via `/v2` with the 2020→present gap rendered, not hidden); re-ingest is idempotent; a simulated restatement adds a row without destroying its predecessor; segment revenue matches the filed **10-K or 20-F** after unit normalization |
| **P2** | Method appendix (worked examples) · method version tables · ANCHOR then SCORE · confidence downgrades · `fundamental_runs` + enqueued refresh endpoint | The method must be fixated before anything renders it | 3 hand-checked tickers reproduce hand-computed anchors from the appendix; recompute with unchanged inputs is idempotent; **flipping one ticker's `company_type` changes `inputs_hash` and yields new anchors**; a new method version coexists with the old on the same date; exactly one version is active |
| **P3** | The card's deterministic blocks (§7) — subscores, anchor band, confidence reasons, coverage, provenance drill-down; API models + `gen:types` + tab/route wiring; loading/stale/error states | — | Every rendered number resolves to a persisted row; the coverage block lists a real `na`; a stale-version row renders as stale rather than current |
| **P4** | Discovery gate → concentration ledger + sparse edge observations (§6); `edgartools` dependency added | After the card; the concentration block ships empty in P3 | Gate reports real yield before build; NVDA yields a concentration row with a real accession and multi-year trend; ANET→META exists as the reference `asc280_named` edge; TSM yields a 20-F-sourced row; re-processing a filing writes no duplicate |
| **P5** | Stage 5 narrative — **`fundamental_narrative_analyses`** queue, own `ai-fundamental` worker role, DeepSeek, evidence ledger, staged numeric audit | Needs P3 (numbers to constrain it) and **P4 *resolved*** — shipped or killed. A killed P4 is a resolution: the payload carries an explicit unsupported `supply_chain` block | Real worker-path smoke: enqueue → worker claims → narrative renders with audit verdicts persisted; an audit `fail` suppresses the claim; **disabling the provider leaves the card fully usable**; `fetch_unscored_analyses` returns zero fundamental rows; **the P4-killed path produces a narrative with a stated coverage absence** |

### S2 — `/industry_graph`

| Phase | Ships | Gate | Verification |
|---|---|---|---|
| **G1** | Layer × chain matrix from `watchlist_chain`, drill-down to ticker list → S1. **Built and tested in parallel from day one; route stays unreleased** | Publishing an empty matrix would ship the "colouring book with no colours" this spec rejects, duplicating the shipped chain filter | Cell membership matches `watchlist_chain ∩ active watchlist`; the 10 multi-chain tickers appear in each of their cells; route is not reachable in the nav |
| **G2** | Cell encodings from S1 + read-time rollups + the common-version/coverage rules above. **Route released here** | needs S1 P2 | A cell's fill equals the median of its members' `fundamental_scores` at a shared `engine_version`; partial cells show their coverage fraction; uncovered cells hatch, never blank |
| **G3** | Concentration corner marks + row pivot (layer ⇄ company_type) | needs S1 P4 | Every mark traces to `fundamental_edge_obs` / `customer_concentration` rows with real accessions; trend selection rule is explicit and reproducible |

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

**Entry gate — do not start before all three hold:** S1 P4 is **resolved** (shipped or killed) and
S2 G2 is live; the composite has been inspected against outcomes for at least one quarter; and the
per-subscore `na` rate is known, so coverage can be stated honestly rather than plausibly. A killed
P4 satisfies the first condition — gates depend on decisions being made, not on features existing.

This is argon goal-ladder **Stage 2** (self-tending desk). Scoping it here would import a stage-2
problem into stage-1 work.

## 11. Acceptance tests

The identity and idempotence rules above are only real if something fails when they break. Each row
is a required test, not a suggestion.

| # | Scenario | Expected |
|---|---|---|
| T1 | Identical provider payload fetched twice | **one** observation row; `last_seen_at` bumped |
| T2 | Restated payload for the same period | **two** observation rows; the first is unaltered |
| T3 | Same ticker/date/engine, different `inputs_hash` (e.g. `company_type` flipped) | **two** output rows, both retrievable |
| T4 | Identical inputs recomputed | **one** logical output; `inputs_hash` stable |
| T5 | Delete or null the active method pointer | **rejected** — NOT NULL FK; zero-active is unrepresentable |
| T6 | Refresh requested twice in quick succession | **one** active run; the second returns the existing `run_id` |
| T7 | Run fails mid-pipeline, then retried | resumes at the first incomplete stage; completed stages not re-executed |
| T8 | Same filing re-processed after an extractor change | **no duplicate** edge observations (`fact_hash` identity) |
| T9 | P4 killed, then P5 run | narrative produced with an explicit unsupported `supply_chain` block |
| T10 | Fundamental narratives exist, trade outcome backfill runs | `fetch_unscored_analyses` returns **zero** fundamental rows |
| T11 | Container replaced | cached filings survive (Postgres, not container disk) |
| T12 | Provider disabled | card renders stages 1–4 fully; narrative block marked absent |
| T13 | Cell members hold mixed engine versions | aggregate uses the shared active version; coverage fraction shown |
| T14 | Cell members share **no** common date/version | cell renders **unavailable**, never a silently mixed aggregate |
| T15 | Extractor v1 emits a false edge, v2 emits nothing for that filing | edge disappears from the current projection; v1's observation still queryable |
| T15b | **v1 emits `{A, B}`, v2 emits `{A}`** | A **survives**, B retracts. The load-bearing case — a naive latest-run projection drops both |
| T15c | v2 emits `{A, B}` identically to v1 | no duplicate fact rows; both runs have membership for the same `obs_id`s |
| T19b | Foreign issuer (TSM/ASML) reaches the anchor stage in v1 | anchors render **`na` with reason**, never a number derived from unnormalized TWD/EUR |
| T20b | `/v2` queried in `/vX` query-param form | probe treats **HTTP 404 as an error, not as zero coverage** |
| T16 | Extraction run crashes mid-filing | the failed run never becomes current; the prior succeeded run still projects |
| T17 | `DELETE` the method state row | **rejected by the `BEFORE DELETE` trigger**; worker startup also fails loudly if the pointer is unreadable |
| T18 | Identical rerun, then query the current view via the second run | resolves to the same `result_id` through a `reused = true` association |
| T19 | TSM / ASML (no **current** `/vX` coverage; TSM additionally has no quarterly `/v2` rows) | falls back to UW, then SEC XBRL, then renders explicit `na` — never a blank that reads as zero |
| T20c | A `/v2` count taken without `type=Q` | the coverage matrix records the **quarterly** count; an unfiltered total never stands in for it |
| T20 | Non-calendar fiscal issuer (NVDA, AMD) in the overlap zone | quarters match on `end_date` ≡ `reportPeriod`; `calendarDate` is never used as the key |
| T21 | Provider envelope changes (request id / timestamp) with identical financials | `content_hash` unchanged → no new observation |

Gates before merge: `uv run pytest`, ruff, `scripts/check_no_yahoo.py`, and under `web/`
`npm run typecheck && npm run test && npm run lint && npm run build`, plus Playwright coverage of the
card drill-down and provider-down paths.

## 12. Risks

1. **The method is fixated on unvalidated priors.** The §5.2 weights have no backtest behind them and
   the spec says so. Versioned parameter rows make them sweepable and make a revision auditable;
   neither makes the current values right. Inherited from the blueprint, which also ships no
   backtest, hit-rate or P&L. The composite is a **sort key** and must be labelled research priority
   on every surface — argon's own theta-harvester precedent is correct ordering with a losing
   selection.
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

## 13. Open items

All provider claims below are repository snapshots, not live probes. **P1a re-measures every one of
them before any schema is designed** — the `/v2`-frozen error came from trusting exactly this kind of
second-hand reading.

- Confirm massive has no segment-revenue endpoint before segments lock to UW (`[INFERRED]` from the
  capability audit's silence — MED-HIGH).
- The UW capability audit is dated 2026-05-15 (~3 months stale). The live MCP surface exposes
  `get_income_statement_screener` / `get_earnings_screener` names absent from local docs — re-probe
  before assuming either availability or gating.
- Confirm `/vX`'s actual field set. The 103-field count belongs to the frozen `/v2`; what `/vX`
  exposes is unmeasured here, and the subscore rubric assumes ordinary statement lines rather than
  pre-computed ratios.
- Audit the other `_repo()` consumers for the same no-commit pattern (out of scope here).

**Resolved by review — recorded so they are not re-opened.** Round 1: narrative queue is
domain-isolated, not a lane (A1); `/vX` is the backbone (A4); PIT observations are mandatory (A10);
refresh enqueues rather than writes synchronously (A11); ANCHOR precedes SCORE (§5.1); edges are
immutable per-filing observations (§6); G1 releases with G2 (§9). Round 2: observation identity is
`content_hash`, not fetch time; output identity is `(ticker, as_of, engine_version, inputs_hash)`;
the active method is a NOT NULL singleton pointer, not a boolean flag; both run modes end on fresh
anchors and scores; P5 gates on P4 *resolved*, not shipped; filings cache in Postgres; narrative gets
its own `ai-fundamental` worker role (A12).

Round 3 (live-probed): P0's gate is a freshness delta, not a row count — production already holds
669 rows, so the old gate passed without the bug being fixed; massive covers only 23/25 of the core,
so A4 becomes a fallback chain; the method pointer needs a delete trigger, not just a `CHECK`;
identical reruns resolve through `fundamental_run_outputs`; active runs are enforced by a partial
unique index; extraction runs make retraction possible; immutability is payload-scoped.

**One review recommendation was rejected on evidence.** Round 2 proposed R2 for raw filing storage.
R2 is retired and configuring it is a **boot failure** — verified in runtime code at
`worker/scheduler.py:215`, added after a dead R2 bucket froze `vol_index_daily` for 13 days.
`CLAUDE.md` still carries the stale "R2 lake is primary" line, which is the likely source of the
suggestion — **that line should be corrected in a separate PR**, since it will keep misleading
readers and has now done so at least once.
