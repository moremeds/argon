# Trade Insights V1.5 AI Analysis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add operator-triggered local Codex CLI analysis to Trade Insights, returning a validated, timestamped, card-oriented structured market brief without changing deterministic trade data.

**Architecture:** Persist deterministic snapshots as V1 already does, then build a combined deterministic analysis input from the persisted Trade Insights snapshot plus the exact payloads produced by the Market Structure, Volatility, and Flow tabs. The API hashes and stores that analysis input for reuse, the worker injects the production timestamp into the final prompt payload, runs local `codex exec` in read-only non-interactive mode, validates structured JSON, stores `outcome_jsonb` plus rendered Markdown, and the UI polls by `analysis_id`.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, psycopg 3, APScheduler, Postgres JSONB, local Codex CLI, Next.js 16, React 19, TypeScript, Vitest, pytest.

---

## Preconditions

- Work on a feature branch, not `main`.
- Read `CLAUDE.md`, `src/uw_scan/CLAUDE.md`, and `src/uw_scan/storage/CLAUDE.md`.
- Read the design spec: `docs/superpowers/specs/2026-05-13-trade-insights-ai-analysis-design.md`.
- Do not run live UW tests unless explicitly asked.
- Use `uv run ...` for Python commands.
- Do not commit without explicit confirmation unless the current user instruction explicitly waives commit pauses.

## Phase 0 - Local Codex CLI And Repo Contract Checks

### Task 0.1: Verify local Codex CLI flags before runner work

**Files:**
- Modify if needed: `docs/superpowers/specs/2026-05-13-trade-insights-ai-analysis-design.md`
- Modify if needed: `docs/superpowers/plans/2026-05-13-trade-insights-ai-analysis-v15.md`

**Step 1: Verify installed Codex CLI version and flags**

Run:

```bash
codex --version
codex exec --help
```

Expected:

- `codex exec` exists.
- Help lists `--ephemeral`, `--sandbox`, `--ignore-user-config`, `--ignore-rules`, `--skip-git-repo-check`, `--cd`, `--output-schema`, and `--output-last-message`.
- Record the exact `codex --version` output and the verified flag list in the PR description or implementation notes so the runner contract is reviewable.

**Step 2: Lock or adjust the command contract**

If any flag is missing, update the design spec and this plan before writing runner code. Do not silently drop a sandbox/config flag.

Do not proceed to Phase 1 until the documented command contract and installed Codex CLI help output agree.

Current verified local baseline at plan-review time:

```text
codex-cli 0.130.0
```

This version supports the planned flag set.

**Step 3: Re-run doc hygiene if edited**

Run:

```bash
git diff --check HEAD -- docs/superpowers/specs/2026-05-13-trade-insights-ai-analysis-design.md docs/superpowers/plans/2026-05-13-trade-insights-ai-analysis-v15.md
```

Expected: pass.

## Phase 1 - API Models And Structured Outcome

### Task 1.1: Add Pydantic models for AI analysis status and outcome

**Files:**
- Modify: `src/uw_scan/models.py`
- Test: `tests/test_trade_insights_ai.py`

**Step 1: Write failing model tests**

Create `tests/test_trade_insights_ai.py` with tests for:

- `TradeInsightAiOutcome` serializes the required sections.
- `TradeInsightAiOutcome` rejects unknown extra fields.
- `TradeInsightAiAnalysisResponse` includes queue/status fields plus `trade_insights_input_hash`, `analysis_input_hash`, and `produced_at`.
- Missing optional `outcome` and `markdown` are allowed for queued/running rows.

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: fails because models do not exist.

**Step 2: Add outcome models**

In `src/uw_scan/models.py`, add:

- `TradeInsightAiBase` with `ConfigDict(extra="forbid")`
- `TradeInsightAiDominantRead`
- `TradeInsightAiSnapshotMeta`
- `TradeInsightAiHeadline`
- `TradeInsightAiMetricCard`
- `TradeInsightAiScenarioCard`
- `TradeInsightAiScoreBreakdown`
- `TradeInsightAiHighlight`
- `TradeInsightAiLevel`
- `TradeInsightAiSectionCard`
- `TradeInsightAiVrpAssessment`
- `TradeInsightAiPreferredExpression`
- `TradeInsightAiBestExpression`
- `TradeInsightAiConflict`
- `TradeInsightAiRequiredCheck`
- `TradeInsightAiRejectedIdea`
- `TradeInsightAiRendering`
- `TradeInsightAiGuardrails`
- `TradeInsightAiOutcome`
- `TradeInsightAiAnalysisRequest`
- `TradeInsightAiAnalysisResponse`

