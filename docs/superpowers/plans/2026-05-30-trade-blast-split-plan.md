# Trade Blast Split — Quick Plan

> **For agentic workers:** milestone-level plan. Each milestone has exact files + a HARD verification gate.
> Expand any milestone into bite-sized TDD steps on request.

**Goal:** Undo the over-built coupling. Restore the proven **v5.3** prompt as the production *Trade Insights AI* card (Codex/Claude in UI, DeepSeek via CLI worker — all working), and re-home the experimental **v6.0 framework** work as a brand-new, soft-validated **`trade_blast`** prompt rendered in its own **Trade Plan** tab.

**Root cause being fixed:** commit `81cdb13` overwrote `trade-insights-ai-v5.3` *in place* with `trade-insights-ai-v6.0` (KB + framework directive) and bolted a rigid 6-invariant contract onto the shared `TradeInsightAiOutcome`. Result: real model output is rejected, **0 framework rows ever succeeded**, and the working card was degraded. Fix = split into two independent lanes.

**Decisions (locked with user 2026-05-30):**
1. **Discriminator:** add `analysis_kind` column (`'insights' | 'blast'`); fold into the unique key.
2. **Blast contract:** soft-validate, always render. Only **no-naked-shorts** stays HARD. On any other invariant miss → persist raw + render best-effort (`status='partial'`), never blank.
3. **Blast providers:** all three (codex / claude / deepseek).

**Tech stack:** Python 3.13 (uv), FastAPI + Pydantic v2, psycopg 3, APScheduler; Next.js 16 + React 19 + TS; pytest + pytest-postgresql, Vitest, Playwright. Types via `openapi-typescript` → `web/lib/types.ts`.

**Branch:** extend `feat/trade-framework-view` (per standing "extend pending PR branch" rule). Nothing is pushed yet, so history is local-only.

---

## Architecture: two lanes

| | Lane 1 — **insights** (restore) | Lane 2 — **blast** (new) |
|---|---|---|
| prompt_version | `trade-insights-ai-v5.3` | `trade-blast-v1` |
| prompt source | restore origin/main `prompt_text.py` | renamed v6.0 KB + framework directive |
| output | strategy / trigger / legs (no `framework{}`) | `framework{}` block, soft-validated |
| validator | v5.3 rules (origin/main) | soft rules; only `defined_risk` hard |
| UI | existing **Trade Insights** card `[Codex][Claude]` + DeepSeek | new **Trade Plan** tab `[Codex][Claude][DeepSeek]` (reuse `FrameworkTab`/`FrameworkSections`) |
| analysis_kind | `'insights'` (default) | `'blast'` |

---

## Milestone 1 — Restore v5.3 as the Trade Insights AI card

**Intent:** the production card goes back to exactly origin/main behavior. We do NOT delete the v6.0 code here — M2 moves it. This milestone strips framework from the *shared/default* path.

**Files (restore to `origin/main` content):**
- `src/uw_scan/reports/trade_insights_ai/prompt_text.py` → `PROMPT_VERSION = "trade-insights-ai-v5.3"`, drop the `trade_framework_kb` import.
- `src/uw_scan/reports/trade_insights_ai/analysis_input.py` → remove the framework sections + framework directive from the default builder.
- `src/uw_scan/reports/trade_insights_ai/validators.py` → remove the `_check_framework_rules` call from the default path.
- `src/uw_scan/models/` → remove `framework` field from the default `TradeInsightAiOutcome` (becomes blast-only — see M2).
- `src/uw_scan/reports/trade_insights_ai/__init__.py` → restore v5.3 export surface.

**Mechanic:** `git checkout origin/main -- <each file above>` then re-apply only the genuinely-shared, non-framework fixes that landed after main (the Decimal-in-JSONB storage fix is in `storage/`, not these files, so it survives untouched).

