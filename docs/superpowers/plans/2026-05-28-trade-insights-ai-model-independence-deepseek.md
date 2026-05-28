# Trade Insights AI — Model Independence + DeepSeek Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the Trade Insights AI prompt + schema + validator from the `row_provider` name so adding a third provider (DeepSeek, via function-calling with `strict:true`) is a drop-in `RUNNERS` registration rather than a sprawl of `if provider == "claude"` branches.

**Architecture:** Three moves. (1) Hoist the Claude-only `_JSON_ONLY_SYSTEM_PROMPT` from the runner into a shared `CONTRACT_PROMPT` inside `prompt_text.py` so every provider sees the same contract (DeepSeek included). (2) Replace the two `row_provider`-keyed branches in the orchestrator (`strict=`, `lenient=`) with runner-declared class attributes (`schema_strict`, `strip_lookaround_regex`, `requires_lenient_validation`); the schema generator gains an orthogonal `strip_lookaround_regex` knob so the two concerns stop being conflated. (3) Add `DeepSeekRunner` as an in-process `httpx` HTTP runner targeting `https://api.deepseek.com/chat/completions` (the canonical endpoint; the `/v1` prefix from the OpenAI-SDK convention also works) with function-calling against `deepseek-v4-pro` by default, `tool_choice` forced, and `strict: true` (Beta) for server-side schema validation.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, Pydantic v2, psycopg 3, APScheduler 3, `httpx>=0.27`. No new dependencies — `httpx` is already in `pyproject.toml`.

> **Standing-rule reminder (CLAUDE.md):** "Never commit without an explicit user request." The `Commit (milestone)` steps in this plan assume the user has authorized milestone commits for this work. **If the user has not explicitly said "commit each milestone" for this plan, pause at the first commit step and ask** — staging-only is fine until then.

> **Scope reminder:** The user explicitly picked **decoupling-only**. No content changes to `MARKET_INTELLIGENCE_PROMPT` and no rewrites of the trade-skills heuristics (pitfall 24 / counterfactual P/L matrix etc.) — those are a separate follow-up plan.

> **Worktree:** This plan is executed in `.worktrees/feat-trade-insights-ai-deepseek/` on branch `feat/trade-insights-ai-deepseek`. The worktree was created from `main` at `159131b`.

> **Module-size note (CLAUDE.md):** `prompt_text.py` is currently ~696 lines. Adding `CONTRACT_PROMPT` (~155 lines) pushes it to ~850 lines — above the 500-line target but below the 1000-line "stop and propose a split" threshold. Acceptable for this PR; flag for a follow-up to split the constants module (vocab tuples vs prompt bodies) if it grows further.

---

## Design Context (read before starting)

### Why these three coupling sites matter