Use `Decimal` nowhere in these AI models unless a deterministic numeric is echoed as a string. AI output should reference supplied values, not recalculate prices.
Do not inherit these AI output models from `_UwBase`, because `_UwBase` ignores extra fields. AI outcome models must reject unknown fields so hallucinated keys cannot silently pass validation.
Metric cards, section-card highlights, and section-card levels must carry `source_path` strings pointing into the prompt payload unless they are explicitly missing-data notes.

`TradeInsightAiOutcome` must include the richer V1.5 market-brief fields from the design spec:

- `analysis_produced_at`
- `ticker`
- `underlying_price`
- `snapshot`
- `headline`
- `metric_cards`
- `scenario_cards`
- `score_breakdown`
- `section_cards`
- `vrp_assessment`
- `preferred_expression` (nullable when no deterministic candidate is suitable)
- `dominant_read`
- `best_expressions`
- `conflicts`
- `required_checks`
- `rejected_ideas`
- `missing_data`
- `rendering`
- `guardrails`

`section_cards` must require `market_structure`, `volatility`, and `flow_positioning`.

**Step 3: Re-run model tests**

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: pass.

**Step 4: Run broader Python model/lint checks**

Run:

```bash
uv run ruff check src/ tests/ scripts/
uv run pytest tests/test_trade_insights.py tests/test_trade_insights_ai.py -q
```

Expected: pass.

## Phase 2 - Persistence

### Task 2.1: Add migration for AI analysis rows

**Files:**
- Create: `src/uw_scan/storage/migrations/017_trade_insights_ai_analysis.sql`
- Modify: `tests/integration/storage/test_migrations.py`

**Step 1: Write failing migration test**

Extend `tests/integration/storage/test_migrations.py` to assert:

- `uw_scan.trade_insight_ai_analyses` exists.
- status check constraint rejects an invalid status.
- input/audit columns exist: `trade_insights_input_hash`, `analysis_input_hash`, `analysis_input_jsonb`, `prompt_text`, `prompt_payload_jsonb`, `output_schema_jsonb`, and `produced_at`.
- indexes exist for queue/reuse lookups.

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_migrations.py -q
```

Expected: fails because the table does not exist.

**Step 2: Add migration**

Create `017_trade_insights_ai_analysis.sql`:

- `SET search_path TO uw_scan, public;`
- Do not add `CREATE EXTENSION`; migration `005_jobs_table.sql` already creates `pgcrypto` for `gen_random_uuid()`.
- `CREATE TABLE IF NOT EXISTS trade_insight_ai_analyses (...)`
- Allowed `status`: `queued`, `running`, `succeeded`, `failed`.
- FK to `trade_insight_snapshots(snapshot_id)`.
- `trade_insights_input_hash text not null`.
- `analysis_input_hash text not null`.
- `analysis_input_jsonb jsonb not null`.
- `prompt_text text`.
- `prompt_payload_jsonb jsonb`.
- `output_schema_jsonb jsonb`.
- `produced_at timestamptz`.
- Queue index on `(status, requested_at)`.
- Reuse index/unique constraint for successful `(ticker, analysis_input_hash, prompt_version, model)`.
- Any partial unique index must be created with `CREATE UNIQUE INDEX IF NOT EXISTS`, not an inline `UNIQUE` constraint, because it is filtered by `status='succeeded'`.

All SQL must be idempotent.

**Step 3: Run migration twice**

Run:

```bash
bash scripts/migrate.sh
bash scripts/migrate.sh
```

Expected: both complete; second run is a no-op.

**Step 4: Re-run migration tests**

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_migrations.py -q
```

Expected: pass.

### Task 2.2: Add repository helpers

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_repository_trade_insights_ai.py`

**Step 1: Write failing repository tests**

Create tests covering:

- enqueue creates a queued row.
- enqueue stores `trade_insights_input_hash`, `analysis_input_hash`, and `analysis_input_jsonb`.
- prepare stores prompt text, prompt payload JSON, output schema JSON, and `produced_at` before execution.
- completed matching analysis is reused by `(ticker, analysis_input_hash, prompt_version, model)`.
- if more than one succeeded row exists for the same key due to pre-index test setup, `find_completed_trade_insight_ai_analysis(...)` returns the most recent succeeded row.
- a changed combined analysis input hash does not reuse an older succeeded row even when the Trade Insights snapshot hash is unchanged.
- force rerun creates a new row.
- claim transitions queued to running.
- complete stores `outcome_jsonb`, `markdown`, and `finished_at` without changing `produced_at`.
- fail stores `error_message` and `finished_at`.
- fetch by `analysis_id` and ticker scopes correctly.

Use `seeded_db_empty_cards`; do not invent new fixtures.

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_repository_trade_insights_ai.py -q
```