**HARD gate (the gate that was missing before):**
1. `bash scripts/migrate.sh` (no-op expected).
2. `uv run pytest tests/unit -q` green.
3. Bring up worktree stack (alt ports), enqueue **TSLA** for all 3 providers on the insights path.
4. Poll DB until **`status='succeeded'` for codex AND claude AND deepseek** with `prompt_version='trade-insights-ai-v5.3'` and NO framework block.
5. Playwright screenshot of the **Trade Insights** card showing populated `[Codex]`/`[Claude]` tabs → `output/playwright/insights-v5.3-TSLA-<provider>.png`.
   - Evidence query: `SELECT provider,status FROM uw_scan.trade_insight_ai_analyses WHERE ticker='TSLA' AND prompt_version='trade-insights-ai-v5.3' AND status='succeeded';` must return all 3.

**Commit:** `refactor(trade-insights): restore v5.3 prompt as production AI card (decouple from framework)`

---

## Milestone 2 — Re-home v6.0 as a separate `trade_blast` prompt (soft contract)

**Intent:** move the framework work into its own module tree so it can't touch the card; relax the contract so real output always renders.

**Files (create):**
- `src/uw_scan/reports/trade_blast/__init__.py`
- `src/uw_scan/reports/trade_blast/prompt_text.py` → `BLAST_PROMPT_VERSION = "trade-blast-v1"`, the trade-skills KB + framework decision-stack (moved from v6.0 `trade_framework_kb.py` + the framework steps).
- `src/uw_scan/reports/trade_blast/analysis_input.py` → builds the blast payload (positioning/fundamentals/macro/tape sections already added in `ede775f` — reuse those builders).
- `src/uw_scan/reports/trade_blast/validators.py` → **soft** validator: only `defined_risk` (no-naked-shorts) raises; the other 5 invariants downgrade to collected warnings stored on the row, never raise.
- `src/uw_scan/models/` → `TradeFramework` model stays, but `framework` lives on a **blast outcome** type (or stays optional and is only populated on the blast lane).

**Files (move/delete):**
- `reports/trade_insights_ai/validator_rules/framework.py`, `leniency/framework.py`, `trade_framework_kb.py` → move into `reports/trade_blast/`.

**Soft-validate / always-render mechanic:**
- Worker: on blast validation, catch non-defined-risk violations → set `status='partial'`, persist `raw_outcome_jsonb` + `outcome_jsonb` (best-effort coerced) + warnings in `provider_metadata_jsonb`. Only a defined-risk violation or unparseable JSON → `status='failed'`.
- Keep the `raw_decode`, envelope-unwrap, and net_delta coercion fixes (they help, just no longer gate rendering).

**HARD gate:**
1. `uv run pytest tests/unit -q` green (move framework tests under `tests/unit/.../trade_blast/`).
2. OpenAPI snapshot regenerated, diff reviewed.
3. Unit test: a deliberately-malformed framework payload → `status='partial'` with raw preserved (not `failed`/blank). A naked-short payload → `status='failed'` (hard rule holds).

**Commit:** `feat(trade-blast): re-home framework prompt as soft-validated trade_blast lane`

---

## Milestone 3 — `analysis_kind` discriminator (DB + storage)

**Files:**
- `src/uw_scan/storage/migrations/0NN_trade_insight_analysis_kind.sql` (next free number — verify with `ls src/uw_scan/storage/migrations | sort | tail`; currently ≥065):
  ```sql
  ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS analysis_kind text NOT NULL DEFAULT 'insights';
  -- drop + recreate the dedup unique key to include kind
  ALTER TABLE uw_scan.trade_insight_ai_analyses
    DROP CONSTRAINT IF EXISTS <existing_unique_name>;
  CREATE UNIQUE INDEX IF NOT EXISTS trade_insight_ai_analyses_dedup
    ON uw_scan.trade_insight_ai_analyses
    (snapshot_id, provider, analysis_kind, analysis_input_hash);
  ```
  (Find `<existing_unique_name>` first: `\d uw_scan.trade_insight_ai_analyses`.)
- `src/uw_scan/storage/trade_insights_ai.py` → add `analysis_kind` param (default `'insights'`) to `enqueue_*`, `find_latest_*`, `find_latest_*_per_provider`, `count_queued_*_by_provider`, `get_*`; add `AND analysis_kind = %s` to every WHERE.
- `src/uw_scan/worker/jobs/trade_insights_ai.py` → claim filters by kind so `ai-*` workers can serve both lanes; dispatch picks the prompt module by kind.

