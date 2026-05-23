# Trade Insights AI v5.3 + Outcome Ledger v0 Implementation Plan

> **For agentic workers:** Inline execution by Claude on `feat/trade-insights-ai-v5-directional`. Each milestone (M0–M11) closes with a verifiable commit. Continuation of PR #68.

**Goal:** Decompose the overloaded `trigger_level` field into three first-class state-machine components (`thesis_trigger`, `entry_trigger`, `invalidation`), require explicit option `legs[]` on every preferred_expression, and stand up an outcome ledger that scores whether each prior AI analysis actually played out — enabling per-provider per-archetype Bayesian priors.

**Architecture:** Two-phase, single PR.
- **Phase 1 (M0–M7):** Schema bump v5.2 → v5.3. ENTRY_STATE stops being a model judgment and becomes mechanically derived from `thesis_trigger.fired AND entry_trigger.fired`. The schema does the work the prompt previously had to.
- **Phase 2 (M8–M10):** New `trade_insight_outcomes` table + nightly worker that fetches forward-looking OHLC from massive (with market-warehouse fallback), computes whether each trigger/invalidation/target actually fired, and aggregates into a priors view. No UI surface yet — just infrastructure that future PRs can read.

**Tech stack:** Python 3.13 (uv), Pydantic v2, psycopg 3, APScheduler 3, FastAPI, Next.js 16 + React 19, Postgres 16, Codex CLI + Claude CLI (subprocess), Playwright (verification).

**Why this work now:** ChatGPT reviewer + Claude reviewer converged on the same diagnosis after v5.2 NVDA + TSLA runs — `trigger_level` is overloaded across "thesis confirmed" vs "entry confirmed" semantics, which is why NVDA Codex (220) and Claude (215) disagree on ENTRY_STATE even though they agree on direction and archetype. Decomposing this is a data-model fix, not a prompt fix. Once `thesis_trigger ≠ entry_trigger`, ACTIVE/CONDITIONAL becomes mechanical. Without an outcome ledger, the provider_consensus chip from v5.2 is structural-agreement only, not predictive-agreement.

---

## File Structure

### New / restructured (Phase 1)

```
src/uw_scan/reports/
  trade_insights_ai/                  # NEW package — M0 split
    __init__.py                       # re-exports (PROMPT_VERSION, render fns, validators)
    prompt.py                         # MARKET_INTELLIGENCE_PROMPT, PROMPT_VERSION, alias dicts
    validators.py                     # all _check_* HARD validators
    orchestration.py                  # build_prompt_payload, render_markdown, schema generators
  trade_insights_ai_lenient.py        # still single-file but extends — already at 1280 lines, hold for now

src/uw_scan/models/
  trade_insights_ai.py                # ADD TradeInsightAiTriggerComponent, TradeInsightAiOptionLeg
                                      # RESTRUCTURE TradeInsightAiOutcome (thesis_trigger / entry_trigger / invalidation)
                                      # ADD legs[] to TradeInsightAiPreferredExpression
```

### New (Phase 2)

```
sql/migrations/
  <next_seq>_trade_insight_outcomes.sql             # idempotent table + indexes + view

src/uw_scan/storage/
  trade_insight_outcomes_repository.py              # NEW domain module (NEVER appended to repository.py)

src/uw_scan/worker/jobs/
  trade_insight_outcome_backfill.py                 # nightly job + initial-backfill entrypoint

src/uw_scan/worker/scheduler.py                    # register new job (5pm ET nightly)

src/uw_scan/api/routers/
  trade_insights.py                                 # add /api/trade-insights/priors endpoint (reads view)
```

---

## Critical Decision: Trigger Component Semantics

The v5.3 contract treats every meaningful price level as a `TradeInsightAiTriggerComponent`:

```python
class TradeInsightAiTriggerComponent(BaseModel):
    level: Decimal                                    # the price line
    meaning: str                                      # what this level represents (free-form short label)
    fired: bool                                       # has price crossed this level in the relevant direction?
    evidence_close: Decimal | None = None             # the daily close that proved fired=true
    evidence_date: date | None = None                 # the date of that close
    source_path: str | None = None                    # for audit — JSON pointer into the input snapshot
```

**Three required components per outcome (when status is candidate / needs_check / strategy_review):**

| Component | Meaning examples | When fired |
|-----------|------------------|------------|
| `thesis_trigger` | `"support_breakdown_confirmed"`, `"resistance_rejection_confirmed"`, `"breakout_confirmed"` | When the spatial archetype has been validated by price action |
| `entry_trigger` | `"continuation_entry"`, `"flip_trigger_above"`, `"reclaim_below"` | When the actual planned trade entry condition is met |
| `invalidation` | `"reclaim_broken_support"`, `"breakdown_below_breakout_base"` | If price crosses this against the trade, thesis is invalid |

