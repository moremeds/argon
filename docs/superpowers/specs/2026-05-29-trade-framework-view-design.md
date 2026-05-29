---
title: Trade Framework View — design spec
date: 2026-05-29
status: draft (awaiting review)
topic: trade-framework-view
supersedes_ui: web/components/stock/tabs/TradePlanTab.tsx (deterministic trade plan)
related:
  - docs/superpowers/plans/2026-05-28-trade-insights-ai-model-independence-deepseek.md (DeepSeek provider — merged, origin/main 95d370e)
  - docs/research/goyal-saretto-ipca-options/09-massive-fundamentals-coverage.md (massive fundamentals coverage)
  - external: github.com/himself65/trade-skills (the `trade` skill being ported), cloned at /Users/chenxi/projects/trade-skills
---

# Trade Framework View — design spec

## 1. Summary

Replace the deterministic, rule-based trade-plan tab with an **AI-driven "Framework" view** that ports the
`trade-skills` knowledge library and judgment style into our Trade Insights AI pipeline. The Framework reads
the trade-skill's decision stack — gamma regime → IV regime → 3-axis structure gate → conviction count →
confluence → pitfall scan → **counterfactual structure selection → a single decisive best setup** — rendered
as reasoned English prose with scannable glance headers.

It is produced by the **same single AI run** we already queue per provider (Codex / Claude / DeepSeek), as an
**additive `framework{}` block** on `TradeInsightAiOutcome`. The existing AI analysis tab keeps its current
(audit) rendering; the trade-plan tab renders the new `framework{}` as the decision stack. No second pipeline
and no extra *run* per ticker — though the enriched prompt (full KB + bigger payload) does raise per-run token
cost (see §13).

Data is sourced **only from Unusual Whales (UW) + massive.com**. No Funda AI, no TradingView, no Playwright,
no Level-2 order book. Inputs the framework cannot source (forward consensus estimates, channel checks, L2
imbalance, etc.) are surfaced as `na` in the conviction ledger — never fabricated.

## 2. Motivation

- The current trade-plan tab (`_build_trade_plan` → `report.trade_plan`) is deterministic if/else output the
  user considers "useless." It is deleted.
- The `trade-skills` skill encodes a strong options-trading judgment framework (24 pitfalls, 7 case studies,
  gamma/strategies/price-action frameworks) and an operating principle ("tape over thesis") we want our AI to
  reason with — but the skill assumes the model fetches its own data (Funda AI / TradingView). We feed a
  bounded, pre-assembled payload instead, so the port is: **embed the knowledge in the prompt, and feed the
  inputs from UW + massive.**
- The **TSEM Q1-2026 case study** (`trade-skills/.../ticker/tsem-2026-05.md`) crystallizes the single most
  valuable thing the Framework adds over today's AI analysis: **structure selection**. There, direction was
  called correctly (bull) but the trader picked a pin/vega structure (diagonal) when high conviction + event-IV
  demanded a directional defined-risk structure (bull put spread / risk reversal). The diagonal returned
  ~5-15%; the alternatives ~97% / multi-x. The lesson — *"trade the bigger edge," run the counterfactual P/L
  across candidate structures and commit to the one that captures the most upside in your highest-conviction
  scenario* — is the spine of the Framework output.

### Current AI analysis vs. the new Framework (same run, two lenses)

| | Current AI analysis (audit tab) | New Framework tab |
|---|---|---|
| Prompt | `MARKET_INTELLIGENCE_PROMPT` v5.3 — linear MANDATORY DECISION ORDER to one trade | same run; prompt + full trade-skills KB; asks for a decision **stack** |
| Question | "What is the trade?" | "What's the regime read, the conviction, the traps — then the best trade?" |
| Inputs | current bounded payload | **T0+T1+T2 enriched** (positioning + fundamentals + macro + tape derivations) |
| Output | `TradeInsightAiOutcome` (archetype/bias/entry/candidates) | **same object + additive `framework{}`** |
| Style | structured / audit-shaped | trade-skill **narrative** + glance headers |

Enriching for the Framework also upgrades the current analysis for free (bigger payload + KB). The audit tab's
rendering is unchanged.

## 3. Locked decisions