| Site | Today | DeepSeek symptom if unchanged |
|---|---|---|
| `trade_insights_claude_runner.py:135-290` `_JSON_ONLY_SYSTEM_PROMPT` | 155-line vocab + LEGS + DELTA-MATCH + REQUIRED-STRINGS rules shipped to Claude **only** via `--append-system-prompt` | DeepSeek never sees the rules → emits free-text bias values like `"bullish_continuation"` instead of `LONG_DELTA`, schema rejects |
| `worker/jobs/trade_insights_ai.py:134,165` `strict=(row_provider != "claude")` | Codex gets `additionalProperties:false` + required-everywhere; Claude gets a softer schema | Adding DeepSeek requires a third `if`; orthogonal concerns (strict-mode vs OpenAI-regex-strip) collapsed into one flag |
| `worker/jobs/trade_insights_ai.py:177` `lenient=(row_provider == "claude")` | Claude bypasses the strict equality checks via `_coerce_claude_outcome_dict` (issue #67 workaround) | DeepSeek should default to strict; today's branch implies "strict unless Claude" by accident |

### Why DeepSeek goes through function-calling, not response_format

[DeepSeek's JSON-mode docs](https://api-docs.deepseek.com/guides/json_mode) confirm `response_format` supports only `{type: "json_object"}` — **not** the OpenAI-style `{type: "json_schema", strict: true}`. The strict-enforcement path on DeepSeek is [function calling with `strict: true` (Beta)](https://api-docs.deepseek.com/guides/function_calling): define one tool whose `parameters` is the `TradeInsightAiOutcome` schema, force `tool_choice` to that tool, and DeepSeek validates server-side. This is what the user picked.

### Schema mode matrix after this plan

| Provider | `schema_strict` | `strip_lookaround_regex` | `requires_lenient_validation` | Wire format |
|---|---|---|---|---|
| Codex | True | True | False | `codex exec --output-schema schema.json` |
| Claude | False | False | True | `claude --print --json-schema '{...}'` |
| DeepSeek | True | True | False | HTTP function-calling with `strict: true` |

The Claude path stays exactly as it is today (lenient + relaxed schema + the existing `_coerce_claude_outcome_dict` coercer). The DeepSeek path mirrors Codex. The orthogonalization is what makes "DeepSeek mirrors Codex" expressible without re-introducing a fork.

### What stays out of scope (do NOT touch in this plan)

- `MARKET_INTELLIGENCE_PROMPT` content — only re-arrange, never re-author.
- `_coerce_claude_outcome_dict` and the `leniency/` module — still Claude-only. DeepSeek won't use it. Issue #67 stays open.
- `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx` — the third tab is a follow-up plan. This plan ships the backend only; you can queue a `provider='deepseek'` row via the existing API but no UI surfaces it.
- The lenient `Claude` schema variant (`additionalProperties:false` not enforced everywhere). Don't try to "fix" it for DeepSeek — DeepSeek uses the strict variant, not the lenient one.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/uw_scan/reports/trade_insights_ai/prompt_text.py` | Modify | Add `CONTRACT_PROMPT` constant (body = `_JSON_ONLY_SYSTEM_PROMPT` lifted from Claude runner, sans the StructuredOutput-tool sentence). |
| `src/uw_scan/reports/trade_insights_ai/__init__.py` | Modify | Re-export `CONTRACT_PROMPT`. |
| `src/uw_scan/reports/trade_insights_ai/analysis_input.py` | Modify | `build_trade_insights_ai_prompt` prepends `CONTRACT_PROMPT`; remove HARD-rule restatements from integration-notes appendix that duplicate `MARKET_INTELLIGENCE_PROMPT`. Split `trade_insights_ai_output_schema(*, strict, strip_lookaround_regex)`. |
| `src/uw_scan/worker/jobs/trade_insights_ai_runners.py` | Modify | Extend `AiProviderRunner` Protocol with three class-level attrs: `schema_strict`, `strip_lookaround_regex`, `requires_lenient_validation`. |
| `src/uw_scan/worker/jobs/trade_insights_codex_runner.py` | Modify | Add class attrs: `schema_strict=True, strip_lookaround_regex=True, requires_lenient_validation=False`. No behavior change. |
| `src/uw_scan/worker/jobs/trade_insights_claude_runner.py` | Modify | Add class attrs: `schema_strict=False, strip_lookaround_regex=False, requires_lenient_validation=True`. Delete `_JSON_ONLY_SYSTEM_PROMPT` constant. Remove `--append-system-prompt` from `cmd`. |
| `src/uw_scan/worker/jobs/trade_insights_deepseek_runner.py` | **Create** | New HTTP runner. `httpx.Client` POST to `https://api.deepseek.com/chat/completions` with function-calling + forced `tool_choice` + `strict: true`. |
| `src/uw_scan/worker/jobs/trade_insights_ai.py` | Modify | Register `DeepSeekRunner` in `RUNNERS`. Replace `strict=(row_provider != "claude")` with `runner.schema_strict` + `runner.strip_lookaround_regex`. Replace `lenient=(row_provider == "claude")` with `runner.requires_lenient_validation`. Add `_provider_model_and_timeout` branch for deepseek. |
| `src/uw_scan/config.py` | Modify | Add `trade_insights_ai_deepseek_enabled`, `trade_insights_ai_deepseek_model`, `trade_insights_ai_deepseek_timeout_seconds`, `trade_insights_ai_deepseek_worker_count`, `deepseek_api_key: SecretStr \| None`. Wire into `Settings.from_env`. |
| `src/uw_scan/worker/scheduler.py` | Modify | `WorkerGroup` Literal gains `"ai-deepseek"`; `WORKER_ROLES` set adds it; `_worker_groups` returns `{"ai-deepseek"}` for that role; add `_trade_insights_ai_tick_deepseek` job factory. |
| `scripts/dev.sh` | Modify | Add `ai-deepseek-0` / `ai-deepseek-1` panes mirroring the existing `ai-claude` pair. |
| `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py` | **Create** | Assert `CONTRACT_PROMPT` text appears in `build_trade_insights_ai_prompt(payload)` (every provider sees it). Assert no `HARD` rule is duplicated between `MARKET_INTELLIGENCE_PROMPT` and the integration-notes appendix. |
| `tests/test_trade_insights_ai.py` | Modify | Update `test_trade_insights_ai_output_schema_requires_structured_sections` to thread the new orthogonal `strip_lookaround_regex` arg. Audit existing prompt-substring assertions if any moved phrases. |
| `tests/unit/worker/test_trade_insights_claude_runner.py` | Modify | Drop assertions that expect `--append-system-prompt` in the cmd; add assertion that `--append-system-prompt` is NOT present. |
| `tests/unit/worker/test_trade_insights_codex_runner.py` | Modify | Add class-attr smoke check. |
| `tests/unit/worker/test_trade_insights_deepseek_runner.py` | **Create** | Mock `httpx`; assert (a) request shape (URL, auth header, tool_choice, strict:true); (b) happy-path tool_calls.arguments → outcome; (c) non-2xx → `TradeInsightsAiRunnerError`; (d) missing tool_calls → controlled failure; (e) timeout via `httpx.TimeoutException` → controlled failure; (f) secret never logged. |
| `tests/unit/worker/test_trade_insights_ai_runners_shared.py` | Modify | Assert the three Protocol class attrs are present on each runner with the expected values. |
| `tests/unit/test_config_trade_insights_ai.py` | Modify | Add DeepSeek env-var coverage. |
| `src/uw_scan/storage/migrations/063_trade_insights_ai_deepseek_provider.sql` | **Create** | New idempotent migration: `DROP CONSTRAINT IF EXISTS trade_insight_ai_analyses_provider_check; ADD CONSTRAINT … CHECK (provider IN ('codex','claude','deepseek'))`. Latest tip on `main` is `062_classification_unique_index.sql` — verify by running `ls src/uw_scan/storage/migrations/ \| tail -3` immediately before creating to catch any concurrent migration landing on main during execution. |
| `src/uw_scan/models/trade_insights_ai_parts/base.py` | Modify | Widen `TradeInsightAiProvider = Literal["codex", "claude", "deepseek"]`. **This is an explicit API contract change**, not a model split — per the standing rule "API model refactors preserve contract identity unless the PR is explicitly an API contract change," this PR qualifies and the OpenAPI snapshot regeneration is expected. |
| `tests/integration/api/openapi.snapshot.json` | Regenerate | Four enum sites pin `["codex","claude"]` (`TradeInsightAiAnalysisRequest.properties.providers.anyOf[0].items`, `TradeInsightAiAnalysisResponse.properties.provider`, `TradeInsightAiAnalysisStub.properties.provider`, `TradeInsightAiPriorRow.properties.provider`). Regenerate after Literal widens; verify the only diff is `deepseek` added to those four enums. |
| `tests/unit/test_models_trade_insights_ai_provider.py` | Modify | Existing tests `test_provider_literal_accepts_codex_and_claude` (line 21) and `test_latest_pair_allows_null_per_provider` (line 68) assume the 2-provider world. Extend to also accept `"deepseek"`; the negative test `test_provider_literal_rejects_other_values` (line 34) keeps `"openai"` as the rejected example (still not a provider). |
| `src/uw_scan/api/routers/trade_insights.py` | Modify | Add a third provider-enqueue block parallel to the codex (lines 297-308) and claude (314-328) blocks, gated on `settings.trade_insights_ai_deepseek_enabled` and `"deepseek" in provider_filter`. **DeepSeek participates in enqueue + persistence**, but for v1 the `_compute_provider_consensus(codex, claude)` consensus signal stays a 2-way codex-vs-claude comparison (cross-provider agreement on 3 providers is a separate scoping question). Document the carve-out explicitly in the function docstring. |
| `src/uw_scan/storage/trade_insights_ai.py` | Modify | `find_latest_trade_insight_ai_analyses_per_provider` (around line 283) initializes `out = {"codex": None, "claude": None}` — widen to also include `"deepseek": None`. Update the docstring (line 291) accordingly. |
| `src/uw_scan/api/routers/trade_insights.py` (second edit) | Modify | The `pair["codex"]` / `pair["claude"]` unpack at lines 443-444 must also extract `pair["deepseek"]`. The `TradeInsightAiLatestPair` Pydantic model already has a `current_prompt_version` field plus per-provider slots — add the `deepseek` slot (or treat it as optional/extra: pick whichever matches the model design). |
| `src/uw_scan/models/trade_insights_ai.py` | Modify | If `TradeInsightAiLatestPair` has fixed `codex` / `claude` fields, add an optional `deepseek` field. Verify with `grep -n "deepseek\|codex.*Response\|claude.*Response" src/uw_scan/models/trade_insights_ai*.py` before editing. |
| `src/uw_scan/api/routers/health.py` | Modify | Lines 373 + 380 hardcode `provider="codex"` and `provider="claude"` for heartbeat health checks. Add a third call for `provider="deepseek"` so the health endpoint surfaces the new worker role's liveness. |

---

## Task 1: Worktree baseline

**Files:** none (env setup only)

- [ ] **Step 1: Confirm worktree + branch**

```bash
cd /Users/chenxi/projects/unusual-whales/.worktrees/feat-trade-insights-ai-deepseek
git status && git branch --show-current
```

Expected: clean tree, branch = `feat/trade-insights-ai-deepseek`.

- [ ] **Step 2: Install deps**

```bash
uv sync --extra postgres
```

Expected: success, no resolver errors. The plan adds no new dependencies — `httpx` is already pinned.

- [ ] **Step 3: Baseline test run (touched packages only — full suite is too slow for a sanity check)**

```bash
uv run pytest tests/test_trade_insights_ai.py tests/unit/worker/test_trade_insights_claude_runner.py tests/unit/worker/test_trade_insights_codex_runner.py tests/unit/worker/test_trade_insights_ai_runners_shared.py tests/unit/test_config_trade_insights_ai.py -q
```

Expected: all pass. If anything fails on `main`, **stop and report** — do not start refactoring on a red baseline.

---

## Task 2: Hoist `CONTRACT_PROMPT` into shared prompt text

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai/prompt_text.py`
- Modify: `src/uw_scan/reports/trade_insights_ai/__init__.py`
- Create: `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py`

- [ ] **Step 1: Write the failing assembly test**

Create `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py`:

```python
from datetime import datetime, timezone

from uw_scan.reports.trade_insights_ai import (
    CONTRACT_PROMPT,
    MARKET_INTELLIGENCE_PROMPT,
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
)


def _minimal_analysis_input() -> dict:
    return {
        "ticker": "TEST",
        "run_id": "run-xyz",
        "trade_insights_input_hash": "hash-abc",
        "tabs": {
            "market_structure": {"market_structure": {"spot": "100.0"}},
            "volatility": {},
            "flow": {},
            "positioning": {},
        },
        "underlying_price": "100.0",
        "candidate_structures": [],
    }


def test_contract_prompt_present_in_assembled_prompt():
    """CONTRACT_PROMPT (lifted from Claude-only _JSON_ONLY_SYSTEM_PROMPT)
    must appear in every assembled prompt so DeepSeek/Codex see the same
    contract Claude has been getting through --append-system-prompt."""
    payload = build_trade_insights_ai_prompt_payload(
        _minimal_analysis_input(),
        produced_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    assembled = build_trade_insights_ai_prompt(payload)
    # Pick three load-bearing fragments from CONTRACT_PROMPT.
    assert 'directional_bias MUST be one of: "LONG_DELTA"' in assembled
    assert "MODE-STRUCTURE CONSISTENCY (HARD" in assembled
    assert "v5.3 LEGS REQUIREMENT (HARD)" in assembled


def test_contract_prompt_does_not_leak_claude_cli_or_structured_output_tool_hints():
    """CONTRACT_PROMPT must be provider-neutral. Two leaks to guard against:
    (a) the Claude CLI flag name '--json-schema' was rewritten to 'JSON schema'
        so DeepSeek/Codex callers aren't confused by Anthropic CLI grammar;
    (b) the trailing 'Use the StructuredOutput tool' Claude-mechanic sentence
        was dropped so non-Claude providers don't see misleading advice."""
    assert "--json-schema" not in CONTRACT_PROMPT
    assert "StructuredOutput tool" not in CONTRACT_PROMPT


def test_contract_prompt_exported_from_package_root():
    """Both __init__.py re-export and module attribute must resolve to
    the same constant so existing imports stay stable."""
    from uw_scan.reports.trade_insights_ai import prompt_text

    assert CONTRACT_PROMPT is prompt_text.CONTRACT_PROMPT
    assert isinstance(CONTRACT_PROMPT, str)
    assert len(CONTRACT_PROMPT) > 500  # Substantial body, not a stub
```

- [ ] **Step 2: Run and verify it fails**

```bash
uv run pytest tests/unit/reports/test_trade_insights_ai_prompt_assembly.py -v
```

Expected: FAIL with `ImportError: cannot import name 'CONTRACT_PROMPT'`.

- [ ] **Step 3: Lift `_JSON_ONLY_SYSTEM_PROMPT` body into `CONTRACT_PROMPT`**

**Boundary instructions (read carefully — the line numbers will drift, so anchor on text, not numbers):**

In `src/uw_scan/worker/jobs/trade_insights_claude_runner.py`, the body to lift is the *interior* of the `_JSON_ONLY_SYSTEM_PROMPT = """\ ... """` triple-quoted string. The body:

- **STARTS at** the line containing `Emit a single raw JSON object conforming EXACTLY to the supplied --json-schema.`
- **ENDS at** the line containing `rather than leaving blank.` (last line of the placeholder-fallback paragraph).
- **DROP** the trailing two lines that say `Use the StructuredOutput tool if available; otherwise emit the JSON object as the entire response.` — that's Claude-mechanic advice; it has no place in the shared CONTRACT_PROMPT.

One mechanical change inside the lifted body: replace the single occurrence of the substring `--json-schema` (in the very first sentence) with `JSON schema` — the term `--json-schema` is the Claude CLI flag name, which DeepSeek/Codex callers won't recognize. After the swap, the first sentence reads "Emit a single raw JSON object conforming EXACTLY to the supplied JSON schema."

Append the result to `src/uw_scan/reports/trade_insights_ai/prompt_text.py` as a new constant:

```python
# CONTRACT_PROMPT — the JSON-contract clause every provider must see.
#
# Lifted verbatim from the historical Claude-only `_JSON_ONLY_SYSTEM_PROMPT`
# at worker/jobs/trade_insights_claude_runner.py (pre-deepseek-decoupling).
# Codex was getting these rules indirectly via the integration-notes appendix
# in analysis_input.build_trade_insights_ai_prompt; Claude was getting them via
# --append-system-prompt. DeepSeek would have gotten nothing. Centralizing here
# means every provider sees the same contract through the user-prompt path.
#
# The final Claude-specific sentence ("Use the StructuredOutput tool if
# available; otherwise emit the JSON object as the entire response.") is
# INTENTIONALLY DROPPED here — that sentence is provider-mechanic advice and
# now lives only inside ClaudeRunner.run() comments where it belongs.
#
# The phrase "the supplied --json-schema" (Claude CLI flag name) was rewritten
# to "the supplied JSON schema" so the constant is provider-neutral.
CONTRACT_PROMPT = """\
Emit a single raw JSON object conforming EXACTLY to the supplied JSON schema. \
Use exact field names at every nesting level; additionalProperties is false \
everywhere. No markdown, no code fences, no prose before/after.

<... paste the rest of the original body verbatim from
"Populate EVERY field below;..." through "...rather than leaving blank." ...>
"""
```

**Sanity-check before moving on:** the resulting `CONTRACT_PROMPT` must contain each of these load-bearing substrings (these are also asserted by the Step 1 test, so a copy mistake will be caught):

- `directional_bias MUST be one of: "LONG_DELTA"`
- `MODE-STRUCTURE CONSISTENCY (HARD`
- `v5.3 LEGS REQUIREMENT (HARD)`

And must NOT contain:

- `--json-schema` (CLI flag — was rewritten)
- `Use the StructuredOutput tool` (Claude-specific — was dropped)

- [ ] **Step 4: Re-export from `__init__.py`**

Open `src/uw_scan/reports/trade_insights_ai/__init__.py` and add `CONTRACT_PROMPT` to the `.prompt_text` import block + `__all__`:

```python
from .prompt_text import (
    CONTRACT_PROMPT,  # NEW
    DIRECTIONAL_BIAS_VALUES,
    # ... existing entries
)

__all__ = [
    "CONTRACT_PROMPT",  # NEW
    "DIRECTIONAL_BIAS_VALUES",
    # ... existing entries
]
```

- [ ] **Step 5: Prepend `CONTRACT_PROMPT` in `build_trade_insights_ai_prompt`**

In `src/uw_scan/reports/trade_insights_ai/analysis_input.py`, modify `build_trade_insights_ai_prompt` (line 505) to add `CONTRACT_PROMPT` between `MARKET_INTELLIGENCE_PROMPT` and the integration notes:

```python
def build_trade_insights_ai_prompt(prompt_payload: dict[str, Any]) -> str:
    payload_json = json.dumps(prompt_payload, sort_keys=True, indent=2, default=str)
    return (
        f"{MARKET_INTELLIGENCE_PROMPT}\n\n"
        f"{CONTRACT_PROMPT}\n\n"
        "Integration notes for this local JSON runner:\n"
        # ... rest unchanged for now (Task 3 will dedupe)
    )
```

Add `CONTRACT_PROMPT` to the import from `.prompt_text` at the top of `analysis_input.py`.

- [ ] **Step 6: Run the assembly test to verify pass**

```bash
uv run pytest tests/unit/reports/test_trade_insights_ai_prompt_assembly.py -v
```

Expected: PASS.

- [ ] **Step 7: Run touched test packages to confirm no regression**

```bash
uv run pytest tests/test_trade_insights_ai.py tests/unit/reports/ -q
```

Expected: all pass. If a previously-passing test asserted a specific prompt-text substring and now sees the same string twice (because it's in both `MARKET_INTELLIGENCE_PROMPT` and the integration notes appendix), do NOT relax the test — Task 3 will fix that by deduping the appendix.

- [ ] **Step 8: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/reports/trade_insights_ai/prompt_text.py \
        src/uw_scan/reports/trade_insights_ai/__init__.py \
        src/uw_scan/reports/trade_insights_ai/analysis_input.py \
        tests/unit/reports/test_trade_insights_ai_prompt_assembly.py
git commit -m "feat(trade-insights-ai): hoist Claude system prompt into shared CONTRACT_PROMPT"
```

---

## Task 3: Dedupe HARD-rule restatements from the integration-notes appendix

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai/analysis_input.py`
- Modify: `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py`

Context: the integration-notes appendix in `build_trade_insights_ai_prompt` (lines 508-718) restates rules that are now stated TWICE — once in `MARKET_INTELLIGENCE_PROMPT` and once in `CONTRACT_PROMPT`. Delete the appendix's redundant restatements. Keep the appendix-native content (payload key map, source-path rule, `idea_id` rules, headline.stance derivation, conviction rubric reminders).

- [ ] **Step 1: Write the failing dedup test**

Append to `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py`:

```python
def test_hard_rules_not_triplicated_after_dedupe():
    """After dedup, each load-bearing HARD-rule clause appears at most twice
    (once in MARKET_INTELLIGENCE_PROMPT, once in CONTRACT_PROMPT). Triplication
    means the integration-notes appendix still restates a rule that's now in
    CONTRACT_PROMPT — token waste, drift surface."""
    payload = build_trade_insights_ai_prompt_payload(
        _minimal_analysis_input(),
        produced_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    assembled = build_trade_insights_ai_prompt(payload)
    for needle in [
        "MODE-STRUCTURE CONSISTENCY",
        "DELTA-MATCH",
        "DTE-band consistency",
        "Trigger-strike consistency",
        "Conditional-quote validity",   # also restated in v5.1 integration notes
        "Anti-pin quality",              # both bodies have anti-pin guidance
    ]:
        # case-insensitive count, since CONTRACT_PROMPT and MARKET_INTELLIGENCE_PROMPT
        # disagree on capitalization for some terms
        count = assembled.lower().count(needle.lower())
        assert count <= 2, (
            f"{needle!r} appears {count}x in assembled prompt; "
            "should appear at most twice (MARKET_INTELLIGENCE_PROMPT + CONTRACT_PROMPT)"
        )
```

- [ ] **Step 2: Run and verify failures**

```bash
uv run pytest tests/unit/reports/test_trade_insights_ai_prompt_assembly.py::test_hard_rules_not_triplicated_after_dedupe -v
```

Expected: FAIL — at least one needle appears 3x.

- [ ] **Step 3: Delete redundant clauses from `build_trade_insights_ai_prompt` appendix**

In `analysis_input.py:508-718`, delete these specific clauses (they're now in CONTRACT_PROMPT):

- "Mode-aware structure consistency (HARD): if headline.trade_intent == …" (~lines 539-547)
- "Delta-match (HARD): when directional_bias == LONG_DELTA…" (~lines 548-553)
- "DTE-band consistency (HARD, v5.1)…" (~lines 554-558)
- "Trigger-strike consistency (HARD, v5.1)…" (~lines 559-571)
- "Conditional-quote validity (HARD, v5.1)…" (~lines 572-583)

KEEP these (they're not in CONTRACT_PROMPT — they're orchestration-specific notes):

- "Integration notes for this local JSON runner: …" preamble
- "Payload key map: ticker <- ticker; as_of <- tabs.trade_insights.as_of…"
- "Use analysis_produced_at exactly as supplied…"
- "schema_version MUST be exactly the string…"
- "Source-path rule (HARD): every source_path in the outcome must resolve…"
- "Horizon enforcement: every candidate_structures row…"
- "idea_id rules (HARD)…"
- "Derive headline.stance from headline.directional_bias…"
- "Set guardrails.no_executable_recommendations=true…"
- "Keep the markdown output (rendering.markdown if emitted) under ~3 KB…"
- "Emit only JSON conforming to the TradeInsightAiOutcome schema."
- "Payload: …"

Use Read first to confirm exact line ranges before Edit calls — the file may have drifted from the line numbers cited above.

- [ ] **Step 4: Run the dedup test to verify pass**

```bash
uv run pytest tests/unit/reports/test_trade_insights_ai_prompt_assembly.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the broader trade_insights tests**

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: PASS. If a snapshot-style test asserts the appendix contains a deleted phrase, update the assertion to look in `CONTRACT_PROMPT` instead. **Do not weaken the test** — the contract is still expected to surface.

- [ ] **Step 6: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/reports/trade_insights_ai/analysis_input.py \
        tests/unit/reports/test_trade_insights_ai_prompt_assembly.py
git commit -m "feat(trade-insights-ai): dedupe HARD-rule restatements between MARKET_INTELLIGENCE_PROMPT and integration notes"
```

---

## Task 4: Drop `--append-system-prompt` from Claude runner

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insights_claude_runner.py`
- Modify: `tests/unit/worker/test_trade_insights_claude_runner.py`

Now that `CONTRACT_PROMPT` is in the user-prompt path for every provider, Claude no longer needs its private `--append-system-prompt _JSON_ONLY_SYSTEM_PROMPT` injection.

- [ ] **Step 1: Update the existing claude-runner cmd-shape test**

In `tests/unit/worker/test_trade_insights_claude_runner.py:50` (`test_claude_runner_uses_print_mode_with_locked_down_flags`):

Find the assertion(s) that expect `"--append-system-prompt"` in the cmd or `_JSON_ONLY_SYSTEM_PROMPT` as the following arg. Replace with an assertion that `--append-system-prompt` is **NOT** in the cmd:

```python
def test_claude_runner_does_not_use_append_system_prompt(monkeypatch):
    """Post-decoupling: CONTRACT_PROMPT lives in the user prompt for every
    provider. --append-system-prompt is no longer needed and is omitted."""
    # ... existing monkeypatch setup ...
    runner = ClaudeRunner()
    runner.run(prompt="...", schema={...}, model="", timeout_seconds=10.0, max_output_bytes=4096)
    captured_cmd = recorded_calls[0]["cmd"]
    assert "--append-system-prompt" not in captured_cmd
```

- [ ] **Step 2: Run, expect FAIL**

```bash
uv run pytest tests/unit/worker/test_trade_insights_claude_runner.py::test_claude_runner_does_not_use_append_system_prompt -v
```

Expected: FAIL — runner still includes the flag.

- [ ] **Step 3: Remove `_JSON_ONLY_SYSTEM_PROMPT` from the runner**

In `src/uw_scan/worker/jobs/trade_insights_claude_runner.py`:

1. Delete the `_JSON_ONLY_SYSTEM_PROMPT = """\..."""` block (lines 135-290).
2. Delete these two lines from the `cmd` list (around line 327-328):

```python
                "--append-system-prompt",
                _JSON_ONLY_SYSTEM_PROMPT,
```

3. Leave `--setting-sources ""` in place — that's still load-bearing for plugin/output-style isolation.

- [ ] **Step 4: Run claude-runner tests**

```bash
uv run pytest tests/unit/worker/test_trade_insights_claude_runner.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/worker/jobs/trade_insights_claude_runner.py \
        tests/unit/worker/test_trade_insights_claude_runner.py
git commit -m "feat(trade-insights-ai): drop --append-system-prompt from Claude runner (CONTRACT_PROMPT now in shared user prompt)"
```

---

## Task 5: Split schema generator's `strict` argument into two orthogonal flags

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai/analysis_input.py`
- Modify: `tests/test_trade_insights_ai.py`

The current `trade_insights_ai_output_schema(*, strict: bool = True)` conflates two concerns: (a) "everything is required + additionalProperties:false" (b) "strip Pydantic's negative-lookahead regex on Decimal serialization." DeepSeek needs (a) AND (b); the Claude lenient path needs neither. Currently they ride together; split them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_insights_ai.py`:

```python
def test_schema_strict_and_lookaround_strip_are_orthogonal():
    """The two concerns are independent. We need to be able to ask for
    strict=False + strip=True (no current consumer, but mechanically valid)
    and for strict=True + strip=False (no current consumer either, but valid
    as a sanity check on the split). Today the strip rides on strict."""
    from uw_scan.reports.trade_insights_ai import trade_insights_ai_output_schema
    import json

    s_no_strip = trade_insights_ai_output_schema(
        strict=True, strip_lookaround_regex=False
    )
    s_strip = trade_insights_ai_output_schema(
        strict=True, strip_lookaround_regex=True
    )
    # The lookaround-bearing pattern (Pydantic Decimal negative-lookahead) MUST
    # be present in the no-strip variant and absent from the strip variant.
    blob_no = json.dumps(s_no_strip)
    blob_strip = json.dumps(s_strip)
    assert "(?!" in blob_no, "no-strip variant should retain lookaround patterns"
    assert "(?!" not in blob_strip, "strip variant should remove lookaround patterns"


def test_schema_strict_false_strip_false_matches_claude_lenient_today():
    """The Claude path historically called the schema with strict=False;
    that called the strip code as well only because strict gated both.
    After the split, Claude calls strict=False, strip=False — same observable
    schema. Pin that equivalence."""
    from uw_scan.reports.trade_insights_ai import trade_insights_ai_output_schema

    new_call = trade_insights_ai_output_schema(
        strict=False, strip_lookaround_regex=False
    )
    # Today's single-arg shape — keep the call site for back-compat coverage.
    # Will fail until the signature accepts the new arg.
    legacy_call = trade_insights_ai_output_schema(strict=False)
    assert new_call == legacy_call
```

- [ ] **Step 2: Run, expect FAIL**

```bash
uv run pytest tests/test_trade_insights_ai.py::test_schema_strict_and_lookaround_strip_are_orthogonal tests/test_trade_insights_ai.py::test_schema_strict_false_strip_false_matches_claude_lenient_today -v
```

Expected: FAIL — unknown kwarg `strip_lookaround_regex`.

- [ ] **Step 3: Split the signature**

Replace `trade_insights_ai_output_schema` (around `analysis_input.py:764`) with:

```python
def trade_insights_ai_output_schema(
    *,
    strict: bool = True,
    strip_lookaround_regex: bool | None = None,
) -> dict[str, Any]:
    """Produce the JSON schema for TradeInsightAiOutcome.

    Two orthogonal axes:

    - `strict`: if True, every nested property is required and
      `additionalProperties: false` is enforced everywhere. Required by
      OpenAI/Codex structured output and by DeepSeek function-calling with
      `strict: true`. Claude's StructuredOutput tool silently drops to
      freeform JSON when the schema is too strict at every level, so the
      Claude path passes False.

    - `strip_lookaround_regex`: if True, drop Pydantic's negative-lookahead
      regex patterns from Decimal-string serialization. OpenAI's structured-
      output validator and DeepSeek's strict-mode function-calling validator
      both reject lookarounds; Anthropic's accepts them. Defaults to
      `strict` when None (preserves the historical coupling for callers that
      haven't migrated to the orthogonal API).
    """
    if strip_lookaround_regex is None:
        strip_lookaround_regex = strict
    raw = TradeInsightAiOutcome.model_json_schema()
    schema = _coerce_strict_schema(raw) if strict else raw
    if strip_lookaround_regex:
        schema = _strip_openai_unsupported_patterns(schema)
    schema["properties"]["schema_version"]["const"] = PROMPT_VERSION
    schema["$defs"]["TradeInsightAiHeadline"]["properties"]["conviction"]["enum"] = (
        list(FINAL_RATING_VALUES)
    )
    return schema
```

The `None` default preserves the legacy single-arg call shape (existing tests + the orchestrator both keep passing).

- [ ] **Step 4: Run, expect PASS**

```bash
uv run pytest tests/test_trade_insights_ai.py::test_schema_strict_and_lookaround_strip_are_orthogonal tests/test_trade_insights_ai.py::test_schema_strict_false_strip_false_matches_claude_lenient_today -v
```

Expected: PASS.

- [ ] **Step 5: Sanity-check the whole test file**

```bash
uv run pytest tests/test_trade_insights_ai.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/reports/trade_insights_ai/analysis_input.py \
        tests/test_trade_insights_ai.py
git commit -m "feat(trade-insights-ai): split schema generator strict-mode into orthogonal strict + strip_lookaround_regex flags"
```

---

## Task 6: Runner-declared contract flags (`AiProviderRunner` Protocol)

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai_runners.py`
- Modify: `src/uw_scan/worker/jobs/trade_insights_codex_runner.py`
- Modify: `src/uw_scan/worker/jobs/trade_insights_claude_runner.py`
- Modify: `tests/unit/worker/test_trade_insights_ai_runners_shared.py`

- [ ] **Step 1: Write the failing class-attr test**

In `tests/unit/worker/test_trade_insights_ai_runners_shared.py`, append:

```python
def test_codex_runner_declares_strict_contract_flags():
    from uw_scan.worker.jobs.trade_insights_codex_runner import CodexRunner

    runner = CodexRunner()
    assert runner.schema_strict is True
    assert runner.strip_lookaround_regex is True
    assert runner.requires_lenient_validation is False


def test_claude_runner_declares_lenient_contract_flags():
    from uw_scan.worker.jobs.trade_insights_claude_runner import ClaudeRunner

    runner = ClaudeRunner()
    assert runner.schema_strict is False
    assert runner.strip_lookaround_regex is False
    assert runner.requires_lenient_validation is True
```

- [ ] **Step 2: Run, expect FAIL**

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_runners_shared.py -q
```

Expected: FAIL with `AttributeError: 'CodexRunner' object has no attribute 'schema_strict'`.

- [ ] **Step 3: Extend the Protocol**

In `src/uw_scan/worker/jobs/trade_insights_ai_runners.py`, modify `AiProviderRunner` Protocol:

```python
class AiProviderRunner(Protocol):
    """Interface every provider runner must satisfy."""

    name: str  # "codex" | "claude" | "deepseek"

    # Schema-generation flags consumed by the orchestrator. Each runner
    # declares them once as class attributes; the orchestrator never branches
    # on runner.name. Adding a fourth provider = add a class + register; no
    # orchestrator change.
    schema_strict: bool
    strip_lookaround_regex: bool
    requires_lenient_validation: bool

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult: ...
```

- [ ] **Step 4: Set attrs on `CodexRunner`**

In `trade_insights_codex_runner.py`, add class-level attrs to `CodexRunner`:

```python
class CodexRunner:
    """Local Codex CLI runner. Reads keychain auth via CODEX_HOME."""

    name = "codex"
    schema_strict = True
    strip_lookaround_regex = True
    requires_lenient_validation = False
```

- [ ] **Step 5: Set attrs on `ClaudeRunner`**

In `trade_insights_claude_runner.py`, add class-level attrs to `ClaudeRunner`:

```python
class ClaudeRunner:
    """Local `claude --print` runner. Reads keychain OAuth (no env var)."""

    name = "claude"
    schema_strict = False
    strip_lookaround_regex = False
    requires_lenient_validation = True
```

- [ ] **Step 6: Run, expect PASS**

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_runners_shared.py tests/unit/worker/test_trade_insights_codex_runner.py tests/unit/worker/test_trade_insights_claude_runner.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/worker/jobs/trade_insights_ai_runners.py \
        src/uw_scan/worker/jobs/trade_insights_codex_runner.py \
        src/uw_scan/worker/jobs/trade_insights_claude_runner.py \
        tests/unit/worker/test_trade_insights_ai_runners_shared.py
git commit -m "feat(trade-insights-ai): declare schema_strict/strip_lookaround_regex/requires_lenient_validation on runners"
```

---

## Task 7: Orchestrator stops branching on `row_provider`

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai.py`
- Modify: `tests/test_trade_insights_ai.py` (or add a new orchestrator test file if cleaner)

- [ ] **Step 1: Find existing orchestrator coverage**

```bash
grep -n "trade_insights_ai_tick\|strict=(row_provider\|lenient=(row_provider" tests/ -r
```

If there's a unit test for `trade_insights_ai_tick`, use it. If not, add an orchestrator-level integration test that asserts the schema kwargs are sourced from `runner` and not from `row_provider`.

- [ ] **Step 2: Write the failing orchestrator-dispatch test**

Create or extend `tests/unit/worker/test_trade_insights_ai_orchestrator.py`:

```python
"""Orchestrator no longer branches on row_provider for schema/validator config.

These tests pin the contract by monkeypatching the schema generator + validator
to capture kwargs and assert the orchestrator passes runner-declared flags."""

from unittest.mock import MagicMock

import pytest

from uw_scan.worker.jobs import trade_insights_ai as orchestrator


def test_orchestrator_threads_runner_schema_flags_not_provider_name(monkeypatch):
    """If you add a provider whose schema_strict=True but whose name is not
    'codex', this test catches that the orchestrator must read schema_strict
    from the runner, not infer from name."""
    captured = {}

    def fake_schema(*, strict, strip_lookaround_regex):
        captured["strict"] = strict
        captured["strip"] = strip_lookaround_regex
        return {"type": "object"}

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.trade_insights_ai_output_schema",
        fake_schema,
    )
    # Test wiring: feed a synthetic runner with non-codex name but strict flags.
    # This will FAIL until orchestrator stops keying on row_provider == "claude".
    # ... (full plumbing test fixture — see existing orchestrator coverage style)
```

If you instead choose to update `tests/test_trade_insights_ai.py`, add the test there. The point is: the test asserts `strict=` and `lenient=` are read from `runner.schema_strict` / `runner.requires_lenient_validation`, NOT from `row_provider`.

- [ ] **Step 3: Run, expect FAIL**

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_orchestrator.py -v
```

- [ ] **Step 4: Patch the orchestrator**

In `src/uw_scan/worker/jobs/trade_insights_ai.py`:

Replace line 134:

```python
        output_schema = trade_insights_ai_output_schema(
            strict=(row_provider != "claude"),
        )
```

with:

```python
        output_schema = trade_insights_ai_output_schema(
            strict=runner.schema_strict,
            strip_lookaround_regex=runner.strip_lookaround_regex,
        )
```

— but `runner` isn't resolved at this point in the function (it's the `prepare` phase before runner dispatch). Look up the runner once early:

```python
        # After: `if row_provider not in RUNNERS: ...`
        runner = RUNNERS[row_provider]
        # ... existing logic continues, using `runner` for schema kwargs and
        # for the .run() call later in the function
        output_schema = trade_insights_ai_output_schema(
            strict=runner.schema_strict,
            strip_lookaround_regex=runner.strip_lookaround_regex,
        )
```

Then at line 165 (the second schema call inside the `runner.run(...)` invocation), reuse the same call shape:

```python
        result = runner.run(
            build_trade_insights_ai_prompt(prompt_payload),
            trade_insights_ai_output_schema(
                strict=runner.schema_strict,
                strip_lookaround_regex=runner.strip_lookaround_regex,
            ),
            model=model_env,
            timeout_seconds=timeout,
            max_output_bytes=settings.trade_insights_ai_max_output_bytes,
        )
```

Then at line 177, replace:

```python
            lenient=(row_provider == "claude"),
```

with:

```python
            lenient=runner.requires_lenient_validation,
```

- [ ] **Step 5: Run, expect PASS**

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_orchestrator.py tests/test_trade_insights_ai.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/worker/jobs/trade_insights_ai.py \
        tests/unit/worker/test_trade_insights_ai_orchestrator.py
git commit -m "feat(trade-insights-ai): orchestrator reads contract flags from runner, not row_provider"
```

---

## Task 7a: Widen DB CHECK constraint + Pydantic Literal + regenerate OpenAPI snapshot

**Why this runs BEFORE the DeepSeek runner task:** the runner is useless if the DB rejects `provider='deepseek'` inserts. The CHECK constraint at `migrations/053_trade_insights_ai_provider_column.sql:16` is `provider IN ('codex', 'claude')` — without widening it first, the very first DeepSeek INSERT raises `CheckViolation` and the worker crashes on the unhandled `psycopg.errors.CheckViolation`. Similarly, the Pydantic `TradeInsightAiProvider` Literal rejects `"deepseek"` at validation time before any DB call is even attempted.

**Files:**
- Create: `src/uw_scan/storage/migrations/063_trade_insights_ai_deepseek_provider.sql`
- Modify: `src/uw_scan/models/trade_insights_ai_parts/base.py`
- Modify: `tests/unit/test_models_trade_insights_ai_provider.py`
- Modify (regenerate): `tests/integration/api/openapi.snapshot.json`

- [ ] **Step 1: Write the failing model-Literal test**

Open `tests/unit/test_models_trade_insights_ai_provider.py`. Append:

```python
def test_provider_literal_accepts_deepseek() -> None:
    stub = TradeInsightAiAnalysisStub(
        provider="deepseek",
        analysis_id=uuid4(),
        status="queued",
        reused=False,
        model="deepseek-v4-pro",
    )
    assert stub.provider == "deepseek"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
uv run pytest tests/unit/test_models_trade_insights_ai_provider.py::test_provider_literal_accepts_deepseek -v
```

Expected: FAIL with Pydantic `ValidationError` (Literal rejects `"deepseek"`).

- [ ] **Step 3: Widen the Literal**

In `src/uw_scan/models/trade_insights_ai_parts/base.py:51`:

```python
# Before:
TradeInsightAiProvider = Literal["codex", "claude"]

# After:
TradeInsightAiProvider = Literal["codex", "claude", "deepseek"]
```

- [ ] **Step 4: Run model test, expect PASS**

```bash
uv run pytest tests/unit/test_models_trade_insights_ai_provider.py -v
```

Expected: all pass.

- [ ] **Step 5: Write the failing DB-CHECK constraint test**

This test belongs at `tests/integration/storage/test_trade_insights_ai_provider_check.py` (create the file). It uses the existing `pytest-postgresql` fixture path.

```python
"""Integration: DB CHECK constraint accepts the deepseek provider value
after migration 063."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest


def test_provider_check_constraint_accepts_deepseek(repo):
    """Insert with provider='deepseek' MUST succeed after migration 063.
    Without 063, the CHECK constraint from 053 would reject this row."""
    conn = repo.conn
    schema = repo._schema
    sql = (
        f"INSERT INTO {schema}.trade_insight_ai_analyses ("
        "  analysis_id, ticker, run_id, trade_insights_input_hash,"
        "  analysis_input_hash, analysis_input_jsonb, prompt_version,"
        "  model, provider, status, requested_at"
        ") VALUES (%s, 'TEST', 1, 'h1', 'h2', '{}'::jsonb,"
        "  'trade-insights-ai-v5.3', 'deepseek-v4-pro', 'deepseek',"
        "  'queued', %s)"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (uuid4(), datetime.now(timezone.utc)))
    conn.commit()


def test_provider_check_constraint_still_rejects_unknown(repo):
    """Regression guard: the CHECK constraint is widened to add deepseek,
    NOT removed. Inserting 'openai' must still fail."""
    conn = repo.conn
    schema = repo._schema
    sql = (
        f"INSERT INTO {schema}.trade_insight_ai_analyses ("
        "  analysis_id, ticker, run_id, trade_insights_input_hash,"
        "  analysis_input_hash, analysis_input_jsonb, prompt_version,"
        "  model, provider, status, requested_at"
        ") VALUES (%s, 'TEST', 1, 'h1', 'h2', '{}'::jsonb,"
        "  'trade-insights-ai-v5.3', 'gpt-4', 'openai',"
        "  'queued', %s)"
    )
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(sql, (uuid4(), datetime.now(timezone.utc)))
    conn.rollback()
```

The `repo` fixture is the project-standard `pytest-postgresql`-backed Repository — used widely in `tests/integration/storage/`. If the fixture isn't named `repo` in this project, grep `tests/integration/storage/*.py` for the existing pattern and copy it (do NOT introduce a new fixture style).

- [ ] **Step 6: Run, expect FAIL (CheckViolation)**

```bash
uv run pytest tests/integration/storage/test_trade_insights_ai_provider_check.py -v
```

Expected: `test_provider_check_constraint_accepts_deepseek` fails with `psycopg.errors.CheckViolation`.

- [ ] **Step 7: Write the migration**

Create `src/uw_scan/storage/migrations/063_trade_insights_ai_deepseek_provider.sql`:

```sql
-- 063_trade_insights_ai_deepseek_provider.sql
-- Widen the trade_insight_ai_analyses.provider CHECK constraint to admit
-- the deepseek provider added in this PR. Idempotent (DROP IF EXISTS
-- before ADD CONSTRAINT) so re-running migrate.sh is a no-op.

ALTER TABLE uw_scan.trade_insight_ai_analyses
    DROP CONSTRAINT IF EXISTS trade_insight_ai_analyses_provider_check;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD CONSTRAINT trade_insight_ai_analyses_provider_check
        CHECK (provider IN ('codex', 'claude', 'deepseek'));

COMMENT ON COLUMN uw_scan.trade_insight_ai_analyses.provider IS
    'AI provider that produced this analysis: codex, claude, or deepseek. '
    'Each Run enqueues one row per enabled provider; per-provider cache reuse '
    'is enforced by the unique indexes keyed on (ticker, analysis_input_hash, '
    'prompt_version, model, provider).';
```

- [ ] **Step 8: Apply migration to scratch DB and verify**

```bash
bash scripts/migrate.sh
bash scripts/migrate.sh   # Run twice — second run must be a no-op (idempotent)
```

Expected: both runs succeed. Standing-rule check: migration must be idempotent.

- [ ] **Step 9: Run the integration test, expect PASS**

```bash
uv run pytest tests/integration/storage/test_trade_insights_ai_provider_check.py -v
```

Expected: both tests pass — deepseek inserts succeed, openai still rejected.

- [ ] **Step 10: Regenerate the OpenAPI snapshot**

The Pydantic Literal widening propagates to four enum sites in the OpenAPI schema. Regenerate:

```bash
uv run python -c "
from uw_scan.api.server import create_app
import json
from pathlib import Path
app = create_app()
schema = app.openapi()
out = Path('tests/integration/api/openapi.snapshot.json')
out.write_text(json.dumps(schema, indent=2, sort_keys=False) + '\n')
print('Wrote', out)
"
```

(If `create_app` takes required Settings arg, pass it the same way the existing API tests do — grep `tests/integration/api/conftest.py` for the pattern.)

- [ ] **Step 11: Diff the snapshot — only deepseek additions expected**

```bash
git diff tests/integration/api/openapi.snapshot.json | grep -E '^[-+]' | grep -v '^[-+]{3}'
```

Expected: only additions of `"deepseek"` to the four `enum` arrays under (a) `TradeInsightAiAnalysisRequest.properties.providers.anyOf[0].items`, (b) `TradeInsightAiAnalysisResponse.properties.provider`, (c) `TradeInsightAiAnalysisStub.properties.provider`, (d) `TradeInsightAiPriorRow.properties.provider`. **If any other line changes, stop and investigate** — it means an unintended contract drift.

- [ ] **Step 12: Run the snapshot test**

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```

Expected: PASS.

- [ ] **Step 13: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/storage/migrations/063_trade_insights_ai_deepseek_provider.sql \
        src/uw_scan/models/trade_insights_ai_parts/base.py \
        tests/unit/test_models_trade_insights_ai_provider.py \
        tests/integration/storage/test_trade_insights_ai_provider_check.py \
        tests/integration/api/openapi.snapshot.json
git commit -m "feat(trade-insights-ai): widen provider CHECK + Literal + OpenAPI for deepseek"
```

---

## Task 8: `DeepSeekRunner` HTTP runner

**Files:**
- Create: `src/uw_scan/worker/jobs/trade_insights_deepseek_runner.py`
- Create: `tests/unit/worker/test_trade_insights_deepseek_runner.py`

### Wire format DeepSeek accepts (per docs)

```
POST https://api.deepseek.com/chat/completions
Authorization: Bearer $DEEPSEEK_API_KEY
Content-Type: application/json

{
  "model": "deepseek-v4-pro",
  "messages": [{"role": "user", "content": "<prompt>"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "emit_trade_insight",
      "description": "Emit the structured TradeInsightAiOutcome for this analysis.",
      "parameters": <full TradeInsightAiOutcome JSON schema>,
      "strict": true
    }
  }],
  "tool_choice": {"type": "function", "function": {"name": "emit_trade_insight"}}
}
```

Response shape:

```
choices[0].message.tool_calls[0].function.arguments  # string of JSON
choices[0].message.tool_calls[0].function.name       # "emit_trade_insight"
model                                                 # echoed model id
```

- [ ] **Step 1: Write the failing test (cmd shape)**

Create `tests/unit/worker/test_trade_insights_deepseek_runner.py`:

```python
"""DeepSeek HTTP runner tests. Mocks httpx — never hits the network."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest


def _mock_success_response(monkeypatch, outcome_obj, *, resolved_model="deepseek-v4-pro"):
    """Replace httpx.Client.post with a stub returning a DeepSeek-shaped success
    envelope where tool_calls[0].function.arguments is json.dumps(outcome_obj)."""
    body = {
        "model": resolved_model,
        "choices": [{
            "message": {
                "tool_calls": [{
                    "function": {
                        "name": "emit_trade_insight",
                        "arguments": json.dumps(outcome_obj),
                    }
                }],
            }
        }],
    }
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = body
    response.raise_for_status.return_value = None
    response.text = json.dumps(body)
    captured = {}

    def fake_post(self, url, *, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return captured


def test_deepseek_runner_posts_function_call_with_strict_true(monkeypatch):
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    outcome = {"schema_version": "trade-insights-ai-v5.3", "ticker": "TEST"}
    captured = _mock_success_response(monkeypatch, outcome)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    runner = DeepSeekRunner()
    result = runner.run(
        prompt="analyze TEST",
        schema={"type": "object", "properties": {}},
        model="deepseek-v4-pro",
        timeout_seconds=10.0,
        max_output_bytes=4096,
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    body = captured["json"]
    assert body["model"] == "deepseek-v4-pro"
    tool = body["tools"][0]["function"]
    assert tool["name"] == "emit_trade_insight"
    assert tool["strict"] is True
    assert tool["parameters"] == {"type": "object", "properties": {}}
    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_trade_insight"},
    }
    assert result.outcome == outcome
    assert result.resolved_model == "deepseek-v4-pro"


def test_deepseek_runner_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    with pytest.raises(TradeInsightsAiRunnerError, match="DEEPSEEK_API_KEY"):
        DeepSeekRunner().run(
            prompt="x", schema={}, model="deepseek-v4-pro",
            timeout_seconds=10.0, max_output_bytes=4096,
        )


def test_deepseek_runner_raises_on_non_2xx(monkeypatch):
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    err_response = MagicMock(spec=httpx.Response)
    err_response.status_code = 429
    err_response.text = '{"error":{"message":"rate limited"}}'
    err_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=err_response
    )
    monkeypatch.setattr(
        httpx.Client, "post", lambda self, url, **kw: err_response
    )
    with pytest.raises(TradeInsightsAiRunnerError):
        DeepSeekRunner().run(
            prompt="x", schema={}, model="deepseek-v4-pro",
            timeout_seconds=10.0, max_output_bytes=4096,
        )


def test_deepseek_runner_raises_when_response_missing_tool_calls(monkeypatch):
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"content": "free text"}}],
    }
    response.raise_for_status.return_value = None
    response.text = json.dumps(response.json.return_value)
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kw: response)
    with pytest.raises(TradeInsightsAiRunnerError, match="tool_calls"):
        DeepSeekRunner().run(
            prompt="x", schema={}, model="deepseek-v4-pro",
            timeout_seconds=10.0, max_output_bytes=4096,
        )


def test_deepseek_runner_rejects_unexpected_tool_name(monkeypatch):
    """tool_choice was forced; if DeepSeek returns a tool_call whose name is
    something other than 'emit_trade_insight' (e.g. model hallucinated a
    different tool), parsing the arguments would silently bind output to a
    schema we never asked for. Reject loudly instead."""
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"tool_calls": [{
            "function": {
                "name": "search_web",   # wrong tool — schema mismatch
                "arguments": json.dumps({"q": "AAPL"}),
            }
        }]}}],
    }
    response.raise_for_status.return_value = None
    response.text = json.dumps(response.json.return_value)
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kw: response)
    with pytest.raises(TradeInsightsAiRunnerError, match="unexpected tool name"):
        DeepSeekRunner().run(
            prompt="x", schema={}, model="deepseek-v4-pro",
            timeout_seconds=10.0, max_output_bytes=4096,
        )


def test_deepseek_runner_raises_on_timeout(monkeypatch):
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def raise_timeout(self, url, **kw):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.Client, "post", raise_timeout)
    with pytest.raises(TradeInsightsAiRunnerError, match="timed out"):
        DeepSeekRunner().run(
            prompt="x", schema={}, model="deepseek-v4-pro",
            timeout_seconds=10.0, max_output_bytes=4096,
        )


def test_deepseek_runner_raises_when_output_exceeds_max_bytes(monkeypatch):
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    huge_outcome = {"schema_version": "trade-insights-ai-v5.3", "blob": "x" * 5000}
    _mock_success_response(monkeypatch, huge_outcome)
    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        DeepSeekRunner().run(
            prompt="x", schema={}, model="deepseek-v4-pro",
            timeout_seconds=10.0, max_output_bytes=512,
        )


def test_deepseek_runner_declares_strict_contract_flags():
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    runner = DeepSeekRunner()
    assert runner.name == "deepseek"
    assert runner.schema_strict is True
    assert runner.strip_lookaround_regex is True
    assert runner.requires_lenient_validation is False


def test_deepseek_api_key_is_not_in_subprocess_child_env_allowlist(monkeypatch):
    """Regression guard: the _runner_child_env allow-list forwards a fixed
    set of neutral env vars to Codex/Claude subprocesses. Adding
    DEEPSEEK_API_KEY to that allow-list would leak the key to subprocesses
    that don't need it (codex exec, claude --print), violating the standing
    rule 'no secrets to local Codex subprocesses'.

    The DeepSeek runner is in-process HTTP and reads DEEPSEEK_API_KEY from
    os.environ directly — it does NOT go through _runner_child_env. This test
    pins that separation."""
    from uw_scan.worker.jobs.trade_insights_ai_runners import _runner_child_env

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-not-leak-here")
    child_env = _runner_child_env()
    assert "DEEPSEEK_API_KEY" not in child_env, (
        "DEEPSEEK_API_KEY leaked into subprocess child env — would expose "
        "the DeepSeek key to Codex/Claude CLI subprocesses. Remove it from "
        "the _runner_child_env allow-list."
    )
```

- [ ] **Step 2: Run, expect ImportError**

```bash
uv run pytest tests/unit/worker/test_trade_insights_deepseek_runner.py -v
```

Expected: FAIL with `ImportError: cannot import name 'DeepSeekRunner'`.

- [ ] **Step 3: Implement the runner**

Create `src/uw_scan/worker/jobs/trade_insights_deepseek_runner.py`:

```python
"""DeepSeek HTTP runner — implements AiProviderRunner via DeepSeek's
OpenAI-compatible /v1/chat/completions endpoint.

Unlike Codex/Claude, this runner is in-process HTTP (httpx) rather than a
subprocess. DeepSeek's API is OpenAI-compatible in shape, but its
structured-output story is different: response_format only supports
{type: "json_object"} (no strict json_schema). The schema-enforcement path
is function-calling with strict:true (Beta) — define one tool whose
parameters is the TradeInsightAiOutcome schema, force tool_choice to that
tool, and DeepSeek validates server-side.

Docs:
- JSON mode (response_format=json_object only):
  https://api-docs.deepseek.com/guides/json_mode
- Function calling + strict mode (Beta):
  https://api-docs.deepseek.com/guides/function_calling

Auth: DEEPSEEK_API_KEY read from process env at call time. Unlike the
subprocess runners, no _runner_child_env allow-list dance — this runs
in-process so the existing process env is available directly. The key
itself is never logged or echoed in error messages.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    RunnerResult,
    TradeInsightsAiRunnerError,
)

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_TOOL_NAME = "emit_trade_insight"


class DeepSeekRunner:
    """In-process HTTP runner. Reads DEEPSEEK_API_KEY from env."""

    name = "deepseek"
    schema_strict = True
    strip_lookaround_regex = True
    requires_lenient_validation = False

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise TradeInsightsAiRunnerError(
                "DEEPSEEK_API_KEY is not set in the worker environment"
            )

        effective_model = model.strip() or "deepseek-v4-pro"

        body = {
            "model": effective_model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": DEEPSEEK_TOOL_NAME,
                        "description": (
                            "Emit the structured TradeInsightAiOutcome for "
                            "this analysis. Populate every field required by "
                            "the supplied JSON schema."
                        ),
                        "parameters": schema,
                        "strict": True,
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": DEEPSEEK_TOOL_NAME},
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    DEEPSEEK_CHAT_COMPLETIONS_URL,
                    json=body,
                    headers=headers,
                    timeout=timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise TradeInsightsAiRunnerError(
                f"deepseek HTTP timed out after {timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise TradeInsightsAiRunnerError(
                f"deepseek HTTP transport error: {exc!r}"
            ) from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # response.text MAY contain the api key if it was echoed back —
            # in practice DeepSeek does not echo it, but truncate defensively.
            preview = (response.text or "")[:500]
            raise TradeInsightsAiRunnerError(
                f"deepseek HTTP {response.status_code}: {preview}"
            ) from exc

        try:
            envelope = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise TradeInsightsAiRunnerError(
                "deepseek response was not valid JSON"
            ) from exc
        if not isinstance(envelope, dict):
            # response.json() can decode a top-level list or scalar; the next
            # .get() would raise AttributeError which the orchestrator wraps as
            # a bare runtime error. Convert to a controlled failure with a
            # diagnostic that doesn't leak the response body (could contain
            # echoed prompt material).
            raise TradeInsightsAiRunnerError(
                "deepseek response JSON was not an object "
                f"(got {type(envelope).__name__})"
            )

        choices = envelope.get("choices") or []
        if not choices:
            raise TradeInsightsAiRunnerError(
                "deepseek response had no choices[]"
            )
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            raise TradeInsightsAiRunnerError(
                "deepseek response had no tool_calls — model did not emit "
                "structured output. Check that strict:true is honored."
            )
        function_call = tool_calls[0].get("function") or {}
        emitted_name = function_call.get("name")
        if emitted_name != DEEPSEEK_TOOL_NAME:
            # tool_choice was forced; if DeepSeek returns a different tool
            # name we have no contract for what `arguments` means.
            raise TradeInsightsAiRunnerError(
                "deepseek emitted unexpected tool name "
                f"{emitted_name!r} (expected {DEEPSEEK_TOOL_NAME!r})"
            )
        arguments = function_call.get("arguments") or ""

        if len(arguments.encode("utf-8")) > max_output_bytes:
            raise TradeInsightsAiRunnerError(
                f"deepseek tool-call arguments exceeded {max_output_bytes} bytes"
            )

        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise TradeInsightsAiRunnerError(
                "deepseek tool-call arguments were not valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise TradeInsightsAiRunnerError(
                "deepseek tool-call arguments must be a JSON object"
            )

        resolved = envelope.get("model") or effective_model or "deepseek-default"
        return RunnerResult(outcome=parsed, resolved_model=resolved)
```

- [ ] **Step 4: Run, expect PASS**

```bash
uv run pytest tests/unit/worker/test_trade_insights_deepseek_runner.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/worker/jobs/trade_insights_deepseek_runner.py \
        tests/unit/worker/test_trade_insights_deepseek_runner.py
git commit -m "feat(trade-insights-ai): add DeepSeek HTTP runner with function-calling strict mode"
```

---

## Task 9: Register DeepSeek in `RUNNERS` + Settings + scheduler routing

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai.py`
- Modify: `src/uw_scan/config.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `tests/unit/test_config_trade_insights_ai.py`
- Modify: `tests/unit/worker/test_trade_insights_ai_orchestrator.py` (or wherever orchestrator tests live)

- [ ] **Step 1: Write the failing Settings test**

Append to `tests/unit/test_config_trade_insights_ai.py`:

```python
def test_settings_parses_deepseek_env(monkeypatch):
    from uw_scan.config import Settings

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-fake")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED", "true")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT", "2")
    settings = Settings.from_env()
    assert settings.trade_insights_ai_deepseek_enabled is True
    assert settings.trade_insights_ai_deepseek_model == "deepseek-v4-pro"
    assert settings.trade_insights_ai_deepseek_timeout_seconds == 240.0
    assert settings.trade_insights_ai_deepseek_worker_count == 2
    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "sk-deepseek-fake"


def test_settings_deepseek_defaults_when_env_unset(monkeypatch):
    from uw_scan.config import Settings

    for var in [
        "DEEPSEEK_API_KEY",
        "TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED",
        "TRADE_INSIGHTS_AI_DEEPSEEK_MODEL",
        "TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS",
        "TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT",
    ]:
        monkeypatch.delenv(var, raising=False)
    settings = Settings.from_env()
    assert settings.trade_insights_ai_deepseek_enabled is True
    assert settings.trade_insights_ai_deepseek_model == ""
    assert settings.trade_insights_ai_deepseek_timeout_seconds == 300.0
    assert settings.trade_insights_ai_deepseek_worker_count == 2
    assert settings.deepseek_api_key is None
```

- [ ] **Step 2: Run, expect FAIL**

```bash
uv run pytest tests/unit/test_config_trade_insights_ai.py -v
```

Expected: FAIL — attributes missing on Settings.

- [ ] **Step 3: Extend `Settings`**

In `src/uw_scan/config.py`, after the existing `trade_insights_ai_claude_worker_count` line (~line 139), add:

```python
    # Trade Insights AI DeepSeek provider (alongside Codex + Claude)
    trade_insights_ai_deepseek_enabled: bool = True
    trade_insights_ai_deepseek_model: str = ""
    trade_insights_ai_deepseek_timeout_seconds: float = 300.0
    trade_insights_ai_deepseek_worker_count: int = 2
    deepseek_api_key: SecretStr | None = None
```

And in `Settings.from_env` (~line 333, after the claude block), add:

```python
            trade_insights_ai_deepseek_enabled=_env_bool(
                "TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED", True
            ),
            trade_insights_ai_deepseek_model=os.environ.get(
                "TRADE_INSIGHTS_AI_DEEPSEEK_MODEL", ""
            ),
            trade_insights_ai_deepseek_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS", "300.0")
            ),
            trade_insights_ai_deepseek_worker_count=int(
                os.environ.get("TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT", "2")
            ),
            deepseek_api_key=(
                SecretStr(_ds_key)
                if (_ds_key := os.environ.get("DEEPSEEK_API_KEY", "").strip())
                else None
            ),
```

- [ ] **Step 4: Run Settings test**

```bash
uv run pytest tests/unit/test_config_trade_insights_ai.py -v
```

Expected: PASS.

- [ ] **Step 5: Register DeepSeek in `RUNNERS`**

In `src/uw_scan/worker/jobs/trade_insights_ai.py`:

```python
from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

RUNNERS: dict[str, AiProviderRunner] = {
    "codex": CodexRunner(),
    "claude": ClaudeRunner(),
    "deepseek": DeepSeekRunner(),
}
```

And extend `_provider_model_and_timeout`:

```python
def _provider_model_and_timeout(settings: Settings, provider: str) -> tuple[str, float]:
    if provider == "codex":
        return (
            settings.trade_insights_ai_model.strip(),
            settings.trade_insights_ai_timeout_seconds,
        )
    if provider == "claude":
        return (
            settings.trade_insights_ai_claude_model.strip(),
            settings.trade_insights_ai_claude_timeout_seconds,
        )
    if provider == "deepseek":
        return (
            settings.trade_insights_ai_deepseek_model.strip(),
            settings.trade_insights_ai_deepseek_timeout_seconds,
        )
    raise TradeInsightsAiRunnerError(f"unknown provider {provider!r}")
```

- [ ] **Step 6: Add scheduler worker role**

In `src/uw_scan/worker/scheduler.py`:

```python
WorkerGroup = Literal["uw", "massive", "ai", "ai-codex", "ai-claude", "ai-deepseek"]
WORKER_ROLES: set[str] = {
    "all",
    "uw",
    "massive",
    "ai",
    "ai-codex",
    "ai-claude",
    "ai-deepseek",  # NEW
}
```

Update the error-message strings on lines 91 and 119:

```python
"UW_SCAN_WORKER_ROLE must be one of: all, uw, massive, ai, "
"ai-codex, ai-claude, ai-deepseek "
```

In `_worker_groups`:

```python
    if role == "ai-deepseek":
        return {"ai-deepseek"}
```

Add a tick factory parallel to `_trade_insights_ai_tick_claude`:

```python
    def _trade_insights_ai_tick_deepseek() -> None:
        trade_insights_ai_tick(settings, provider_filter="deepseek")
```

Wire the factory into the role-routing section of `scheduler.py` (look for where `_trade_insights_ai_tick_claude` is registered — typically a `scheduler.add_job(...)` call gated on `"ai-claude" in groups` — and add the parallel `"ai-deepseek"` block).

- [ ] **Step 7: Run orchestrator dispatch test for DeepSeek + end-to-end mock**

Add to `tests/unit/worker/test_trade_insights_ai_orchestrator.py`:

```python
def test_orchestrator_dispatches_to_deepseek_runner_for_provider_deepseek():
    from uw_scan.worker.jobs.trade_insights_ai import RUNNERS
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    assert "deepseek" in RUNNERS
    assert isinstance(RUNNERS["deepseek"], DeepSeekRunner)


def test_orchestrator_threads_deepseek_runner_flags_through_schema_and_validator(monkeypatch):
    """End-to-end check (no DB, no network): when a `provider='deepseek'` row
    is claimed, the orchestrator must call `trade_insights_ai_output_schema`
    with `strict=True, strip_lookaround_regex=True` and call
    `validate_trade_insights_ai_outcome` with `lenient=False`. If anyone
    re-introduces a `row_provider == "..."` branch, this test catches it."""
    from uw_scan.worker.jobs import trade_insights_ai as orchestrator
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    schema_calls: list[dict] = []
    validate_calls: list[dict] = []

    def fake_schema(*, strict, strip_lookaround_regex):
        schema_calls.append({"strict": strict, "strip": strip_lookaround_regex})
        return {"type": "object"}

    def fake_validate(outcome, payload, *, produced_at, lenient):
        validate_calls.append({"lenient": lenient})
        # Minimum viable parsed outcome — the orchestrator only needs
        # .model_dump(mode="json"). Use a MagicMock.
        from unittest.mock import MagicMock
        m = MagicMock()
        m.model_dump.return_value = {"ticker": "TEST"}
        return m

    monkeypatch.setattr(orchestrator, "trade_insights_ai_output_schema", fake_schema)
    monkeypatch.setattr(orchestrator, "validate_trade_insights_ai_outcome", fake_validate)
    monkeypatch.setattr(orchestrator, "render_trade_insights_ai_markdown", lambda _o: "md")
    monkeypatch.setattr(orchestrator, "build_trade_insights_ai_prompt", lambda _p: "prompt")

    # Plumbing for the DB layer — patch _repo to return a stub that walks the
    # happy-path methods. The shape mirrors how existing orchestrator tests
    # (if any) stub the repo; if not, build the stub fresh.
    from unittest.mock import MagicMock
    fake_row = {
        "analysis_id": "00000000-0000-0000-0000-000000000001",
        "provider": "deepseek",
        "prompt_version": orchestrator.PROMPT_VERSION,
        "analysis_input_jsonb": {"ticker": "TEST", "run_id": "r1", "trade_insights_input_hash": "h"},
    }
    fake_repo = MagicMock()
    fake_repo.claim_next_trade_insight_ai_analysis.return_value = fake_row
    fake_repo.upsert_heartbeat.return_value = None
    monkeypatch.setattr(orchestrator, "_repo", lambda settings: fake_repo)

    # Stub the runner so we don't hit the network — return a canned outcome dict.
    monkeypatch.setattr(
        DeepSeekRunner,
        "run",
        lambda self, prompt, schema, *, model, timeout_seconds, max_output_bytes:
            __import__("uw_scan.worker.jobs.trade_insights_ai_runners", fromlist=["RunnerResult"]).RunnerResult(
                outcome={"ticker": "TEST"},
                resolved_model="deepseek-v4-pro",
            ),
    )

    from uw_scan.config import Settings
    settings = Settings.from_env()
    handled = orchestrator.trade_insights_ai_tick(settings, provider_filter="deepseek")

    assert handled is True
    # Schema must have been generated with DeepSeek's contract flags.
    assert all(c == {"strict": True, "strip": True} for c in schema_calls)
    # Validator must have been called with lenient=False (DeepSeek doesn't
    # use the Claude lenient coercer).
    assert validate_calls and all(c["lenient"] is False for c in validate_calls)
```

```bash
uv run pytest tests/unit/worker/test_trade_insights_ai_orchestrator.py -q
```

Expected: PASS. If the orchestrator test fixtures don't support stubbing `_repo` cleanly (e.g., because `_repo` is called multiple times and the second call needs different behavior), refactor the orchestrator slightly so `_repo` is overridable in tests — but keep the production code identical to today.

- [ ] **Step 8: Update repo-root CLAUDE.md and AGENTS.md**

The standing rule is "**AGENTS.md** still lives at the root for Codex; keep both files in sync when policy changes." This PR adds a third provider with new env vars and a new worker role — that's a policy change.

In `CLAUDE.md` (project root), find the "Trade Insights AI (V1.5)" section and:

1. Update the opening sentence: replace "Local Codex CLI and Claude CLI are the two model execution paths" with "Local Codex CLI, Claude CLI, and DeepSeek HTTP API are the three model execution paths". Add one sentence noting DeepSeek uses function-calling with `strict: true` (Beta) and reads `DEEPSEEK_API_KEY` from the worker env.
2. Add an "Environment (DeepSeek):" block parallel to the Codex / Claude blocks:

```markdown
Environment (DeepSeek):

- `TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED` — DeepSeek kill switch; default **true**
- `TRADE_INSIGHTS_AI_DEEPSEEK_MODEL` — optional DeepSeek model alias; blank → `deepseek-v4-pro` (top-tier thinking variant — quality default). Set to `deepseek-v4-flash` for the cheap/fast non-thinking alternative. The legacy `deepseek-chat` / `deepseek-reasoner` names still resolve (aliased to v4-flash's non-thinking / thinking modes) but are deprecated.
- `TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS` — DeepSeek HTTP timeout, default 300
- `TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT` — parallel workers claiming deepseek rows, default 2. **Lower to 1 if DeepSeek 429s** — DeepSeek's rate ceiling is provider-side and may be below your codex/claude ceilings.
- `DEEPSEEK_API_KEY` — bearer token; read in-process at call time (no subprocess env-allow-list dance)

**Worker env rotation:** APScheduler workers freeze their env at fork time. Rotating `DEEPSEEK_API_KEY` (or any env above) requires restarting the `ai-deepseek` worker processes — the running process will keep using the boot-time value. The same applies to `ai-codex` / `ai-claude` workers.
```

3. Update the "Worker roles:" sentence: add `ai-deepseek` to the list alongside `ai-codex` and `ai-claude`. Add one sentence: "The DeepSeek runner is in-process HTTP (`httpx`), not a subprocess — `_runner_child_env` does not apply, but `DEEPSEEK_API_KEY` is still scoped to the worker process and not echoed in error messages."
4. Update the "Trade Insights AI — UI tabs" row in the "Where to look first" table: change "[Codex] [Claude] tabs" to "[Codex] [Claude] [DeepSeek planned] tabs — the DeepSeek tab is a follow-up PR; backend queues `provider='deepseek'` rows today but the UI does not yet surface them."

In `AGENTS.md` (project root), apply the **same edits** verbatim (the two files mirror each other for policy content).

Verify the mirror is intact:

```bash
diff <(grep -A 40 "Trade Insights AI" CLAUDE.md | head -60) \
     <(grep -A 40 "Trade Insights AI" AGENTS.md | head -60)
```

Expected: empty diff for the Trade-Insights-AI sections (modulo any pre-existing drift unrelated to this PR).

- [ ] **Step 9: Confirm full touched-test pass**

```bash
uv run pytest tests/test_trade_insights_ai.py tests/unit/worker/test_trade_insights_*runner.py tests/unit/worker/test_trade_insights_ai_*.py tests/unit/test_config_trade_insights_ai.py tests/unit/reports/test_trade_insights_ai_prompt_assembly.py -q
```

Expected: all pass.

- [ ] **Step 10: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/config.py \
        src/uw_scan/worker/jobs/trade_insights_ai.py \
        src/uw_scan/worker/scheduler.py \
        tests/unit/test_config_trade_insights_ai.py \
        tests/unit/worker/test_trade_insights_ai_orchestrator.py \
        CLAUDE.md \
        AGENTS.md
git commit -m "feat(trade-insights-ai): register DeepSeek runner + ai-deepseek worker role + settings + docs"
```

---

## Task 9a: API router enqueue + `find_latest` dict + health endpoint

Background: register-in-RUNNERS (Task 9) makes the orchestrator dispatch to DeepSeek, but the upstream API + downstream read path are still 2-provider-shaped. Without this task, the operator can never queue a `provider='deepseek'` row from the UI / API and `/latest` never surfaces a DeepSeek result.

**Scope decision for v1 (HOLD scope, document explicitly):** DeepSeek participates in enqueue + persistence + /latest, **but** the cross-provider consensus signal (`_compute_provider_consensus(codex, claude)` at `api/routers/trade_insights.py:338-347`) stays a 2-way codex-vs-claude comparison. Generalizing consensus to 3 providers (majority vote? pairwise agreement?) is a separate scoping question and explicitly out of scope for this PR. The function docstring must say so.

**Files:**
- Modify: `src/uw_scan/api/routers/trade_insights.py`
- Modify: `src/uw_scan/storage/trade_insights_ai.py`
- Modify: `src/uw_scan/api/routers/health.py`
- Possibly modify: `src/uw_scan/models/trade_insights_ai.py` (if `TradeInsightAiLatestPair` has fixed codex/claude fields rather than a flexible map)
- Modify: `tests/integration/api/test_trade_insights_router.py` (if it exists; otherwise create)

- [ ] **Step 1: Add `deepseek` field to `TradeInsightAiLatestPair` (Path A — resolved during plan review)**

`models/trade_insights_ai.py:552-566` declares the model with FIXED fields:

```python
class TradeInsightAiLatestPair(TradeInsightAiBase):
    current_prompt_version: str
    current_prompt_label: str | None = None
    codex: TradeInsightAiAnalysisResponse | None = None
    claude: TradeInsightAiAnalysisResponse | None = None
    provider_consensus: TradeInsightAiProviderConsensus = Field(
        default_factory=TradeInsightAiProviderConsensus
    )
```

Add a sibling `deepseek` field with `None` default (preserves backward compat for clients that don't know about deepseek yet):

```python
class TradeInsightAiLatestPair(TradeInsightAiBase):
    """GET /latest response — null per provider when no succeeded row exists.

    v5.2: provider_consensus is computed at read time by comparing the
    two providers' headline fields whenever both have succeeded. The
    UI surfaces consensus_grade + actionable_disagreement above the
    [Codex] [Claude] tabs as a quality signal.

    v5.3 (deepseek-decoupling, 2026-05-28): adds the deepseek slot.
    DeepSeek surfaces in /latest but DOES NOT participate in
    provider_consensus — that remains a 2-way codex-vs-claude comparison
    (see _compute_provider_consensus docstring for the scope decision).
    """

    current_prompt_version: str
    current_prompt_label: str | None = None
    codex: TradeInsightAiAnalysisResponse | None = None
    claude: TradeInsightAiAnalysisResponse | None = None
    deepseek: TradeInsightAiAnalysisResponse | None = None  # NEW
    provider_consensus: TradeInsightAiProviderConsensus = Field(
        default_factory=TradeInsightAiProviderConsensus
    )
```

**OpenAPI consequence:** the snapshot will gain one optional `deepseek` field on `TradeInsightAiLatestPair`. Combined with the four enum widenings from Task 7a, regenerate the snapshot at Task 7a Step 10 (or re-regenerate here if Task 9a runs after Task 7a's snapshot commit landed).

Also update the existing test at `tests/unit/test_models_trade_insights_ai_provider.py:68` (`test_latest_pair_allows_null_per_provider`) to also assert `pair.deepseek is None` by default.

- [ ] **Step 2: Widen storage `find_latest_*_per_provider`**

In `src/uw_scan/storage/trade_insights_ai.py` (around line 306):

```python
# Before:
out: dict[str, dict[str, Any] | None] = {"codex": None, "claude": None}

# After:
out: dict[str, dict[str, Any] | None] = {
    "codex": None,
    "claude": None,
    "deepseek": None,
}
```

And update the docstring (line 291):

```python
"""Latest terminal-state row per known provider as a keyed dict.

Output shape: {"codex": row|None, "claude": row|None, "deepseek": row|None}.
Returns the most recent succeeded OR failed row per provider; succeeded wins
when both exist (the v1 docstring said "two providers" — widened to three
for the DeepSeek addition).
"""
```

- [ ] **Step 3: Add `deepseek` enqueue block to the router**

In `src/uw_scan/api/routers/trade_insights.py` around lines 297-328 (after the Claude block at line 328), add a third block that mirrors the structure:

```python
    if settings.trade_insights_ai_deepseek_enabled and (
        provider_filter is None or "deepseek" in provider_filter
    ):
        model_label = (
            settings.trade_insights_ai_deepseek_model.strip() or "deepseek-default"
        )
        stubs.append(
            _enqueue_one_provider(
                repo=repo,
                ticker=ticker,
                request_id=request_id,
                run_id=run_id,
                trade_insights_input_hash=trade_insights_input_hash,
                analysis_input=analysis_input,
                analysis_input_hash=analysis_input_hash,
                model=model_label,
                provider="deepseek",
                prompt_text=prompt_text,
                output_schema=output_schema,
                produced_at=produced_at,
                prompt_payload=prompt_payload,
            )
        )
```

Use the EXACT argument list of `_enqueue_one_provider` as it appears today (the snippet above is illustrative; copy the kwarg names from the codex/claude block — they're identical for all providers).

- [ ] **Step 4: Update the disabled-all gate**

The router has a guard at ~line 258:

```python
settings.trade_insights_ai_enabled or settings.trade_insights_ai_claude_enabled
```

Widen to:

```python
(
    settings.trade_insights_ai_enabled
    or settings.trade_insights_ai_claude_enabled
    or settings.trade_insights_ai_deepseek_enabled
)
```

- [ ] **Step 5: Update the `/latest` unpack**

At ~lines 443-444:

```python
# Before:
codex = _row_to_ai_response(pair["codex"]) if pair["codex"] else None
claude = _row_to_ai_response(pair["claude"]) if pair["claude"] else None

# After:
codex = _row_to_ai_response(pair["codex"]) if pair["codex"] else None
claude = _row_to_ai_response(pair["claude"]) if pair["claude"] else None
deepseek = _row_to_ai_response(pair["deepseek"]) if pair["deepseek"] else None
```

Then pass `deepseek=deepseek` into the `TradeInsightAiLatestPair(...)` constructor call wherever `codex=codex, claude=claude` is passed today. Grep `api/routers/trade_insights.py` for `TradeInsightAiLatestPair(` to find the construction site(s).

- [ ] **Step 6: Document the consensus scope decision**

In `_compute_provider_consensus(codex, claude)` (around line 338-347), update the docstring:

```python
def _compute_provider_consensus(
    codex: TradeInsightAiAnalysisResponse | None,
    claude: TradeInsightAiAnalysisResponse | None,
) -> TradeInsightAiProviderConsensus:
    """v5.2: cross-provider agreement signal computed at GET /latest time.

    DELIBERATELY 2-PROVIDER (v1 DeepSeek scope decision, 2026-05-28): consensus
    stays a codex-vs-claude comparison even after deepseek was added as a third
    provider. Extending to 3-way consensus (majority vote? pairwise
    agreement?) is a separate scoping question — DeepSeek queues, persists,
    and surfaces in /latest, but does NOT vote.
    ...
    """
```

- [ ] **Step 7: Add `deepseek` to the health heartbeat enumeration**

In `src/uw_scan/api/routers/health.py` (lines 373, 380 are codex+claude). Add a third entry for `provider="deepseek"`:

```python
# After the existing claude heartbeat block:
        _heartbeat_block(
            repo,
            settings=settings,
            provider="deepseek",
            # ...same kwarg shape as codex / claude blocks
        ),
```

Cite the exact kwarg names by reading the existing claude block first — don't paraphrase. The block builder is reused, so the only differences are `provider="deepseek"` and (potentially) `worker_count=settings.trade_insights_ai_deepseek_worker_count`.

- [ ] **Step 8: Run the touched-test set**

```bash
uv run pytest \
  tests/integration/storage/ \
  tests/unit/test_models_trade_insights_ai_provider.py \
  tests/unit/worker/test_trade_insights_ai_orchestrator.py \
  tests/integration/api/ \
  -q -k "trade_insight"
```

Expected: all pass. If the OpenAPI snapshot test fails because Path A added a new optional field, regenerate the snapshot per Task 7a Step 10.

- [ ] **Step 9: Commit (milestone, if authorized)**

```bash
git add src/uw_scan/api/routers/trade_insights.py \
        src/uw_scan/storage/trade_insights_ai.py \
        src/uw_scan/api/routers/health.py \
        src/uw_scan/models/trade_insights_ai*.py \
        tests/integration/api/openapi.snapshot.json 2>/dev/null || true
git status   # Confirm only the expected files are staged
git commit -m "feat(trade-insights-ai): enqueue + /latest + health for deepseek (consensus stays 2-way)"
```

---

## Task 10: Update `scripts/dev.sh` (developer convenience)

**Files:**
- Modify: `scripts/dev.sh`

- [ ] **Step 1: Add `ai-deepseek` panes**

Open `scripts/dev.sh`. Find the `concurrently` invocation (~line 24) and add two `ai-deepseek` panes mirroring the `ai-claude` pair. Example diff:

```diff
-  -n next,api,uw-0,uw-1,massive-0,massive-1,ai-codex-0,ai-codex-1,ai-claude-0,ai-claude-1,massive-ws \
+  -n next,api,uw-0,uw-1,massive-0,massive-1,ai-codex-0,ai-codex-1,ai-claude-0,ai-claude-1,ai-deepseek-0,ai-deepseek-1,massive-ws \
```

And add two new worker-launch lines after the `ai-claude` pair (around lines 34-35):

```bash
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-deepseek UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-deepseek UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
```

- [ ] **Step 2: Smoke-check the script syntactically (don't run; it needs the full dev stack)**

```bash
bash -n scripts/dev.sh
```

Expected: silent (parse OK).

- [ ] **Step 3: Commit (milestone, if authorized)**

```bash
git add scripts/dev.sh
git commit -m "chore(dev): add ai-deepseek worker panes to dev.sh"
```

---

## Task 11: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full pytest run for the affected packages**

```bash
uv run pytest \
  tests/test_trade_insights_ai.py \
  tests/unit/reports/ \
  tests/unit/worker/ \
  tests/unit/test_config_trade_insights_ai.py \
  tests/unit/test_models_trade_insights_ai_provider.py \
  tests/integration/storage/test_trade_insights_ai_provider_check.py \
  tests/integration/api/test_openapi_snapshot.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: OpenAPI snapshot — explicit-contract-change verification**

This PR **deliberately widens** the API contract (`TradeInsightAiProvider` Literal gains `"deepseek"`; one optional `deepseek` field added to `TradeInsightAiLatestPair` if you took Path A in Task 9a). The standing rule "API model refactors preserve contract identity unless the PR is explicitly an API contract change" qualifies this PR as an explicit contract change.

Verify the snapshot delta is ONLY the expected additions:

```bash
git diff main..HEAD -- tests/integration/api/openapi.snapshot.json | grep -E '^[-+]' | grep -v '^[-+]{3}' | head -40
```

Expected diff:
- 4× lines adding `+        "deepseek",` to the `["codex","claude"]` enum arrays for: `TradeInsightAiAnalysisRequest.providers.items`, `TradeInsightAiAnalysisResponse.provider`, `TradeInsightAiAnalysisStub.provider`, `TradeInsightAiPriorRow.provider`.
- (Path A only) New optional `deepseek` property on `TradeInsightAiLatestPair`.
- (Possibly) updated default value or description strings on `TradeInsightAiAnalysisResponse.provider` if the default `"codex"` documentation changes.

**No other diffs.** If any unrelated field appears in the delta, stop and investigate.

- [ ] **Step 2b: Regenerate web types after OpenAPI changes**

```bash
cd web && npm run gen:types && cd ..
git status -- web/lib/types.ts
```

Expected: `web/lib/types.ts` may show small additions reflecting the new optional field / widened enum. Commit those — generated types must travel with the contract change.

- [ ] **Step 3: Live smoke test (optional, requires `DEEPSEEK_API_KEY`)**

Only if `DEEPSEEK_API_KEY` is set in the shell:

```bash
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY \
TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED=true \
UW_SCAN_WORKER_ROLE=ai-deepseek UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=1 \
uv run python -c "from uw_scan.config import Settings; from uw_scan.worker.jobs.trade_insights_ai import trade_insights_ai_tick; s = Settings.from_env(); print('claimed:', trade_insights_ai_tick(s, provider_filter='deepseek'))"
```

Expected: `claimed: False` if there's no queued `provider='deepseek'` row, or `claimed: True` after queuing one via the API. If the worker exits with a `TradeInsightsAiRunnerError` from DeepSeek (network/auth/etc.), capture stderr.

If no `DEEPSEEK_API_KEY` available: **skip and document** in the PR description that live smoke was deferred to the user.

- [ ] **Step 4: Verify the orchestrator has zero `row_provider` string equality checks**

```bash
grep -n 'row_provider ==\|row_provider !=' src/uw_scan/worker/jobs/trade_insights_ai.py
```

Expected: no matches. (Note: `if row_provider not in RUNNERS:` is allowed — that's a key lookup, not a name-keyed branch on behavior.)

- [ ] **Step 5: Stage final state for PR review**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat
```

Expected: tidy commit history walking through Tasks 2-10; diff scoped to the files in the File Structure table above.

- [ ] **Step 6: Open PR (per the standing rule — no direct merge to main)**

```bash
git push -u origin feat/trade-insights-ai-deepseek
gh pr create --title "feat(trade-insights-ai): model-independent prompt + DeepSeek provider" --body "$(cat <<'EOF'
## Summary
- Hoists Claude's `_JSON_ONLY_SYSTEM_PROMPT` into a shared `CONTRACT_PROMPT` so every provider (Codex, Claude, DeepSeek) sees the same contract.
- Replaces `if provider == "claude"` branches in the orchestrator with runner-declared class attributes (`schema_strict`, `strip_lookaround_regex`, `requires_lenient_validation`).
- Splits the schema generator's `strict` arg into two orthogonal flags so DeepSeek can pick strict + lookaround-strip without re-implying Claude's lenient mode.
- Adds DeepSeek as a third provider via in-process httpx HTTP runner using function-calling with `strict: true` (Beta), per [DeepSeek docs](https://api-docs.deepseek.com/guides/function_calling).

## Out of scope (follow-up)
- UI: third `[DeepSeek]` tab in `TradeInsightsAiAnalysisPanel.tsx`.
- Prompt content improvements drawing from `~/projects/trade-skills` pitfalls.
- Lenient-coercer (`_coerce_claude_outcome_dict`) remains Claude-only.

## Test plan
- [ ] `uv run pytest tests/test_trade_insights_ai.py tests/unit/reports/ tests/unit/worker/ tests/unit/test_config_trade_insights_ai.py -q` passes locally.
- [ ] No `row_provider == "claude"` / `row_provider != "claude"` branches remain in the orchestrator.
- [ ] CI green.
- [ ] (Optional) Live smoke against DeepSeek API with `DEEPSEEK_API_KEY` set — defer to operator.
EOF
)"
```

Expected: PR URL returned. Wait for CI before merging.

---

## Self-Review Notes (run before declaring plan done)

1. **Spec coverage:** Every site in the "Current provider coupling" table from the design discussion is addressed: site 1 → Tasks 2+4, site 2 → Tasks 5+7, site 3 → Tasks 6+7, site 4 → Task 5, site 5 → Task 3. DeepSeek runner addition → Tasks 8+9+10.

2. **Placeholder scan:** No `TBD`, `TODO`, or "fill in later" in any task. Every code block is paste-ready except for the explicit "paste lines 135-289" step in Task 2 (where the line numbers are stated and the boundary is precise). The plan flags exact line numbers as drift-prone and instructs to re-read before pasting.

3. **Type consistency:**
   - `schema_strict`, `strip_lookaround_regex`, `requires_lenient_validation` — used identically across Tasks 5, 6, 7, 8, 9.
   - `trade_insights_ai_output_schema(*, strict, strip_lookaround_regex)` — signature matches in Tasks 5, 7, 8.
   - `DeepSeekRunner.name = "deepseek"` matches `RUNNERS["deepseek"]` and `provider_filter="deepseek"` and `WorkerGroup`'s `"ai-deepseek"` literal.
   - `TRADE_INSIGHTS_AI_DEEPSEEK_*` env-var prefix matches `Settings.trade_insights_ai_deepseek_*` attr prefix.

4. **One open soft-spot:** Task 7's orchestrator test assumes a way to inject a synthetic runner. If the existing test fixtures around `trade_insights_ai_tick` don't support injection cleanly, the implementer may need to refactor the dispatch path slightly to make `RUNNERS` overridable in tests (e.g., a module-level constant referenced via attribute access, not a frozen import). This is a small ergonomic risk — flag during execution if it bites.
