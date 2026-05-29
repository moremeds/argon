SET search_path TO uw_scan, public;

-- Per-provider runtime metadata captured from the runner: DeepSeek's
-- reasoning_content (chain-of-thought text emitted when thinking mode is
-- enabled), which output channel won (tool_calls vs delta.content), and
-- byte sizes for cost/latency analytics. Other providers may populate
-- subset fields (or leave the column NULL) — the shape is provider-
-- specific and intentionally schemaless.
ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS provider_metadata_jsonb jsonb;

COMMENT ON COLUMN uw_scan.trade_insight_ai_analyses.provider_metadata_jsonb IS
    'Internal-only diagnostic metadata from the provider runner — NOT '
    'surfaced via the public API today. Schemaless and provider-specific. '
    'Today (2026-05): DeepSeek populates {reasoning_content, '
    'reasoning_bytes, output_channel}; Codex/Claude leave it NULL. Future '
    'providers append their own keys without a migration. Readers MUST '
    'guard for missing keys; do not assume any field is present.';