| Decision | Choice |
|---|---|
| Compute model | AI-driven (enrich prompt + payload) |
| Pipeline | One run per provider, two views; additive `framework{}` on `TradeInsightAiOutcome` |
| Providers | Codex (strict schema) + Claude (lax) + DeepSeek (HTTP/reasoning); 3-way toggle on the Framework tab. DeepSeek already on `origin/main` (`95d370e`). |
| Knowledge port | **Full library verbatim** — 24 pitfalls + 7 case studies + gamma/strategies/price-action frameworks |
| Output format | Narrative + glance header, collapsible decision stack, **English** |
| Output spine | header → three_axis → gamma → catalyst → conviction → confluence → pitfalls → candidates (counterfactual P/L) → **best_setup** → what_changes → bottom_line |
| Best-setup logic | counterfactual Bull/Base/Bear P/L across candidates; structure-by-conviction rule; decisive single pick |
| Tone | **Assertive** + no-fabrication guardrail (absent factor = `na`, never a bluffed number) |
| Earnings | **Swing-default, LEAPS-aware** (`exit_before_print` / `stand_aside`; `hold_through_leaps` only when explicitly classified long-term) |
| Input scope | T0 (have/plumbed) + T1 (UW-200 fetchers) + T2 (massive fundamentals) |
| Old trade plan | Delete `trade_plan` (legs/max-loss) + producers; **keep** `setup`/`SetupClassification` (shared w/ watchlist + scanner) |
| Out of scope | TradingView/Playwright, L2 order book, forward consensus estimates (→ `na`, deferred), Funda-only fundamentals |
| Branch | fresh `feat/trade-framework-view` off **updated** main (local is 24 commits behind — `git pull` first) |

## 4. Architecture & data flow

```
                 ┌──────────── worker (massive role) ────────────┐
 massive ───────▶│ fundamentals_jobs: /vX financials, float,      │──┐
                 │ dividends, splits  (+ rates backdrop)           │  │
                 └────────────────────────────────────────────────┘  │ persist
                 ┌──────────── worker (uw role) ─────────────────┐    ▼
 UW ───────────▶│ positioning refresh: SI%float, analysts,        │──┐ ┌──────────────┐
                │ inst-ownership, insider, econ-calendar, earnings │  ▼ │   Postgres   │
                │ history  + VIX inject                            │    │  warm store  │
                └────────────────────────────────────────────────┘    └──────┬───────┘
 (existing) GEX+flip, walls, IV-regime, VRP, skew, OHLCV, net-prem ──────────▶│
                                                                              │ reads
                          ai worker claims a queued analysis row              │
                          ┌──────────────────────────────────────────────────▼──────┐
                          │ analysis_input.py → enriched payload                       │
                          │ prompt_text.py + trade_framework_kb (full library)         │
                          │   ↓ codex exec / claude --print / deepseek HTTP (sandboxed)│
                          │ TradeInsightAiOutcome  (+ framework{} additive)            │
                          └──────────────────────────┬─────────────────────────────────┘
                                                      │ persist
                                          trade_insight_ai_analyses (per provider)
                                          ┌───────────┴───────────┐
                              client-poll │                       │ client-poll
                        ┌─────────────────▼──┐            ┌───────▼─────────────────┐
                        │ AI audit tab        │            │ trade-plan tab =        │
                        │ [Codex][Claude][DS] │            │ FRAMEWORK view          │
                        │ current layout      │            │ [Codex][Claude][DS]     │
                        └─────────────────────┘            │ decision stack + prose  │
                                                           └─────────────────────────┘
```

Key properties:

- **One run, two views.** `framework{}` is additive; the audit tab ignores it, the Framework tab renders it.
- **Framework data arrives via polling**, not the synchronous `api.stock()` report. The trade-plan tab becomes
  a client island polling `trade_insight_ai_analyses` per provider (reuse `useAiAnalysisPolling.ts` + the
  provider toggle). This is a real shift from today's pure-RSC `TradePlanTab.tsx`.
- **New inputs must be persisted before analysis runs.** Worker refreshes the warm store; the AI worker reads
  it. If fundamentals/positioning haven't backfilled for a ticker, the payload marks them `na` and the
  framework degrades gracefully — never blocks.
- **Secrets stay out of model subprocesses.** All UW/massive fetching happens in the worker, never passed to
  `codex exec`/`claude --print`. DeepSeek's HTTP runner uses `DEEPSEEK_API_KEY` from its own runner env.

## 5. Data layer