Expected: fails because repository helpers do not exist.

**Step 2: Implement repository helpers**

Add methods near the existing Trade Insights helpers:

- `fetch_trade_insight_snapshot(snapshot_id: int) -> dict | None`
- `fetch_latest_trade_insight_snapshot_for_hash(...)` if useful
- `find_completed_trade_insight_ai_analysis(ticker, analysis_input_hash, prompt_version, model)` returning the most recent `status='succeeded'` row for that reusable key, or `None`
- `enqueue_trade_insight_ai_analysis(snapshot_id, ticker, run_id, trade_insights_input_hash, analysis_input_hash, analysis_input, prompt_version, model) -> str`
- `claim_next_trade_insight_ai_analysis() -> dict | None`
- `prepare_trade_insight_ai_analysis(analysis_id, prompt_text, prompt_payload, output_schema, produced_at)`
- `complete_trade_insight_ai_analysis(analysis_id, outcome, markdown)`
- `fail_trade_insight_ai_analysis(analysis_id, error_message)`
- `get_trade_insight_ai_analysis(analysis_id, ticker=None)`

Keep queries parameterized. Use `Jsonb(outcome)` for `outcome_jsonb`.

**Step 3: Run repository tests**

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_repository_trade_insights_ai.py -q
```

Expected: pass.

## Phase 3 - Prompt, Validation, And Markdown Rendering

### Task 3.1: Add prompt builder and JSON schema

**Files:**
- Create: `src/uw_scan/reports/trade_insights_ai.py`
- Test: `tests/test_trade_insights_ai.py`

**Step 1: Write failing tests**

Add tests for:

- prompt includes prompt version.
- prompt includes the persisted Trade Insights snapshot payload.
- prompt payload includes `tabs.market_structure`, `tabs.volatility`, `tabs.flow`, `tabs.positioning`, and `tabs.trade_insights`.
- prompt payload uses real fields from `SingleStockReport`, `StockHistoryResponse`, `VolatilitySeriesResponse`, and `TradeInsightsResponse`.
- analysis input hash is stable for identical deterministic inputs and ignores `analysis_produced_at`.
- analysis input hash ignores volatile assembly timestamps such as `SingleStockReport.generated_at` and `TradeInsightsResponse.as_of` when they are generated at request time.
- analysis input hash changes when Market Structure, Volatility, Flow, positioning, or Trade Insights deterministic fields change.
- analysis input hash changes when volatility backfill completion adds or changes deterministic volatility series rows for the same Trade Insights snapshot.
- long source arrays are pruned to the deterministic bounds in the design spec before hashing.
- empty history arrays produce a valid analysis input with missing-data notes.
- prompt explicitly says the read must be built from Market Structure, Volatility, Flow, and positioning before candidate expressions.
- prompt includes a worker-provided `analysis_produced_at` timestamp and forbids inventing a different production time.
- prompt asks for a compact card-oriented result instead of long prose.
- prompt forbids outside data and executable recommendations.
- generated JSON Schema requires the structured sections.
- generated JSON Schema rejects additional properties for AI outcome objects.

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: fails.

**Step 2: Implement prompt/schema helpers**

In `src/uw_scan/reports/trade_insights_ai.py`, define:

- `PROMPT_VERSION = "trade-insights-ai-v1"`
- `build_trade_insights_ai_analysis_input(*, ticker: str, run_id: int, trade_insights_input_hash: str, trade_insights_payload: dict, stock_report_payload: dict, stock_history_payload: dict, volatility_series_payload: dict) -> dict`
- `hash_trade_insights_ai_analysis_input(analysis_input: dict) -> str`
- `build_trade_insights_ai_prompt_payload(analysis_input: dict, *, produced_at: datetime) -> dict`
- `build_trade_insights_ai_prompt(prompt_payload: dict) -> str`
- `trade_insights_ai_output_schema() -> dict`

The prompt must instruct Codex to emit only JSON conforming to `TradeInsightAiOutcome`.
Before passing any Pydantic models into these helpers, callers must use `.model_dump(mode="json")` so `Decimal`, `date`, and `datetime` fields are JSON-compatible. The hash helper must use canonical JSON equivalent to `json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)` so hashing stays deterministic and compatible with the V1 Trade Insights idiom.
The prompt payload must preserve these actual tab fields, pruning only long arrays to bounded top/recent slices:

- Market Structure from `SingleStockReport`: `market_structure`, `market_structure_levels`, `strike_gex_curve`, and `max_pain_rows`. Treat `generated_at` as non-authoritative assembly metadata and exclude it from `analysis_input_hash`.
- Market Structure history from `StockHistoryResponse`: recent `rows` with spot, GEX flip, net GEX, net DEX, IV30D, PCR volume, and bias.
- Volatility from `VolatilitySeriesResponse`: `as_of`, `backfill_status`, `header`, `term_structure`, `smile`, `hv_iv_history`, `iv_percentile_distribution`, `iv_of_iv`, `rv_spy_corr`, `regime_quadrant`, `divergence`, `divergence_headline`, `vrp_spread`, `vrp_spread_headline`, and `spot`. Treat `as_of` as request-time assembly metadata in V1.5 and exclude it from `analysis_input_hash`.
- Flow and positioning from `SingleStockReport`: `flow`, `dark_pool_print_count`, `dark_pool_notional`, `short_data`, `options_timeline`, `option_chain_per_strike`, `oi_change_top`, `next_earnings_date`, and flow-related `aggregates`.
- Trade Insights from `TradeInsightsResponse`: header, source reconciliation, signal stack, flow table, term structure table, candidate structures, and synthesis.
  Exclude volatile `as_of` from `analysis_input_hash` when it reflects request-time assembly rather than a true source timestamp.
- Flow/positioning carve-out: put `flow`, `options_timeline`, and `option_chain_per_strike` under `tabs.flow`; put `dark_pool_print_count`, `dark_pool_notional`, `short_data`, `oi_change_top`, flow-related `aggregates`, and `next_earnings_date` under `tabs.positioning`.
- Earnings caveat: include `next_earnings_date` when present, but also include the deterministic Trade Insights fact that `event_data_known=false` and all candidate statuses remain `needs_check`; the AI should frame any earnings/event reference as a required check, not as authoritative event validation.

Use deterministic pruning bounds:

- `stock_history.rows`: newest 30 rows.
- `strike_gex_curve`: top 40 rows by absolute `net_gex`, plus any rows matching named `market_structure_levels` strikes when present.
- `max_pain_rows`: nearest 12 expiries.
- `volatility.term_structure`: nearest 20 expiries.
- `volatility.smile`: nearest 6 expiries, max 25 points per expiry after downsampling by strike order.
- `volatility.hv_iv_history`, `iv_of_iv`, and `rv_spy_corr`: newest 90 points.
- `volatility.divergence`: newest 20 points.
- `volatility.vrp_spread`: newest 30 points.
- `flow.top_alerts`: already capped by `SingleStockReport` at 10.
- `options_timeline`: newest 60 rows.
- `option_chain_per_strike`: top 120 rows by combined volume/OI, while preserving rows near spot when spot is known.
- `oi_change_top`: current repository result cap of 50 rows.

It must exclude secrets, DSNs, API keys, and unrelated raw payload bulk. Do not ask the AI to reason about fields this repo does not currently produce, such as charm/vanna summaries or traditional short-interest percentage.
Fresh tickers with empty history are valid analysis inputs. The prompt payload should include empty arrays plus missing-data notes rather than causing POST to fail; tests should cover an empty `hv_iv_history` / `vrp_spread` / `stock_history.rows` degraded case.

**Step 3: Run tests**

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: pass.

### Task 3.2: Add outcome validation and Markdown renderer

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai.py`
- Test: `tests/test_trade_insights_ai.py`