**Mechanical ENTRY_STATE derivation (replaces the v5.2 model-judgment rule):**

| thesis_trigger.fired | entry_trigger.fired | invalidation.fired | ENTRY_STATE |
|---|---|---|---|
| true | true | false | `ACTIVE` |
| true | false | false | `CONDITIONAL` |
| false | false | false | `NEEDS_CHECK` or `NO_ENTRY` (model picks based on data quality vs. opportunity quality) |
| any | any | true | `NO_ENTRY` (thesis invalidated) |

Both components may share the same `level` (e.g. NVDA Codex read where 220 is both the broken wall AND the entry confirmation), but the `meaning` field must differ, and the `fired` booleans are evaluated independently against their own evidence rules. The disagreement we saw in v5.2 (Codex: trigger 220, Claude: trigger 215) becomes representable: both providers can agree on `thesis_trigger=220` while disagreeing on whether `entry_trigger=215` or `entry_trigger=220`.

---

## Critical Decision: Explicit Option Legs

Every `preferred_expression` of a strategy that has structure (debit/credit spread, butterfly, etc.) must emit:

```python
class TradeInsightAiOptionLeg(BaseModel):
    option_type: Literal["call", "put"]
    side: Literal["long", "short"]
    strike: Decimal
    expiry: date

class TradeInsightAiPreferredExpression(BaseModel):
    # existing fields preserved
    legs: list[TradeInsightAiOptionLeg] = Field(default_factory=list)
```

**Strategy-structure validator (`_check_legs_match_strategy`):**

| Strategy family | Legs required |
|---|---|
| `bear_put_spread` | exactly 2: 1 long put + 1 short put, long.strike > short.strike, same expiry |
| `bull_call_spread` | exactly 2: 1 long call + 1 short call, long.strike < short.strike, same expiry |
| `bear_call_spread` (credit) | exactly 2: 1 short call + 1 long call, short.strike < long.strike, same expiry, defined-risk only |
| `bull_put_spread` (credit) | exactly 2: 1 short put + 1 long put, short.strike > long.strike, same expiry |
| `long_call` / `long_put` | exactly 1 |
| `strategy_review` / `no_entry` | legs may be empty |

**No naked shorts** — credit-spread families always have the long protective leg present (CLAUDE.md rule).

**`_check_legs_align_with_triggers`:** for any spread, the long leg's strike must be within 2% of `entry_trigger.level` OR `thesis_trigger.level`. This catches the v5.2 gap where Codex emitted `trigger_level=220` while the spread (had it been legs-explicit) would have been 215/210 — making `long_leg_role=trigger_level` a falsifiable claim.

---

## Outcome Ledger Schema (Phase 2)

```sql
CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_outcomes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id     uuid NOT NULL REFERENCES uw_scan.trade_insight_ai_analyses(id) ON DELETE CASCADE,
    ticker          text NOT NULL,
    provider        text NOT NULL,                    -- 'codex' | 'claude'
    prompt_version  text NOT NULL,
    snapshot_date   date NOT NULL,                    -- the trading day the analysis was made for
    snapshot_close  numeric,                          -- the close on snapshot_date (None for intraday-only snapshots)

    -- Fixed-window forward closes (chosen per AskUserQuestion answer)
    close_1d        numeric, close_1d_date date,
    close_3d        numeric, close_3d_date date,
    close_5d        numeric, close_5d_date date,
    close_10d       numeric, close_10d_date date,

    -- Trigger-component resolutions (only populated for v5.3+ rows that have these fields)
    thesis_trigger_level       numeric,
    thesis_trigger_meaning     text,
    thesis_trigger_fired_after bool,                  -- did it fire AFTER snapshot_date?
    thesis_trigger_hit_date    date,
    entry_trigger_level        numeric,
    entry_trigger_meaning      text,
    entry_trigger_fired_after  bool,
    entry_trigger_hit_date     date,
    invalidation_level         numeric,
    invalidation_hit           bool,
    invalidation_hit_date      date,
    target_level               numeric,
    target_hit                 bool,
    target_hit_date            date,

    -- Resolution summary
    days_to_resolution         int,
    resolved_outcome           text,                  -- 'target_hit' | 'invalidation_hit' | 'expired_no_resolution' | 'pending'
    notes                      text,

    last_evaluated_at          timestamptz NOT NULL DEFAULT NOW(),
    created_at                 timestamptz NOT NULL DEFAULT NOW(),

    UNIQUE (analysis_id)
);

CREATE INDEX IF NOT EXISTS trade_insight_outcomes_provider_archetype_idx
    ON uw_scan.trade_insight_outcomes (provider, prompt_version);
CREATE INDEX IF NOT EXISTS trade_insight_outcomes_ticker_idx
    ON uw_scan.trade_insight_outcomes (ticker, snapshot_date);
```