### 5.1 Inputs by tier

**T0 — already in payload or already plumbed (no new fetcher; surface/derive only)**
- GEX + derived zero-gamma flip strike (sign change in `strike_gex_curve`), call/put walls (top OI strikes).
- IV regime: `iv_rank_1y`, term-structure slope (front/back) → event-IV vs demand-IV classification.
- VRP / HV-vs-IV, 25d skew + smile + per-strike call/put OI → P/C ratios.
- Multi-day net call/put premium: `net_call_premium`/`net_put_premium` are **already persisted** (migrations
  `002`, `015`); read the persisted daily snapshots to derive a 3-day persistence flag.
- VIX: **already plumbed** (`scan_universe` ticker, `fetch_stock_state`, regime engine) — inject into payload.
- OHLCV derivations from stored bars: 3-close trend, nearest S/R + touch counts, 50/200-DMA,
  drawdown-from-6M-high, volume vs 5d/30d (distribution-day flag), 5d pre-earnings run, post-earnings gap.

**T1 — UW endpoints accessible on our tier (new fetchers; low effort)**
- Short interest % float — `/api/shorts/{t}/interest-float/v2` (current `short_data` has borrow rate, not SI%).
- Analyst ratings + price targets + action timing — `/api/screener/analysts`.
- Institutional ownership — `/api/institution/{t}/ownership`.
- Insider net flow — `/api/insider/{t}/ticker-flow`.
- Macro proximity — `/api/market/economic-calendar` → hours-to-next-print → gamma-suppression flag.
- Earnings calendar/history — `/api/earnings/{t}` (verify whether already integrated). **Must yield the
  forward `next_er_date`** — the catalyst section + earnings-handling decision depend on it; if the endpoint is
  history-only, source `next_er_date` from the existing ticker/stock payload (UW ticker info commonly carries
  next-earnings) and mark `na` if neither has it. `implied_move` is **derived** from the ATM straddle of the
  expiry bracketing earnings (T0 chain/IV), not fetched.

**T2 — massive fundamentals (new source module; medium build, Polygon-shaped)**
- Financials — `/vX/reference/financials` (income / balance / cash-flow): revenue, gross/op/net margin, FCF,
  debt, share-count delta / issuance (buyback proxy). `/v2/reference/financials` for pre-2009 history if ever
  needed (frozen ~2020). See `09-massive-fundamentals-coverage.md`.
- Float — `…/fundamentals/float`.
- Corporate actions — `…/corporate-actions/{dividends,splits}`.
- Rates backdrop — nominal 10Y + breakevens → real yield. **Prefer reusing the existing rates source**
  (`storage/rates_repository.py` / FRED gold module) where it covers; only fall back to massive
  `…/economy/{treasury-yields,inflation-expectations}` for missing series. Decide at plan time.

### 5.2 Sources, storage, jobs, migrations

- Sources: `src/uw_scan/sources/massive_fundamentals.py` (new, Polygon-shaped, sibling to `ohlc.py`);
  add T1 fetchers to `src/uw_scan/sources/uw.py` + slugs to `api/endpoints.py`.
- Storage (own domain modules — never appended to `repository.py`): `storage/fundamentals.py`,
  `storage/positioning.py`. Tables persisted (per the persist-results rule).
- Worker jobs: `worker/jobs/fundamentals_jobs.py` (nightly backfill + refresh, `massive` role) and a
  **dedicated** `worker/jobs/positioning_jobs.py` (`uw` role, its own daily-ish cadence — **not** folded into
  `full_scan`, to avoid multiplying scan-loop UW QPS per §13). Idempotent, ET cron. Both follow the per-worker
  shard/claim discipline (stable shard ownership or `FOR UPDATE SKIP LOCKED`) so multiple `massive`/`uw`
  workers never double-fetch (worker CLAUDE.md: *no duplicated provider work*).
- Migrations: highest on main is `064` → new start at `065+`, **numbered in build order** (UW positioning is
  built first → `065_uw_positioning.sql`; massive fundamentals second → `066_massive_fundamentals.sql`).
  **Migration-DDL idempotency** uses `IF NOT EXISTS` (and `ON CONFLICT DO NOTHING` for any seed rows) — that
  is the standing migration rule. The **runtime storage upsert** in the mixins is a *different* concern: it
  uses `ON CONFLICT (ticker, snapshot_date) DO UPDATE` so a same-day re-fetch keeps the **latest** snapshot
  (mirrors the existing intraday/spot upserts) — re-running the job is still idempotent in effect (same input
  → same row).