**Step 1: Write failing tests**

Add tests for:

- validation rejects unknown idea IDs.
- validation rejects changed `status_observed`.
- validation rejects changed risk flags.
- validation rejects guardrails that are not all `true`.
- validation rejects imperative trade instructions.
- validation rejects a mismatched `analysis_produced_at`.
- validation rejects missing `market_structure`, `volatility`, or `flow_positioning` section cards.
- validation rejects references to unavailable source fields as if they were present, such as charm/vanna summaries or short-interest percentage, unless they appear under `missing_data`.
- validation rejects metric cards, section highlights, and section levels that lack `source_path` unless they are explicitly missing-data notes.
- validation rejects source paths whose required prefix does not exist. Validate enough segments to prove the source family exists, such as `tabs.volatility.header`, `tabs.flow.flow`, or `tabs.positioning.oi_change_top`; do not require resolving every array item after pruning.
- validation allows compact analytical labels such as `BUY setup` while still rejecting imperative text such as `buy now`.
- Markdown renderer includes headline, metrics, scenarios, market structure, volatility, flow/positioning, VRP, preferred expression, checks, and missing data.

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: fails.

**Step 2: Implement validation/rendering**

Add:

- `validate_trade_insights_ai_outcome(outcome, deterministic_payload, *, produced_at: datetime) -> TradeInsightAiOutcome`
- `render_trade_insights_ai_markdown(outcome: TradeInsightAiOutcome) -> str`

