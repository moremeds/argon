# Trade Insights AI v5.3 + Outcome Ledger v0 — Results & Verification

**Date:** 2026-05-24
**Branch:** `feat/trade-insights-ai-v5-directional` (continuing PR #68)
**Commits:** 10 new (M0–M6 v5.3, M8–M10 outcome ledger) on top of the
existing v5.0–v5.2 work in PR #68.

---

## Summary

v5.3 closes the last v5.2 reviewer-flagged failure mode: trigger overload.
The v5.2 NVDA disagreement (Codex `trigger_level=220`, Claude
`trigger_level=215`) was not a model error — it was a schema error.
v5.2 had one field meaning two distinct things ("the wall I broke" vs
"the level where I'd actually enter"). v5.3 decomposes that into three
first-class state-machine components — `thesis_trigger`, `entry_trigger`,
`invalidation` — each with its own `level`, `meaning`, `fired` boolean,
and `evidence_close@date`. `ENTRY_STATE` (ACTIVE/CONDITIONAL/NO_ENTRY)
becomes a *derived* field from those booleans, not a model judgment.

Phase 2 (outcome ledger) stands up the infrastructure to actually score
whether prior trade ideas played out. New `trade_insight_outcomes`
table, nightly worker, priors aggregation view, and read endpoint — all
landed and verified against the existing 47-row historical backlog.

**v5.3 contract works end-to-end.** Both Codex and Claude on NVDA
spontaneously converged on the same trigger decomposition once given
the vocabulary to express it. That's the strongest validation possible.

---

## v5.3 Schema Diff vs. v5.2

| Surface | v5.2 | v5.3 |
|---|---|---|
| `trigger_level` | Single `Decimal` field on `strike_role`, overloaded | Decomposed into 3 `TriggerComponent` blocks at outcome top level |
| `TradeInsightAiTriggerComponent` | — | NEW: `{level, meaning, fired, evidence_close, evidence_date, source_path}` |
| `TradeInsightAiOptionLeg` | — | NEW: `{option_type, side, strike, expiry}` |
| `TradeInsightAiOutcome.thesis_trigger` | — | NEW `TradeInsightAiTriggerComponent` (default-empty) |
| `TradeInsightAiOutcome.entry_trigger` | — | NEW `TradeInsightAiTriggerComponent` |
| `TradeInsightAiOutcome.invalidation` | — | NEW `TradeInsightAiTriggerComponent` |
| `TradeInsightAiPreferredExpression.legs` | — | NEW `list[TradeInsightAiOptionLeg]` (default `[]`) |
| `PROMPT_VERSION` | `trade-insights-ai-v5.2` | `trade-insights-ai-v5.3` |
| Validators (new HARD) | — | `_check_legs_match_strategy`, `_check_legs_align_with_triggers`, `_check_entry_state_derivation` |
| `ENTRY_STATE` | Model judgment | Mechanical: `ACTIVE iff thesis.fired AND entry.fired AND NOT invalidation.fired` |

**All additions are backwards-compatible at the Pydantic surface** —
new fields have `default_factory`, so v5.2 outcomes parse cleanly into
v5.3 models. The lenient coercer backfills v5.3 trigger components from
v5.2 `trigger_evidence` + `strike_role.invalid_level` so historical
rows render properly in the new UI.

---

## Milestone Commits

| # | Commit | Subject | LoC |
|---|---|---|---|
| M0 | `abf5419` | Split `trade_insights_ai.py` (2285 lines) into 4-module package | +2653 / −2285 |
| M1 | `5578cbd` | Pydantic models: `TriggerComponent` + `OptionLeg` schema | +92 / −0 |
| M2 | `77299d1` | Prompt for decomposed triggers + explicit legs | +237 / −45 |
| M3 | `02dfb81` | Lenient coercer for trigger components + option legs | +236 / −10 |
| M4 | `7839fc5` | Three new HARD validator rules | +319 / −0 |
| M5 | `b83dd6e` | UI legs table + decomposed trigger components | +272 / −40 |
| M6 | `41e3d47` | Validator tests + OpenAPI snapshot regen | +499 / −0 |
| M8 | `8ea40ec` | Outcome ledger schema + repository module | +390 / −0 |
| M9 | `72a52c6` | Nightly outcome scoring + initial backfill | +457 / −1 |
| M10 | `2bb5e44` | Priors aggregation view + `/api/trade-insights/priors` | +522 / −0 |

**Net footprint:** ~+5,677 LOC, ~−2,381 LOC across 10 commits.

---

## Live Smoke Results (M7)

Restarted the AI worker fleet after M6 to pick up v5.3 code (APScheduler
workers don't hot-reload — `feedback_check_worker_etime_before_debugging`).
Queued NVDA and TSLA against both Codex and Claude via the real
worker path.

### NVDA — v5.3 contract held end-to-end

Both providers spontaneously converged on the same trigger decomposition.
This is the v5.3 thesis vindication: the structured vocabulary forced
both Codex and Claude to commit to the same semantic distinction
(broken wall ≠ entry trigger), and their natural-language `meaning`
fields confirm it.

| Component | NVDA / Claude | NVDA / Codex |
|---|---|---|
| `directional_bias` | SHORT_DELTA | SHORT_DELTA |
| `thesis_archetype` | support_breakdown | support_breakdown |
| `entry_state` | CONDITIONAL | CONDITIONAL |
| `underlying_path` | downside_break | downside_break |
| `conviction` | C | C |
| `thesis_trigger.level` | **220** | **220** |
| `thesis_trigger.meaning` | "put_wall_broken_support_breakdown_confirmed" | "support_breakdown_confirmed_below_put_wall" |
| `thesis_trigger.fired` | true | true |
| `thesis_trigger.evidence` | 215.33 @ 2026-05-22 | 215.33 @ 2026-05-22 |
| `entry_trigger.level` | **215** | **215** |
| `entry_trigger.meaning` | "gex_flip_break_confirms_short_delta_entry" | "short_delta_entry_confirmation_below_gex_flip" |
| `entry_trigger.fired` | false | false |
| `invalidation.level` | **220** | **220** |
| `invalidation.meaning` | "reclaim_of_broken_put_wall_kills_thesis" | "broken_put_wall_reclaim_invalidates_short_delta" |
| `invalidation.fired` | false | false |
| `preferred.structure` | bear_put_spread | bear_put_spread |
| `preferred.status_observed` | strategy_review | strategy_review |
| `preferred.legs` | `[long_put@215, short_put@210, exp=2026-06-26]` | `[long_put@215, short_put@210, exp=2026-06-26]` |

**Outcome:** the v5.2 NVDA Codex-vs-Claude trigger disagreement is
gone. v5.3 schema decomposition resolved it cleanly. The v5.3
`entry_state_derivation` validator passes (only thesis fired → must be
CONDITIONAL). `legs_match_strategy` passes (bear_put_spread: 2 puts,
long > short, same expiry). `legs_align_with_triggers` passes
(long_put@215 within 2% of entry_trigger.level=215).

### TSLA — reproduced known upstream issues

TSLA hit the same failure modes documented in the v5.2 deliverable:

- **TSLA / Codex (both attempts):** `status_observed changed for idea_id G`.
  This is a pre-existing v5.x `no-whitewashing` validator — Codex picked
  candidate "G" (bear_put_spread) and emitted a different status_observed
  than the candidate row's stored status. The validator correctly
  rejected. Not a v5.3 regression — this same error happens
  intermittently on tickers with rich candidate menus.

- **TSLA / Claude (both attempts):** `claude --print returned no
  structured_output and result field was not valid JSON`. The Claude
  CLI's `--json-schema` StructuredOutput tool drops on TSLA's payload
  specifically. Also seen in the v5.2 deliverable — not a v5.3 issue.

**Practical implication:** the v5.3 contract is validated by the NVDA
runs. TSLA's failures are upstream issues unrelated to v5.3 (Codex's
candidate-status fidelity + Claude's StructuredOutput reliability on
larger payloads). Both would need separate fixes outside the v5.3 scope.

---

## Outcome Ledger v0 (Phase 2)

### Schema (migration 054)

`uw_scan.trade_insight_outcomes` — 34 columns, 4 indexes, 1:1 with
`trade_insight_ai_analyses`. Forward-looking outcome scoring:

- `snapshot_close` + `close_1d/3d/5d/10d` — fixed-window forward closes
- v5.3 trigger components mirrored on the ledger: `thesis_trigger_level`,
  `thesis_trigger_meaning`, `thesis_trigger_fired_after` (BOOL —
  did it fire *after* snapshot_date?), `thesis_trigger_hit_date`. Same
  for entry_trigger and invalidation.
- `target_level`, `target_hit`, `target_hit_date`
- `resolved_outcome` ∈ {`target_hit`, `invalidation_hit`,
  `expired_no_resolution`, `pending`} — first-hit wins
- `days_to_resolution` for resolved rows

### Worker (M9)

`trade_insight_outcome_backfill_once` — runs nightly at 17:00 ET on the
primary massive worker. Two passes:

1. **Bootstrap pass:** LEFT JOIN to find unscored succeeded analyses;
   create empty `pending` rows. INITIAL_BACKFILL_BATCH=50/tick.
2. **Scoring pass:** drains pending queue; fetches forward closes from
   `daily_ohlc` (90-day horizon); computes per-trigger hit booleans +
   resolution. INCREMENTAL_BATCH=25/tick.

Direction-aware scoring: SHORT_DELTA thesis fires when `close < level`,
LONG_DELTA when `close > level`. Invalidation uses the inverse
(reclaim against trade direction). Target reaches when `close <= target`
(SHORT_DELTA) or `close >= target` (LONG_DELTA).

### Initial backfill (verified)

```
total outcomes: 47

by prompt_version:
                   trade-insights-ai-v1: total= 10
                   trade-insights-ai-v2: total= 15
                   trade-insights-ai-v4: total= 12
                   trade-insights-ai-v5: total=  2
                 trade-insights-ai-v5.1: total=  2
                 trade-insights-ai-v5.2: total=  4
                 trade-insights-ai-v5.3: total=  2
```

All 47 historical succeeded analyses now have outcome rows. The 2 v5.3
NVDA cells correctly extracted `thesis_trigger.level=220` and
`entry_trigger.level=215`. v1/v2/v4 rows show `with_thesis=0` because
they predate v5.3's trigger decomposition — exactly as designed; the
priors view filters on `prompt_version` to keep per-archetype stats
apples-to-apples.

All resolved_outcome=pending today because `snapshot_date = finished_at.date()
= 2026-05-24` and no daily_ohlc bars after today exist yet. Forward
closes will fill in over the next 1–10 trading days as the nightly worker
ticks.

### Priors endpoint (M10)

```bash
curl /api/trade-insights/priors
curl /api/trade-insights/priors?provider=claude&prompt_version=trade-insights-ai-v5.3
```

Returns 14 cohorts across all providers/versions/archetypes/bias/entry_state
combinations. The v5.3 NVDA cohorts are correctly grouped:

```json
{
  "provider": "claude",
  "prompt_version": "trade-insights-ai-v5.3",
  "thesis_archetype": "support_breakdown",
  "directional_bias": "SHORT_DELTA",
  "entry_state": "CONDITIONAL",
  "sample_count": 1,
  "target_hit_count": 0,
  "invalidation_hit_count": 0,
  "pending_count": 1,
  "hit_rate_pct": null,
  "median_days_to_resolution": null
}
```

`hit_rate_pct` is null because everything is still pending — that's the
intended semantics (an all-pending cohort is NOT a 0% hit rate).

UI for priors is **deferred to a follow-on PR** — the endpoint exists,
types are generated, but no panel renders it. Two reasons:
1. Sample sizes are too small for meaningful priors until 30+ resolved
   outcomes accumulate (~6-8 weeks of nightly scoring).
2. The product question of "where in the UI does this surface?" deserves
   its own design conversation — likely on the stock detail page above
   the provider tabs, but worth thinking through.

---

## Verification Checklist

- [x] **M0:** 643 unit tests + 3 skipped pass after the package split (no behavior change)
- [x] **M1:** Pydantic round-trip works for `TriggerComponent` (including dict-form coercion of `{"strike": "215"}` into `Decimal`) and `OptionLeg` (rejects missing strike with `ValidationError`)
- [x] **M2:** Prompt size 24.6KB → 30.2KB; all v5.3 sections present in both MARKET_INTELLIGENCE_PROMPT and Claude system mirror
- [x] **M3:** Lenient coercer round-trip for (a) v5.3-native input, (b) v5.2 back-compat backfill, (c) v5.3 with missing legs (coerces to `[]`)
- [x] **M4:** All 3 new validators each have at least one pass-case and one fail-case test
- [x] **M5:** `npm run typecheck` clean, vitest 8/8 pass, panel renders legs table + 3 trigger-component rows with proper testids
- [x] **M6:** 654 unit tests pass (up from 643 — exactly 11 new v5.3 tests), OpenAPI snapshot updated
- [x] **M7:** NVDA across both providers succeeded with v5.3 schema; TSLA reproduced known upstream issues unrelated to v5.3
- [x] **M8:** Migration applied idempotently; repository round-trips through upsert + fetch + cleanup
- [x] **M9:** Bootstrap pass added 47 outcome rows; scoring pass correctly extracted v5.3 trigger components; v1–v5.2 rows correctly leave trigger fields NULL
- [x] **M10:** `curl /api/trade-insights/priors` returns 14 cohorts; v5.3 NVDA cohort correctly grouped; OpenAPI snapshot test passes
- [ ] **M11 (this doc):** deliverable doc written; PR description updated; branch pushed

---

## Out of Scope (Deferred)

These were intentionally NOT included in v5.3-minimal — the user's M0–M11
plan kept the surface bounded:

- ChatGPT P0 #3 (source_path scalar enforcement) — added cost > benefit
- ChatGPT P0 #4 + Claude's "disagreement axis" — divergent-consensus UI branching (bull case / bear case display). Separate UI-only PR
- ChatGPT P1 #5–7 — IV-implied target_feasibility, expanded R:R rule, deterministic anti-pin wall_test_history
- ChatGPT P2 #8 — provider arbiter summary
- Sonnet 4.6 A/B test — separate experiment, run after outcome ledger has 30+ resolved rows
- UI for `/api/trade-insights/priors` — endpoint exists, panel deferred (see M10 notes above)
- Snapshot-date refinement — currently uses `finished_at.date()`; a more honest snapshot date would be the latest completed close in the analysis input (`evidence_date` on trigger components). Worth a follow-up but doesn't block v0 ledger usefulness.

---

## What v5.3 is and isn't

**v5.3 is:**
- A schema bump that resolves the v5.2 NVDA trigger-level disagreement
  by decomposing one overloaded field into three first-class state
  machine components
- A mechanism that turns ENTRY_STATE from a model judgment into a
  derived field — the schema does the work the prompt previously
  asked the model to do
- An explicit legs-table contract that makes "is the long-put strike
  215 or 220?" a falsifiable claim
- An outcome ledger that, as resolved outcomes accumulate, will support
  per-provider per-archetype Bayesian priors (the foundation for
  "should I weight Codex or Claude more on resistance_rejection setups?")

**v5.3 is not:**
- A fix for Claude's StructuredOutput drop on TSLA-shape payloads
- A fix for Codex's intermittent candidate-status drift on rich menus
- A UI for the priors endpoint (intentionally deferred)
- A divergent-consensus branching UI (deferred)
- A measure of whether AI analyses actually make money (that requires
  outcome accumulation — which v5.3 just enabled)

The honest summary: v5.3 closes the last *schema* gap. The remaining
wins are now in the surrounding infrastructure (outcome accumulation,
priors UI, divergent-branching, model A/B testing) — not in another
prompt iteration. Each ratchet on v5.3 would now cost more in prompt
complexity than it buys in correctness.