- **Freshness TTL:** every persisted row is timestamped; the payload builder marks an input `na` when stale —
  ~100 days for quarterly fundamentals, ~5 trading days for positioning (SI%/analysts/inst-own), ~1 day for
  macro/VIX. A missed refresh degrades to `na`, never feeds stale numbers (mirrors the rejected-TV TTL rule).

### 5.3 Out of scope / deferred (recorded so the framework marks them `na`, not fabricated)

- **TradingView / Playwright** — skipped (user instruction). TV has no real options flow (its GEX is a proxy);
  its only genuine fill is forward analyst estimates = 1 of the 8 conviction factors, not worth the brittleness.
- **Level-2 order book** — not feasible: UW/massive give L1 NBBO at best, and L2 is worthless on a 15-min delay
  and wrong-horizon for an EOD analysis tool. Permanent `na` / reasoning-only.
- **Forward consensus estimates** — UW `earnings-estimates` = 403 (Advanced+); massive Benzinga consensus =
  partner add-on (404 on our key). `na` for now; deferred path = Benzinga add-on or UW Advanced+ tier.
- **Funda-only items** — channel checks, buy-side whisper, customer/segment concentration (filings), IPO
  roadshow range, greenshoe/lock-up. `na` / reasoning-only.

## 6. Payload enrichment — `reports/trade_insights_ai/analysis_input.py`

`build_trade_insights_ai_analysis_input()` gains bounded sections, each tolerant of missing data (emit `null`
+ an availability flag so the prompt can mark `na`):

- `positioning`: SI% float, analyst consensus + target (hi/lo/avg) + recent rating actions, institutional
  ownership %, insider net flow.
- `fundamentals`: latest-quarter revenue, gross/op/net margin, FCF, total debt, share-count delta (buyback),
  float, recent dividends/splits.
- `macro`: VIX, hours-to-next-macro-print + suppression flag, rates backdrop (10Y nominal, real yield).
- `flow_series`: multi-day net-call-minus-put premium + 3-day persistence flag (from persisted snapshots).
- `tape`: the OHLCV-derived bundle (T0 derivations). Derived in a new `cards/framework_tape.py` deriver (pure
  function); numbers passed into the payload (not left for the model to compute).
- `setup`: the existing `SetupClassification` (type + score) passed as a rule-based prior the framework can
  corroborate or contradict (the Framework *reads* `setup`; it does not own it — see §10).

## 7. Prompt enrichment — `reports/trade_insights_ai/`

- **KB module (new):** `reports/trade_insights_ai/trade_framework_kb.py` exporting `TRADE_FRAMEWORK_KNOWLEDGE`
  — the trade-skills library embedded verbatim (24 pitfalls + 7 case studies + gamma-framework.md +
  strategies.md + price-action-framework.md). Kept in its own module so `prompt_text.py` stays under the
  1000-line budget; `build_trade_insights_ai_prompt()` imports and concatenates it. (The model subprocess has
  no filesystem, so the KB must be baked into the prompt string at build time.)
- **Decision stack:** extend the prompt's decision order so the **framework stack drives** (gamma regime → IV
  regime → 3-axis gate → conviction count → confluence → pitfall scan → counterfactual candidates →
  best_setup), and the legacy outcome fields (archetype/bias/entry/candidate_structures) are emitted
  *consistent with* the framework (e.g. `best_setup` aligns with the chosen `candidate_structures` entry) so
  the audit tab stays coherent. Version bump: v5.3 → **v6.0 (framework)**.