**Outcome scoring rules** (applied per row by the worker):

- `thesis_trigger.fired_after = true` iff there is at least one daily close after `snapshot_date` that crosses `thesis_trigger.level` in the direction implied by `underlying_path` (below for support_breakdown, above for breakout, etc.). First such close → `thesis_trigger_hit_date`.
- `entry_trigger.fired_after` — same logic against `entry_trigger.level`.
- `invalidation_hit` — first daily close that crosses `invalidation.level` in the *opposite* direction.
- `target_hit` — first daily close that reaches `target_level` in the move direction.
- `resolved_outcome = target_hit` if target_hit_date precedes invalidation_hit_date (or invalidation never hit).
- `resolved_outcome = invalidation_hit` if invalidation_hit_date precedes target_hit_date.
- `resolved_outcome = expired_no_resolution` if `preferred_expression.expiry` (when present) has passed without target or invalidation.
- `resolved_outcome = pending` otherwise.

**Backfill scope (per AskUserQuestion answer): ALL historical rows.** For v4 rows that lack thesis_trigger/entry_trigger/invalidation, only the four fixed-window closes are populated; trigger-component fields stay NULL. Per-archetype priors will naturally restrict to v5+ rows once we add an archetype filter in the view.

---

## Milestones

| # | Subject | LoC est. | Commit message prefix |
|---|---------|---------|---------|
| **M0** | Split `reports/trade_insights_ai.py` (2285 → ~600+700+500 in package) | ±0 net (move only) | `refactor(ai): split trade_insights_ai into prompt/validators/orchestration` |
| **M1** | Pydantic models: TradeInsightAiTriggerComponent + TradeInsightAiOptionLeg + outcome restructure + version bump | +180 -40 | `feat(ai): M1 v5.3 — trigger components + option legs schema` |
| **M2** | Prompt v5.3: trigger decomposition + legs requirement + mechanical ENTRY_STATE | +260 -120 | `feat(ai): M2 v5.3 — prompt for decomposed triggers + explicit legs` |
| **M3** | Lenient coercer: back-compat (old trigger_level → thesis_trigger) + new shape coercion | +220 | `feat(ai): M3 v5.3 — lenient coercer for v5.3 + v5.2 back-compat` |
| **M4** | HARD validators: legs-strategy-match + entry-state-derivation + legs-align-triggers | +180 | `feat(ai): M4 v5.3 — three new deterministic validator rules` |
| **M5** | UI: legs table + decomposed trigger evidence card + version banner | +240 -60 (TSX) | `feat(ai): M5 v5.3 — UI legs table + decomposed trigger tiles` |
| **M6** | Tests (pytest + vitest) + OpenAPI snapshot + web types regen | +480 -90 | `test(ai): M6 v5.3 — validator + lenient + UI tests + types regen` |
| **M7** | Live smoke through real worker path: NVDA + TSLA both providers | doc only | (no commit — produces the screenshots that go into M11) |
| **M8** | Migration + outcome repository module | +160 (sql) +280 (py) | `feat(outcomes): M8 — schema + repository for trade_insight_outcomes` |
| **M9** | Nightly worker job + initial all-rows backfill | +320 | `feat(outcomes): M9 — nightly outcome scoring + initial backfill` |
| **M10** | Priors aggregation view + read endpoint | +120 | `feat(outcomes): M10 — priors view + /api/trade-insights/priors` |
| **M11** | Deliverable doc + PR description update + `git push` | doc only | `docs(ai): v5.3 + outcome ledger results` |

**Total est. footprint:** ~+2,460 LOC, ~–310 LOC, 11 commits on top of the existing 22 commits on `feat/trade-insights-ai-v5-directional`.

---

## Risk Register