Do not parse Markdown in order to validate. Validate JSON first, render Markdown second.
The renderer must use the structured fields directly and should keep Markdown compact enough to review in logs or database audit views.
Imperative trade-instruction rejection should be field-aware. Reject imperatives in `headline.stance_label`, `preferred_expression.title`, `preferred_expression.subtitle`, and sentence starts in free-text fields; do not run a naive whole-JSON substring filter that rejects benign explanatory text.

**Step 3: Run tests**

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: pass.

## Phase 4 - Local Codex CLI Worker

### Task 4.1: Add local Codex runner wrapper

**Files:**
- Create: `src/uw_scan/worker/jobs/trade_insights_ai.py`
- Test: `tests/unit/worker/test_trade_insights_ai_runner.py`

**Step 1: Write failing runner tests**

Mock `subprocess.run` and test:

- command uses `codex exec`.
- command includes `--ephemeral`, `--sandbox read-only`, `--ignore-user-config`, `--ignore-rules`, `--skip-git-repo-check`, `--output-schema`, and `--output-last-message`.
- prompt is passed through stdin.
- environment excludes `UW_SCAN_API_KEY`, `MASSIVE_API_KEY`, and database password variables.
- timeout raises a controlled failure.
- non-zero exit raises a controlled failure.
- oversized output raises a controlled failure.

Run:

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_runner.py -q
```

Expected: fails.

**Step 2: Implement runner**

In `trade_insights_ai.py`, add:

- `TradeInsightsAiRunnerError`
- `run_codex_trade_insights_analysis(prompt, schema, *, model, timeout_seconds, max_output_bytes) -> dict`

Use `tempfile.TemporaryDirectory()` for prompt/schema/result files. Do not use shell interpolation.

**Step 3: Run runner tests**

Run:

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_runner.py -q
```

Expected: pass.

### Task 4.2: Add worker tick

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/config.py`
- Test: `tests/integration/worker/test_trade_insights_ai_jobs.py`

**Step 1: Write failing worker tests**

Use repository fixtures and monkeypatch the runner. Test:

- empty queue returns `False`.
- queued analysis is claimed and completed on valid mocked output.
- worker uses the stored `analysis_input_jsonb` from the queue row rather than rebuilding tab context after claim.
- invalid output marks failed.
- mismatched `analysis_produced_at` marks failed.
- runner timeout marks failed.
- prompt text, prompt payload, output schema, and produced timestamp are persisted.
- worker heartbeat is written through `repo.upsert_heartbeat("trade_insights_ai_tick")`.
- the worker commits claim/prepare state and releases its DB connection before invoking the Codex subprocess, then reopens a connection to complete or fail the row.

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_trade_insights_ai_jobs.py -q
```

Expected: fails.

**Step 2: Add settings**

In `src/uw_scan/config.py`, add env-driven settings:

- `trade_insights_ai_enabled: bool = False`
- `trade_insights_ai_model: str = ""`
- `trade_insights_ai_timeout_seconds: float = 90.0`
- `trade_insights_ai_max_output_bytes: int = 262144`
- `trade_insights_ai_poll_seconds: int = 3`

If model is blank, omit the `--model` flag and let local Codex CLI choose its default.
Store the model label as `codex-default` when the flag is omitted.

**Step 3: Implement worker tick**

Add `trade_insights_ai_tick(settings) -> bool` plus small internal helpers as needed.

Behavior:

