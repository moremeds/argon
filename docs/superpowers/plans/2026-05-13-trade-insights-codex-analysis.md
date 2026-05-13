# Trade Insights V1.5 Codex Analysis Plan

**Goal:** Add optional operator-triggered Codex commentary on top of the deterministic Trade Insights JSON without allowing AI output to override backend statuses, risk flags, or required checks.

## Phase 1 - Persistence

- Add an idempotent migration for `uw_scan.trade_insight_ai_analyses`.
- Columns: `analysis_id`, `ticker`, `run_id`, `input_hash`, `model`, `prompt_version`, `status`, `markdown`, `error_message`, `requested_at`, `started_at`, `finished_at`.
- Add repository helpers to enqueue, start, complete, fail, and fetch analyses by `analysis_id` and by `(ticker, input_hash, prompt_version)`.
- Store markdown separately from deterministic `trade_insight_snapshots`; do not mutate candidate statuses.

## Phase 2 - Prompt Contract

- Add a fixed prompt template in backend code, not user-editable UI text.
- Prompt must instruct Codex to analyze only supplied deterministic JSON, preserve every `status`, preserve every `risk_flag`, state missing data, avoid executable recommendations, and emit concise Markdown.
- Required Markdown sections: `Dominant Read`, `Best Expressions`, `Conflicts`, `Required Checks`, `Rejected Ideas`.
- Include prompt version in storage and job logs.

## Phase 3 - Worker Execution

- Add an allowlisted worker wrapper for non-interactive `codex exec`.
- Run Codex in read-only mode with no approval prompts and a hard timeout.
- Pass sanitized structured input by temp file or database `analysis_id`, not by large shell command string.
- Strip secrets from the environment before execution.
- Limit concurrency and output size.

## Phase 4 - API

- Add `POST /api/stock/{ticker}/trade-insights/ai-analysis` to enqueue analysis for the latest deterministic payload.
- Add a read endpoint for analysis status and markdown.
- Reuse an existing completed analysis when `(ticker, input_hash, prompt_version)` matches unless the request explicitly asks for a rerun.
- On Codex failure, return failed status while leaving the deterministic tab fully usable.

## Phase 5 - UI

- Add a secondary utility `Run AI Analysis` control below deterministic synthesis.
- Poll analysis status without blocking deterministic panel rendering.
- Render returned Markdown in a clearly labeled generated-commentary section.
- Never show AI commentary as a source of truth or promote `needs_check` candidates.

## Phase 6 - Tests

- Repository tests for idempotent enqueue and status transitions.
- Worker tests for timeout, failure, and output-size handling.
- API tests for enqueue, reuse, failure fallback, and latest-payload lookup.
- Frontend tests for button state, polling state, rendered markdown, and failure message.

## Out Of Scope

- Automatic analysis on every scan or page load.
- User-authored prompts.
- Order placement, sizing, or executable recommendations.
- Any AI override of deterministic candidate status, max loss, risk flags, or required checks.