- **Three directives, enforced in the prompt:**
  1. *Find the best setup* — produce `candidates[]` with Bull/Base/Bear P/L each, and a `best_setup` whose
     `why_not_alternatives` justifies the pick against the runners-up (the TSEM counterfactual). Hard rule:
     high internal-vs-consensus gap → directional defined-risk, not pin/vega; calendar/diagonal only when
     implied-move ÷ distance-to-short-strike ≤ ~0.75.
  2. *Assertive* — commit to ONE best_setup, decisive verdicts, no hedging. **Guardrail:** confidence is
     about commitment given the data; any factor with no data is `na`, never bluffed. (Structurally enforced —
     see §8.) When the *core* inputs (tape / flow / IV) are themselves absent, the decisive call is
     `position_type: stand_aside` with "insufficient data" — assertiveness never means inventing a setup on no data.
  3. *Earnings = swing-default, LEAPS-aware* — `catalyst.handling` defaults to `exit_before_print` /
     `stand_aside` when ER is inside the hold window; `hold_through_leaps` only when `position_type: leaps` is
     explicitly classified. Swing semantics apply to `position_type: swing` only (entry DTE 21–60, never an
     expiry inside the hold window); LEAPS use long-dated expiries by definition and may sit through ER.
     **Hold-window circularity:** the earnings check uses a *fixed pre-structure* hold-window assumption (the
     swing default, ~10–14 calendar days) evaluated **before** structure selection — `catalyst.handling` is
     decided first, then `best_setup` is chosen consistent with it (no dependency on the not-yet-picked DTE).
- **Defined-risk only** — all `candidates` and `best_setup` must be defined-risk (no naked shorts); prompt
  states it and the validator enforces it (§8).

## 8. Output contract — `models/trade_insights_ai_parts/`

Add a `TradeFramework` model in **`models/trade_insights_ai_parts/framework.py`** (the DeepSeek PR already
introduced the `trade_insights_ai_parts/` package), re-exported via `trade_insights_ai_parts/__init__.py` and
the package root so `from uw_scan.models import …` and OpenAPI component names stay stable. Add an **optional**
`framework: TradeFramework | None` field to `TradeInsightAiOutcome` (additive — preserves contract identity).

```
TradeFramework
  header        { thesis_one_liner: str, position_type: "swing"|"leaps"|"stand_aside", spot,
                  conviction_n: int(0..8)  // canonical = conviction.score (validator-enforced equal) }
  three_axis    { direction { verdict: "bull"|"bear"|"neutral", prose }
                  vega      { regime: "event_iv"|"demand_iv"|"low_iv", ivr, term_slope, prose }
                  asymmetry { rule_on: bool, structure_family: "directional_defined_risk"|"pin_vega", prose } }
  gamma         { regime: "short"|"long", flip_strike, call_wall, put_wall, prose }
  catalyst      { next_er_date, dte_to_er, implied_move,
                  handling: "exit_before_print"|"stand_aside"|"hold_through_leaps", prose }
  conviction    { score: int(0..8), factors: [ {name, status: "yes"|"no"|"na", note} ], prose }
  confluence    { aligned: bool, signals: [ {name, direction} ], prose }
  pitfalls      [ {id, title, triggered: bool, note} ]
  candidates    [ {name, legs, debit_credit, net_delta, net_vega,
                   pnl_bull, pnl_base, pnl_bear, defined_risk: bool} ]
  best_setup    { structure (a candidates[] name OR "stand_aside"), legs, cost, max_risk, rationale,
                  why_not_alternatives, invalidation }   // stand_aside ⇒ no legs; invalidation = re-engage trigger
  what_changes  [ {signal, effect} ]
  bottom_line   prose
```

- **Tri-provider schema/validation.** The DeepSeek PR added runner-declared schema/validator flags. The
  `framework{}` fields go into: the **strict** schema (Codex), the **lax/leniency** path (Claude + DeepSeek
  JSON mode). Coercion for cosmetic drift (conviction as string→int, structure synonyms, `rows[N]` vs
  `rows.N`) lives in `reports/trade_insights_ai/leniency/*` — normalize in the validator, don't tighten the
  prompt.