- open a short repository context;
- call `repo.upsert_heartbeat("trade_insights_ai_tick")`;
- claim one queued row;
- load the row's stored `analysis_input_jsonb`;
- create one timezone-aware UTC `produced_at`;
- build final prompt payload from stored analysis input plus `produced_at`;
- build prompt/schema;
- call `prepare_trade_insight_ai_analysis(...)` to persist prompt text, prompt payload JSON, output schema JSON, and `produced_at` before invoking Codex;
- commit the claim/prepare work and close the repository context;
- run Codex;
- reopen a short repository context;
- validate outcome, including exact `analysis_produced_at == produced_at`;
- render Markdown;
- complete or fail row.

On runner timeout, non-zero exit, invalid output, or validation failure, reopen a repository context and call `fail_trade_insight_ai_analysis(...)`. Never keep the DB connection open while the Codex subprocess is running.

**Step 4: Register scheduler job**

In `src/uw_scan/worker/scheduler.py`, add an interval job if `settings.trade_insights_ai_enabled` is true:

```python
def _trade_insights_ai_tick() -> None:
    trade_insights_ai_tick(settings)


sched.add_job(
    _trade_insights_ai_tick,
    IntervalTrigger(seconds=settings.trade_insights_ai_poll_seconds),
    id="trade_insights_ai_tick",
    name="Trade Insights AI analysis poll",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=max(30, settings.trade_insights_ai_poll_seconds * 5),
)
```

**Step 5: Run worker tests**

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_trade_insights_ai_jobs.py -q
```

Expected: pass.

## Phase 5 - API

### Task 5.0: Add read-only volatility assembly path for AI input

**Files:**
- Modify: `src/uw_scan/reports/volatility_series.py`
- Test: `tests/test_trade_insights_ai.py` or `tests/integration/api/test_trade_insights_ai_endpoint.py`

**Step 1: Write failing tests**

Test:

- `assemble_volatility_series(..., persist_derived=False)` returns the same response shape as the default path for the same stored data.
- `persist_derived=False` does not call `persist_vrp_daily`, does not call `persist_stock_analytics`, and does not commit derived volatility/analytics writes.
- an empty `realized_vol_history` / `hv_iv_history` degraded case still returns a valid `VolatilitySeriesResponse` with empty arrays or missing-data notes rather than failing AI POST.

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: fails because the read-only flag does not exist.

**Step 2: Implement read-only mode**

In `src/uw_scan/reports/volatility_series.py`, extend:

```python
assemble_volatility_series(*, ticker: str, repo: Repository, backfill_status: str = "ready", persist_derived: bool = True)
```

Preserve existing behavior when `persist_derived=True`. When `persist_derived=False`, skip `persist_vrp_daily`, `persist_stock_analytics`, and the internal `repo.conn.commit()` at the end of the assembler. Do not start a backfill or call external data sources.

**Step 3: Run tests**

Run:

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: pass.

### Task 5.1: Add API endpoints

**Files:**
- Modify: `src/uw_scan/api/routers/trade_insights.py`
- Test: `tests/integration/api/test_trade_insights_ai_endpoint.py`
- Update snapshot: `tests/integration/api/openapi.snapshot.json`

**Step 1: Write failing API tests**

Test:

- POST returns `202` and queued analysis.
- POST reuses completed matching analysis.
- POST normalizes blank model config to `codex-default` before reuse/enqueue.
- POST computes `analysis_input_hash` from the combined deterministic tab payload, not only from `trade_insight_snapshots.input_hash`.
- POST does not reuse a prior success when Volatility, Market Structure, Flow, positioning, or Trade Insights deterministic input changes.
- POST with `force_rerun=true` creates a new row.
- POST returns 503 when `TRADE_INSIGHTS_AI_ENABLED=false` and does not enqueue an AI row.
- POST does not mutate VRP daily or stock analytics derived rows while building AI input for a reuse check.
- GET returns status/outcome.
- GET includes `produced_at` and persisted structured outcome when succeeded.
- GET returns 404 for wrong ticker or unknown analysis.
- deterministic Trade Insights GET still works after failed AI analysis.

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_trade_insights_ai_endpoint.py -q
```

Expected: fails.

**Step 2: Refactor deterministic snapshot creation**

In `trade_insights.py`, extract helper:

- `_build_and_persist_trade_insights(ticker, repo) -> tuple[TradeInsightsResponse, int, str]`

It should contain the existing GET assembly/persistence logic and return response, snapshot_id, input_hash.
Important commit boundary: the helper may upsert the deterministic snapshot and candidates, but it must not hide a commit inside itself. The GET handler should commit after calling it, preserving current behavior. The POST AI handler must commit after deterministic snapshot creation and AI row enqueue so the worker can query both the snapshot and queued row.