**HARD gate:**
1. `bash scripts/migrate.sh` **twice** → second run no-op (idempotent).
2. `uv run pytest tests/integration -q` **serially** (sole DB consumer) green.
3. Storage unit test: insights + blast rows for same (ticker, provider, snapshot) coexist and `find_latest(kind=...)` returns the right one.

**Commit:** `feat(storage): analysis_kind discriminator for insights vs blast lanes`

---

## Milestone 4 — API + worker wiring for the blast lane

**Files:**
- `src/uw_scan/api/routers/trade_insights.py` → blast enqueue + `/latest` keyed `analysis_kind='blast'`. Either a `kind` query param on the existing routes or a parallel `/trade-plan` route family (prefer a `kind` param to avoid duplication).
- Provider enable flags reused (`TRADE_INSIGHTS_AI_*`); blast respects the same kill switches.

**HARD gate:**
1. `cd web && npm run gen:types` → `web/lib/types.ts` regenerated, no drift beyond the new fields.
2. `uv run pytest tests/integration/api -q` (serial) green.
3. Curl: POST blast for TSLA returns 3 provider stubs; GET `/latest?kind=blast` returns them.

**Commit:** `feat(api): trade_blast enqueue + latest routes (kind-keyed)`

---

## Milestone 5 — New "Trade Plan" tab (reuse FrameworkTab)

**Files:**
- `web/components/stock/tabs/FrameworkTab.tsx` → relabel to **Trade Plan**, point at the blast `/latest?kind=blast` endpoint, 3-provider toggle `[Codex][Claude][DeepSeek]`. Render `partial` status with a soft-warning banner + the best-effort sections (never blank).
- `web/components/stock/tabs/framework/FrameworkSections.tsx` → handle `partial` rows (show warnings list).
- `web/app/stock/[ticker]/page.tsx` → register the **Trade Plan** tab in the tab list (the slot the old deterministic trade-plan tab vacated).
- Leave the existing **Trade Insights** card untouched (it's the restored v5.3 lane from M1).

**HARD gate (the real end-to-end proof):**
1. `cd web && npm run typecheck && npm run test` green.
2. Enqueue **TSLA** blast for all 3 providers via the real API→worker path.
3. Poll DB until **≥1 `succeeded` (or `partial`) blast row WITH a framework block**:
   `SELECT provider,status,(outcome_jsonb ? 'framework') FROM uw_scan.trade_insight_ai_analyses WHERE ticker='TSLA' AND analysis_kind='blast';`
4. Playwright screenshot of the **Trade Plan** tab rendering real TSLA framework data → `output/playwright/trade-plan-TSLA-<provider>.png`.
5. State plainly in the report: succeeded-with-framework count must be **≥1** (the metric that was 0 before).

**Commit:** `feat(web): Trade Plan tab rendering trade_blast framework (per-provider)`

---

## Milestone 6 — Verify, review, ship

1. Full gates: `uv run pytest` (unit + integration serial), `cd web && npm run typecheck && npm run test`, `bash scripts/migrate.sh` ×2, OpenAPI snapshot.
2. Standing-rule check: no naked shorts (hard rule verified by M2 test), no Yahoo, no secrets to Codex/Claude subprocesses, results persisted to Postgres.
3. `/review-cycle` on the cumulative diff — **with** the end-to-end gate evidence attached (succeeded row counts + screenshots), not just unit greens.
4. Open PR (only on explicit instruction / via ship).

---

## What this explicitly fixes vs the failed attempt
- **Before:** 1 prompt (v6.0) replaced v5.3; rigid contract; 0 framework successes; card degraded; "done" claimed with 0 real results.
- **After:** 2 lanes; v5.3 card restored & proven (3 providers succeed); blast lane soft-validates so it always renders; every milestone gated on a **real `succeeded`/`partial` DB row + screenshot**, not unit greens.

## Non-goals (YAGNI)
- No new data sources beyond what `ede775f`/`174106a`/`ed66b11` already added.
- No tuning of the v5.3 prompt — restore as-is.
- No deterministic trade-plan resurrection — the Trade Plan tab is AI-driven (blast), not the old computed plan.