- **New validator rule:** `reports/trade_insights_ai/validator_rules/framework.py` — light checks only:
  `conviction.score ∈ 0..8` and equals count of `factors.status == "yes"`; `header.conviction_n ==
  conviction.score`; enums valid; **every `candidates` entry is `defined_risk == true` (no naked shorts)**;
  `best_setup.structure` must equal one of `candidates[].name` **verbatim** (case-fold + whitespace/hyphen
  normalization only — *not* alias/family fuzzing; the prompt instructs the model to echo the exact candidate
  name it picked, so candidate names must not carry strikes that the family-level pick would omit) and that
  candidate must be `defined_risk`, **or** be the literal `"stand_aside"` (no legs required). A naked / undefined-risk candidate is a **hard validation failure** (errors the row via the
  existing strict→lenient→error path), never coerced into a defined-risk variant. Prose fields are
  intentionally unvalidated (the skill's "no machine validation" reality).
- **Assertive-but-honest is structural:** `conviction.factors[].status` is a hard `yes|no|na` enum, so the
  model cannot turn an absent channel-check/estimate into conviction — it shows as `na`. Confidence lives in
  the prose verdict; honesty lives in the factor ledger. The conviction ledger is a **fixed canonical set of
  8 factors** — the bull-conviction checklist ported verbatim from the trade-skills KB
  (`references/strategies.md` / pitfall 24). `score` counts only the `yes` factors, so `score ∈ 0..8` always
  holds and the `N/8` denominator is stable. The model **MUST emit all 8** — enforced structurally
  (`conviction.factors` is `min_length=8, max_length=8`; the leniency layer pads any missing canonical factor
  as `na` before validation, so strict and lenient providers both land on exactly 8). The 8, with how each
  maps to our UW + massive data:
  1. 3+ independent channel checks aligned bullish — **permanent `na`** (Funda-only, §5.3).
  2. Sector / thematic narrative actively re-rating — sourceable (news/flow context; else `na`).
  3. Stock down >20% from recent high (de-risked setup) — sourceable (`tape` drawdown-from-6M-high).
  4. Past 4 quarters: ≥3 positive earnings reactions — sourceable (earnings history).
  5. NEW information likely to be disclosed (new customer tier / product class / guide raise / M&A) —
     mostly **`na`** (whisper/channel territory; reasoning-only).
  6. Net options flow back-month bullish (call-premium dominance, 5-day rolling) — sourceable (`flow_series`).
  7. Short interest >10% (squeeze potential) — sourceable (`positioning` SI% float).
  8. Implied move materially below recent realized average — sourceable (`vol` IV-vs-RV).
  Factors 1 and 5 are structurally unsourceable under the UW+massive scope → the realistic ceiling is ≈ 6/8.
  This is honest-by-construction, not a defect: an unsourceable factor is `na`, never fabricated into a `yes`.
- **Asymmetry threshold (na-aware):** `three_axis.asymmetry.rule_on` ⟺ `conviction.score ≥ 4` (absolute, of
  8), **enforced in both directions by the validator** (`rule_on` with `score < 4` errors; `score ≥ 4` with
  `rule_on = false` errors). If fewer than 4 *non-`na`* factors exist, conviction is **indeterminate** →
  `rule_on = false` plus an explicit "insufficient data" note in `conviction.prose` (and `score < 4`,
  consistent with `rule_on = false`) — never a silently-low score that quietly disables the asymmetry rule.
- **Cross-provider consensus (framework):** the consensus banner compares **only** `header.position_type` and
  `best_setup.structure` *family* (directional-defined-risk vs pin/vega vs stand_aside) across providers —
  never the prose. **Computed client-side in `FrameworkTab`** over the providers (Codex / Claude / DeepSeek)
  that carry a non-null `framework{}` (≥2 required, else "single provider") — separate from the existing
  server-side `provider_consensus` on `/latest`, which stays a deliberately **2-way codex-vs-claude**
  comparison (`_compute_provider_consensus`, DeepSeek excluded by design). The framework banner therefore
  needs **no `/latest` contract change**.
- **stand_aside precedence:** `catalyst.handling == "stand_aside"` ⟹ `best_setup.structure == "stand_aside"`,
  **and** `header.position_type == "stand_aside"` ⟺ `best_setup.structure == "stand_aside"` (both enforced by
  the validator). `position_type` is the overall stance; `catalyst.handling` is the earnings-specific
  entry-timing action; the two never disagree on whether a trade is entered now.
- **Persistence (verified on `origin/main`):** the structured `TradeInsightAiOutcome` is stored in
  `trade_insight_ai_analyses.outcome_jsonb` — a **JSONB** column (created in
  `017_trade_insights_ai_analysis.sql`; written via `Jsonb(outcome)` in `storage/trade_insights_ai.py` at the
  `outcome_jsonb = %s` upsert; read as `outcome_jsonb->'headline'->>…` by the priors view `055`). Since
  `framework{}` is additive to that model, it serializes into `outcome_jsonb` with **no new migration**.
  (`raw_outcome_jsonb` from `056` is a *separate* JSONB column holding rejected raw payloads for audit — not
  where the structured framework lives.) Add a `067_…` migration only if a framework field must become its own
  queryable column.
- After the model change: regenerate OpenAPI snapshot + `cd web && npm run gen:types`; run
  `tests/unit/test_models_exports.py` and the field-surface/OpenAPI checks.

## 9. Frontend — the Framework view

- **`web/components/stock/tabs/TradePlanTab.tsx`** → reworked into the Framework tab as a **client island**
  (rename to `FrameworkTab.tsx`; rewire the `tab="trade-plan"` route in
  `web/app/stock/[ticker]/[tab]/page.tsx`). It no longer reads `report.trade_plan`.
- **Per-provider polling + toggle:** reuse `web/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling.ts`
  and a `[Codex] [Claude] [DeepSeek]` toggle (like the AI panel); render the polled `framework{}` per provider,
  with a cross-provider consensus banner on top.
- **Per-provider state handling:** a provider may be `queued` / `running` / `failed` / `stale`, or carry a
  null `framework{}` (a legacy row, or a provider that errored — e.g. a DeepSeek API outage). The tab renders
  that state explicitly (badge + reason), never a blank. The consensus banner requires ≥2 providers with a
  `framework{}`; with fewer it shows "single provider," not consensus.
- **Layout:** collapsible decision-stack sections (reuse the fold pattern in
  `web/components/regime/vcg/VcgStressHistorySection.tsx`) — each section = one-line glance header + expandable
  prose. Order mirrors the output spine. The gamma section draws the flip marker + call/put-wall markers
  (reuse `web/lib/svgChart.ts`). **Data source:** the `framework.gamma` block carries only the three strike
  points (`flip_strike`, `call_wall`, `put_wall`), not a full curve series. To draw the underlying GEX curve,
  the RSC parent (`page.tsx`, which already loads `SingleStockReport`) passes its existing GEX-profile series
  to `FrameworkTab` as an **optional read-only `gexCurve` prop** (static backdrop only — the framework markers
  still come from the polled `framework{}`). When the prop is absent, the gamma section renders the three
  framework markers on a bare price axis (no curve) rather than fabricating a series. Conviction renders as `●●●●○○○○ N/8` with per-factor tooltips
  (`yes`/`no`/`na`). Best-setup is the visual climax (structure, legs, cost, max-risk, invalidation).
- Argon dark theme + mono section labels (existing `sectionHeading` style) + `MetricGrid`/`DataTable` primitives.
- **DeepSeek `reasoning_content`:** surfaced as an optional collapsible "model reasoning" disclosure beneath
  `bottom_line`, **off by default** (the framework prose is the primary artifact; the reasoning trace is
  opt-in). Codex/Claude rows simply omit it.
- After the contract change, run `cd web && npm run gen:types` so `web/lib/types.ts` carries `framework{}`
  (cross-ref §8/§11).

## 10. Removal of the deterministic trade plan

- **Delete** `trade_plan` (legs/max-loss) producers: `_build_trade_plan` and `build_trade_plan_for_report` in
  `reports/single_stock.py`, the `TradePlan`/`TradePlanLeg` models (`models/stock.py`), and the `trade_plan`
  field on the single-stock response. This is a **deliberate, scoped API contract change** (regenerate OpenAPI
  + types).
- **Keep** `setup` / `SetupClassification` (`models/matrix.py`) — it is consumed by the watchlist tiles
  (`web/components/watchlist/{TickerCard,FilterBar}.tsx`), scanner candidate cards
  (`web/components/scanner/CandidateCard.tsx`), and the watchlist landing (`web/app/page.tsx`). The Framework
  may *read* `setup` as one input, but does not own it.
- Blast radius (verified): only `TradePlanTab.tsx` consumes `report.trade_plan` on the frontend; removal is
  clean.
- **Test/contract blast radius (verified on `origin/main` — update these before deleting):**
  `tests/unit/test_models_exports.py` (lines 33-34: `"TradePlan"`, `"TradePlanLeg"` in the expected
  `models.__all__` surface) → remove those two entries; `tests/unit/test_report_assembly.py:328`
  (`assert report.trade_plan is None`) → remove/update; `tests/integration/api/openapi.snapshot.json` (7 refs:
  the `trade_plan` field + `TradePlan`/`TradePlanLeg` component schemas) → regenerate after the model removal.
  Confirm no other response model embeds `TradePlan`, then regenerate the OpenAPI snapshot + `web/lib/types.ts`
  (the snapshot test fails until refreshed).

## 11. Testing

- **Unit:** prompt assembly includes the KB (`tests/unit/reports/test_trade_insights_ai_prompt_assembly.py`);
  `framework{}` schema validation; leniency coercion of framework drift; the new framework validator rule
  (conviction bounds, defined-risk enforcement, best_setup↔candidates linkage); fundamentals/positioning
  parsers.
- **Integration (pytest-postgresql, no mocked DB):** worker produces `framework{}` for all three providers;
  fundamentals/positioning storage round-trips; API `/latest` returns `framework{}` per provider;
  provider CHECK still passes.
- **Web:** vitest for `FrameworkTab` rendering (each section, `na` handling, consensus banner); Playwright for
  tab interaction (screenshots under `output/playwright/`).
- **Real-path smoke (per standing rule):** API → DB → worker → DB → UI. No `/tmp` side-channel scripts.
- After model/API changes: OpenAPI snapshot + `npm run gen:types` + `test_models_exports.py`.

## 12. Sequencing & branch

1. ✅ Done in pre-flight: worktree `feat/trade-framework-view` is based on `origin/main` (`95d370e`, DeepSeek
   merged); highest migration confirmed `064` → new start `065`.
2. Milestone order (commit each after its verification, per big-project rule) — the implementation plan runs
   **contract-first**: output contract → validator/leniency → prompt KB + decision stack → data layer (T1 UW
   `065`, T2 massive `066`) → payload enrichment → frontend Framework view → delete deterministic trade plan →
   integration/tests. The contract is fixed first so every downstream test asserts a stable `framework{}`
   shape; the data layer is contract-independent and could equally run first.
3. Open a PR before merging to main (never push to main directly). No `Co-Authored-By` trailer.

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Prompt ~2× larger (full KB) → token cost / latency | Accepted (user chose full library). KB in its own module; monitor `TRADE_INSIGHTS_AI_*` timeouts; output cap 256 KB is ample. |
| Prompt (KB + enriched payload) exceeds a provider's **context window** | Verify total prompt size vs each provider's context limit at plan time (Codex / Claude / DeepSeek). KB is fixed-size, payload is bounded — assert headroom; if tight, trim payload verbosity before touching the KB. |
| Assertive tone → overconfident/fabricated claims | `conviction.factors[].status` hard `na`; validator enforces; prompt guardrail; no-fabrication is a project rule. |
| massive fundamentals not yet backfilled for a ticker | Payload marks `na`; framework degrades gracefully; nightly backfill fills over time. |
| Three runners drift on the new fields | Strict schema (Codex) + leniency coercion (Claude/DeepSeek) + framework validator; normalize in validator, not prompt. |
| Module-size / contract-identity regressions | KB split module; `framework{}` additive in `trade_insights_ai_parts/`; preserve `__all__`/`__module__`; run export + OpenAPI + field-surface checks. |
| Worker→source rate (UW QPS scales with worker count) | T1/T2 refresh on slow cadences (nightly fundamentals; positioning daily-ish), not the 1s rescan loop. |

## 14. Success criteria

- The trade-plan tab renders a per-provider (`[Codex][Claude][DeepSeek]`) Framework decision stack with prose
  + glance headers, ending in a single decisive `best_setup` — either a defined-risk structure with a
  counterfactual `why_not_alternatives`, or an explicit `stand_aside` with its re-engage trigger.
- Conviction shows `N/8` with a `yes|no|na` factor ledger; absent inputs are `na`, never fabricated.
- Earnings handling honors swing-default / LEAPS-aware.
- T1 (UW) + T2 (massive) inputs are fetched, persisted, and visible in the payload; fundamentals degrade to
  `na` when absent.
- The deterministic `trade_plan` is gone; `setup` still powers the watchlist/scanner.
- All tests pass; OpenAPI snapshot + `web/lib/types.ts` regenerated; PR opened (not pushed to main).

## 15. Out-of-scope note (deferred)

- Forward consensus estimates via massive Benzinga add-on or UW Advanced+ tier (paid) — revisit if the
  forward-estimate conviction factor proves worth it.
- Level-2 order book imbalance — not feasible on 15-min-delayed data; permanent reasoning-only.