**Step 3: Implement POST and GET**

Add:

- `POST /stock/{ticker}/trade-insights/ai-analysis` with `status_code=202`
- `GET /stock/{ticker}/trade-insights/ai-analysis/{analysis_id}`

POST should assemble local deterministic source context without external calls:

- `assemble_single_stock_report(ticker, run_id, repo)` for Market Structure, Flow, dark-pool, short-borrow, OI-change, chain, timeline, and aggregate data.
- `repo.fetch_stock_history_rollup(ticker, limit=30)` plus the same `find_flip_strike(...)` and `classify_bias(...)` logic used by `src/uw_scan/api/routers/stock.py` for recent Market Structure history; do not import the API router.
- `assemble_volatility_series(ticker=ticker, repo=repo, backfill_status=(repo.get_volatility_backfill_status(ticker) or {}).get("status") or "ready", persist_derived=False)` for Volatility tab data, without kicking off a new backfill, making external calls, or committing derived VRP/analytics rows.
- persisted `trade_insight_snapshots.payload_jsonb` for Trade Insights candidates and synthesis.

POST should check `settings.trade_insights_ai_enabled` before enqueueing any AI row. It should serialize Pydantic source models with `.model_dump(mode="json")` before inserting into `analysis_input_jsonb` or hashing, so Decimal/date/datetime fields are JSON-compatible and canonical. It should build `analysis_input_jsonb`, compute `analysis_input_hash`, normalize blank model config to `codex-default`, reuse completed analysis unless forced, and enqueue new rows with the deterministic analysis input. The worker should construct and persist only the exact final prompt text, final prompt payload, output schema, and `produced_at`, because `analysis_produced_at` must reflect actual execution time rather than enqueue time.

V1.5 accepts the multi-assembler cost on every POST in order to compute a source-aware `analysis_input_hash`; it must not write derived volatility rows during that process. A future cache can store a latest analysis hash alongside deterministic snapshots if repeated POST latency becomes a problem.

**Step 4: Regenerate OpenAPI snapshot**

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_openapi_snapshot.py -q
```

If it fails because the snapshot changed, regenerate using the repo's existing snapshot workflow or update deliberately after inspecting the diff.

**Step 5: Run API tests**

Run:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_trade_insights_ai_endpoint.py tests/integration/api/test_trade_insights_endpoint.py tests/integration/api/test_openapi_snapshot.py -q
```

Expected: pass.

## Phase 6 - Frontend API Client And UI

### Task 6.1: Add generated types and API client methods

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/lib/types.ts`

**Step 1: Regenerate types**

Start API if needed, then run:

```bash
cd web && npm run gen:types
```

Expected: `web/lib/types.ts` includes the new AI analysis endpoints. Because `web/lib/types.ts` is checked in, inspect:

```bash
git diff -- web/lib/types.ts
```

Confirm the generated diff contains the AI request/response schemas and route types, and no unrelated OpenAPI drift.

**Step 2: Add client helpers**

In `web/lib/api.ts`, add:

- `tradeInsightsAiAnalysis(ticker, body?)`
- `tradeInsightsAiAnalysisStatus(ticker, analysisId)`
- exported `TradeInsightsAiAnalysisResponse` type.

**Step 3: Typecheck**

Run:

```bash
cd web && npm run typecheck
```

Expected: pass.

### Task 6.2: Add AI analysis panel

**Files:**
- Create: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx`
- Modify: `web/components/stock/tabs/TradeInsightsTab.tsx`
- Test: `web/tests/unit/tradeInsightsAiAnalysisPanel.test.tsx`

**Step 1: Write failing frontend tests**

Test:

- initial state shows `Run AI Analysis`.
- disabled API response shows an unavailable message instead of breaking deterministic panels.
- clicking button calls POST.
- queued/running disables the button.
- succeeded renders the card grid: headline, metric cards, scenarios, Market Structure, Volatility, Flow/Positioning, VRP Assessment, Preferred Expression, Conflicts, Required Checks, Rejected Ideas, and Missing Data.
- succeeded shows `analysis_produced_at`, deterministic data freshness, and generated-analysis disclaimer.
- failed status shows retry affordance.

Run:

```bash
cd web && npm run test -- tradeInsightsAiAnalysisPanel.test.tsx
```

Expected: fails.

**Step 2: Implement client panel**

Use a client component with local state and polling. Keep visual style consistent with existing `InsightPanel` shell.