| Risk | Mitigation |
|---|---|
| Strict-mode JSON Schema rejects new nested object regexes (Decimal lookaround issue recurs for new models) | M7 fix from v5.2 (`_strip_openai_unsupported_patterns`) is already in place — verify it walks the new nested `TradeInsightAiTriggerComponent` and `TradeInsightAiOptionLeg` `$defs` too. Test with Codex live run in M7. |
| Backwards-compat for v5/v5.1/v5.2 rows in the lenient coercer is fragile | M3 explicitly handles old-shape input. Test fixture matrix in M6 includes one synthetic v5.2-shape outcome that gets coerced into v5.3 shape without losing trigger data. |
| OHLC source for outcome scoring — massive may not have full history for older v4 rows | Worker job falls back to market-warehouse parquet lake (per `~/clauded/.../reference_market_warehouse_lake.md`). If both miss, leave row as `resolved_outcome='pending'` with `notes='ohlc_source_unavailable'` — never silently zero. |
| Initial backfill is slow if there are hundreds of v4 rows | Backfill runs in batches of 25 with a 1-second sleep between batches; total time bounded by `(row_count / 25) * 1s + per-row OHLC fetch`. Worst case 5–10 min on initial run. |
| Mechanical ENTRY_STATE derivation may classify ambiguous data-quality cases (NEEDS_CHECK in v5.2) as CONDITIONAL incorrectly | The model still emits ENTRY_STATE; the validator only enforces *consistency* with the trigger bools when they're populated. If both trigger.fired are absent/null, NEEDS_CHECK remains valid. |
| `trade_insight_outcomes.analysis_id` FK with ON DELETE CASCADE could orphan priors if a row is purged | UNIQUE (analysis_id) constraint ensures 1:1, and the cascade is acceptable because outcome rows have no independent value without their analysis. |
| Per CLAUDE.md "No secrets to local Codex subprocesses" — the new prompt's legs section should not leak any infra/key info | Verified — prompt only contains framework rules, no env. |

---

## Verification Per Milestone

- **M0:** `uv run pytest tests/test_trade_insights_ai.py -q` passes (no behavior change); `uv run python -c "from uw_scan.reports.trade_insights_ai import PROMPT_VERSION; print(PROMPT_VERSION)"` returns the v5.2 string (still on v5.2 at this milestone).
- **M1:** Pydantic model imports succeed; `PROMPT_VERSION == "trade-insights-ai-v5.3"`; OpenAPI components include `TradeInsightAiTriggerComponent` and `TradeInsightAiOptionLeg`.
- **M2:** Prompt diff visible in `git diff M1..M2 -- src/uw_scan/reports/trade_insights_ai/prompt.py`; Claude system mirror updated; PROMPT_VERSION still v5.3.
- **M3:** Lenient coercer round-trip test passes for (a) v5.3 native shape, (b) v5.2 back-compat input, (c) v5.3 with missing legs (coerces to empty list when status is strategy_review).
- **M4:** Each new validator has at least one pass-case and one fail-case test in `tests/test_trade_insights_ai.py`.
- **M5:** `cd web && npm run test -- tradeInsightsAiAnalysisPanel` passes; Playwright snapshot of the panel renders legs table with 2 rows and 3 trigger components.
- **M6:** `uv run pytest tests/ -q` passes (full suite); `cd web && npm run gen:types && npm run test -- --run` passes; OpenAPI snapshot diff is committed.
- **M7:** Both NVDA + TSLA across Codex + Claude succeed with `prompt_version='trade-insights-ai-v5.3'`; outcome_jsonb contains `thesis_trigger` and `entry_trigger` keys; legs array non-empty for active expressions.
- **M8:** `bash scripts/migrate.sh` is idempotent (run twice, second run no-op); `\d uw_scan.trade_insight_outcomes` in psql shows the table.
- **M9:** Manual trigger of `trade_insight_outcome_backfill` populates outcomes for at least the 4 v5.2 rows; `select count(*) from uw_scan.trade_insight_outcomes` matches `select count(*) from uw_scan.trade_insight_ai_analyses where status='succeeded'`.
- **M10:** `curl http://127.0.0.1:8400/api/trade-insights/priors?provider=claude&archetype=support_breakdown` returns a non-empty JSON envelope (or empty list with sample_count=0, never 500).
- **M11:** PR description shows full v5.0–v5.3 scope; deliverable doc renders the priors snapshot table; `git push` succeeds.

---

## Out of Scope (Deferred)

- ChatGPT P0 #3 (source_path scalar enforcement) — added cost > benefit at this stage; can be a small follow-up validator.
- ChatGPT P0 #4 + Claude's "disagreement axis" — divergent-consensus UI branching (bull case / bear case display). Separate UI-only PR.
- ChatGPT P1 #5–7 — IV-implied target_feasibility, expanded R:R rule, deterministic anti-pin wall_test_history.
- ChatGPT P2 #8 — provider arbiter summary.
- Sonnet 4.6 A/B test — separate experiment, can run after outcome ledger has enough rows to evaluate.
- UI for priors — the endpoint exists in M10 but no panel renders it. Future PR.