Render from the structured `outcome`; do not parse `markdown`. Use a grouped card grid so the AI section is scan-friendly and does not become a long wall of text.

Placement in `TradeInsightsTab.tsx`:

```text
CandidateStructuresPanel
InsightsSynthesisPanel
TradeInsightsAiAnalysisPanel
bottom support panels
```

**Step 3: Run frontend tests and typecheck**

Run:

```bash
cd web && npm run test -- tradeInsightsAiAnalysisPanel.test.tsx tradeInsightsPanels.test.tsx && npm run typecheck
```

Expected: pass.

## Phase 7 - Verification And Smoke

### Task 7.1: Run backend CI-equivalent checks

Run:

```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/unit/ -v
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/ -v
```

Expected: all pass, live tests skipped unless credentials are explicitly provided.

### Task 7.2: Run frontend checks

Run:

```bash
cd web && npm run test -- tradeInsightsAiAnalysisPanel.test.tsx tradeInsightsPanels.test.tsx
cd web && npm run typecheck
```

Expected: pass.

### Task 7.3: Migration idempotency

Run:

```bash
bash scripts/migrate.sh
bash scripts/migrate.sh
```

Expected: both complete; no duplicate-object failures.

### Task 7.4: Manual local smoke

Start the stack:

```bash
export TRADE_INSIGHTS_AI_ENABLED=true
bash scripts/dev.sh
```

Smoke:

```bash
curl -sS -X POST http://127.0.0.1:8400/api/stock/TSLA/trade-insights/ai-analysis \
  -H 'Content-Type: application/json' \
  -d '{"force_rerun": false}'
```

Then poll:

```bash
curl -sS http://127.0.0.1:8400/api/stock/TSLA/trade-insights/ai-analysis/<analysis_id>
```

Expected:

- status transitions from `queued`/`running` to `succeeded` or a clear `failed`.
- successful rows have non-null `analysis_input_hash`, `analysis_input_jsonb`, `prompt_text`, `prompt_payload_jsonb`, `output_schema_jsonb`, `produced_at`, `outcome_jsonb`, and `markdown`.
- `outcome.analysis_produced_at` matches `produced_at`.
- deterministic tab remains usable if AI fails.
- browser route `/stock/TSLA/trade-insights` renders deterministic panels and the AI analysis panel without console errors.

### Task 7.5: Whitespace and final diff

Run:

```bash
git diff --check HEAD
git status --short --branch
```

Expected: whitespace clean; only intended files changed.

### Task 7.6: Documentation policy sync

**Files:**
- Modify if needed: `CLAUDE.md`
- Modify if needed: `AGENTS.md`

Check whether repo policy docs need updates for:

- `TRADE_INSIGHTS_AI_ENABLED`
- `TRADE_INSIGHTS_AI_MODEL`
- `TRADE_INSIGHTS_AI_TIMEOUT_SECONDS`
- `TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES`
- `TRADE_INSIGHTS_AI_POLL_SECONDS`
- local Codex CLI as the only V1.5 model execution path
- no secrets passed to local Codex subprocesses

`AGENTS.md` currently has stale Streamlit-era language. If this implementation touches repo policy or developer workflow docs, keep `CLAUDE.md` and `AGENTS.md` aligned or explicitly leave the stale `AGENTS.md` cleanup as a separate documented follow-up.

## Suggested Commit Slices

1. `Add Trade Insights AI analysis models`
2. `Persist Trade Insights AI analyses`
3. `Add Trade Insights AI prompt contract`
4. `Run Trade Insights AI analysis in worker`
5. `Add Trade Insights AI analysis API`
6. `Render Trade Insights AI analysis panel`
7. `Verify Trade Insights AI analysis workflow`

## Review Checklist Before Merge

- AI output is structured JSON and validated before storage.
- Markdown is rendered from validated JSON, not trusted as the source of truth.
- The exact prompt, prompt payload, output schema, and produced timestamp are persisted for review.
- The UI renders a compact card grid using Market Structure, Volatility, and Flow/Positioning fields.
- `analysis_produced_at` is displayed and validated against worker time.
- Local Codex CLI is the only model execution path.
- No UW/Massive/database secrets are passed to Codex.
- Deterministic candidate statuses and risk flags cannot be changed by AI.
- Queue/reuse behavior prevents duplicate successful analyses for the same combined deterministic analysis input hash.
- Default tests do not require local Codex auth.
- Failed AI analysis does not break deterministic Trade Insights.
