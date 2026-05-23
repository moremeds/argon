"""Claude CLI runner — implements AiProviderRunner via `claude --print`.

Uses Claude Code's OAuth keychain auth (the operator's existing subscription).
Tools, slash-commands, MCP, session-persistence are all disabled so the
subprocess is pure prompt-in / JSON-out.

Verified pre-flight quirks (do NOT change unless re-verified):

- `--mcp-config '{"mcpServers": {}}'` is required; bare `'{}'` is rejected
  with "Invalid input: expected record, received undefined".
- `--output-format json` emits a JSON *array* of events, not a single envelope.
  Walk the array: extract `model` from the system/init event, extract the
  outcome and `is_error` from the final result event.
- When `--json-schema` is passed, Claude Code >= 2.1 returns the parsed object
  on the result event's `structured_output` field (already a dict). The
  `result` string becomes prose ("Returned `{...}` via the StructuredOutput
  tool."). Older versions returned the JSON in `result` — fall back to that.
- `is_error: true` can coexist with `subtype: "success"` (e.g. billing errors).
  Treat is_error as the ground truth.
- ANTHROPIC_API_KEY in the parent env overrides OAuth keychain — _runner_child_env
  strips it.
- `--setting-sources ""` is required so user-level plugin/output-style settings
  do not bleed into the subprocess. Without it, a user with the explanatory
  output-style plugin enabled gets prose+insight blocks in `result` instead of
  the StructuredOutput tool firing, and `structured_output` stays empty.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    RunnerResult,
    TradeInsightsAiRunnerError,
    _format_runner_failure,
    _runner_child_env,
)


def _strip_markdown_fence(text: str) -> str:
    """Strip leading/trailing ```json ... ``` markdown fences if present.

    Claude does not always fire the StructuredOutput tool for large schemas
    even with --json-schema; in that case it returns the JSON inline as a
    Markdown code block. Strip the fences before json.loads.
    """
    s = text.strip()
    if not s.startswith("```"):
        return text
    first_newline = s.find("\n")
    if first_newline == -1:
        return text
    body = s[first_newline + 1 :]
    if body.endswith("```"):
        body = body[:-3]
    return body.rstrip()


_JSON_ONLY_SYSTEM_PROMPT = """\
Emit a single raw JSON object conforming EXACTLY to the supplied --json-schema. \
Use exact field names at every nesting level; additionalProperties is false \
everywhere. No markdown, no code fences, no prose before/after.

Populate EVERY field below; do not leave any blank, null, or set to placeholder \
strings like "n/a" or "unknown".

VOCAB MAPPINGS (the user prompt uses analyst vocabulary; translate to schema \
Literals on output):
- headline.trade_intent MUST be one of: "directional_swing", "range_income". \
  Default to "directional_swing" unless Step 4 of the decision order selected \
  range_income.
- headline.directional_bias MUST be one of: "LONG_DELTA", "SHORT_DELTA", "WAIT". \
  NEVER emit "bullish_continuation" or "long" or "bull" — those values belong \
  in underlying_path. The bias is the trader-facing directional gate.
- headline.entry_state MUST be one of: "ACTIVE", "CONDITIONAL", "NO_ENTRY".
- headline.underlying_path MUST be one of: "bullish_continuation", \
  "bearish_rejection", "downside_break", "pinned_no_directional_entry", \
  "data_insufficient".
- headline.dte_band MUST be one of: "momentum", "trend" (no "standard" — that \
  band exists in the candidate menu but the headline field is binary).
- headline.stance MUST be derived from headline.directional_bias for legacy \
  UI display: LONG_DELTA -> "bullish", SHORT_DELTA -> "bearish", WAIT -> "wait".
- headline.conviction MUST be exactly one of: "A", "B", "C", "D", "F".
- vrp_assessment.signal MUST be one of: "long_vol", "short_vol", "neutral".

MODE-STRUCTURE CONSISTENCY (HARD; validator will reject otherwise):
- If trade_intent == "directional_swing", preferred_expression.structure MUST \
  be in {long_call, long_put, call_debit_spread, put_debit_spread, \
  bull_call_spread, bear_put_spread, call_diagonal, put_diagonal, no_trade}. \
  iron_condor / iron_butterfly / strangle / credit_spread / calendar_spread \
  are BANNED as preferred when trade_intent=directional_swing.
- If trade_intent == "range_income", preferred_expression.structure MUST be \
  in {iron_condor, iron_butterfly, butterfly, calendar_spread, \
  call_credit_spread, put_credit_spread, no_trade}.

DELTA-MATCH (HARD):
- directional_bias = LONG_DELTA  -> preferred_expression structure MUST be \
  net-positive-delta (long_call, call_debit_spread, bull_call_spread, \
  call_diagonal).
- directional_bias = SHORT_DELTA -> net-negative-delta (long_put, \
  put_debit_spread, bear_put_spread, put_diagonal).
- directional_bias = WAIT        -> preferred_expression.structure = \
  "no_trade". The preferred_expression block then describes the CONDITIONAL \
  setup; the Scenarios section names the long/short expressions that would \
  activate.

REQUIRED STRINGS in headline (each substantive, one sentence; not a fragment):
- title, stance_label, conviction_label, top_reason, primary_risk, watch_trigger.

section_cards has THREE required keys: market_structure, volatility, \
flow_positioning. Each MUST have title, summary (>=1 sentence of real \
analysis), data_quality, and >=1 highlight or level with a real source_path \
from the supplied payload.

vrp_assessment is REQUIRED (not null). Provide {signal, title, summary, \
metrics, reason}. When data is incomplete, set signal="neutral" and explain \
in summary/reason.

preferred_expression: provide {idea_id, structure, title, why, \
status_observed, risk_flags_observed}. Also fill estimated_entry, \
max_profit_observed, max_loss_observed, reward_risk with concrete numeric \
strings ($X.XX or "0.YY") — not blanks. For trade_intent=range_income or \
directional_bias=WAIT, structure="no_trade" is acceptable; the other fields \
then describe the conditional setup.

dominant_read MUST have all four fields populated (headline, summary, \
confidence_commentary, data_quality_commentary).

guardrails defaults: {statuses_preserved: true, risk_flags_preserved: true, \
no_executable_recommendations: true} unless you changed a candidate.

scenario_cards: 3 items with case in {"upside","base","downside"}.

required_checks: 1-2 items. rejected_ideas: 3-5 items. At least one rejected \
idea MUST cite one of: horizon_mismatch (DTE outside 14-75), mode_mismatch \
(e.g. iron_condor rejected because trade_intent=directional_swing), or \
safety_override (short_strangle / risk_reversal: undefined-risk, blocked by \
project policy).

If the supplied deterministic payload truly lacks data for a required field, \
write a brief specific placeholder ("source_reconciliation status UNKNOWN; \
treating IV magnitude as relative-shape signal") rather than leaving blank.

Use the StructuredOutput tool if available; otherwise emit the JSON object \
as the entire response.
"""


class ClaudeRunner:
    """Local `claude --print` runner. Reads keychain OAuth (no env var)."""

    name = "claude"

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult:
        with tempfile.TemporaryDirectory(prefix="trade-insights-claude-") as tmp:
            tmpdir = Path(tmp)
            schema_json = json.dumps(schema, sort_keys=True)

            cmd = [
                "claude",
                "--print",
                "--tools",
                "",
                "--disable-slash-commands",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers": {}}',
                "--no-session-persistence",
                "--output-format",
                "json",
                "--json-schema",
                schema_json,
                "--setting-sources",
                "",
                "--append-system-prompt",
                _JSON_ONLY_SYSTEM_PROMPT,
                "--add-dir",
                str(tmpdir),
            ]
            if model:
                cmd.extend(["--model", model])

            try:
                completed = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    env=_runner_child_env(),
                    check=False,
                    cwd=str(tmpdir),
                )
            except subprocess.TimeoutExpired as exc:
                raise TradeInsightsAiRunnerError(
                    f"claude --print timed out after {timeout_seconds}s"
                ) from exc

            if completed.returncode != 0:
                detail = _format_runner_failure(completed.stderr, completed.stdout)
                raise TradeInsightsAiRunnerError(
                    f"claude --print failed with exit {completed.returncode}: {detail}"
                )

            stdout_bytes = completed.stdout.encode("utf-8")
            if len(stdout_bytes) > max_output_bytes:
                raise TradeInsightsAiRunnerError(
                    f"claude --print output exceeded {max_output_bytes} bytes"
                )

            try:
                events = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise TradeInsightsAiRunnerError(
                    "claude --print stdout was not valid JSON"
                ) from exc

            if not isinstance(events, list):
                raise TradeInsightsAiRunnerError(
                    "claude --print stdout expected JSON array of events"
                )

            init_event = next(
                (
                    e
                    for e in events
                    if isinstance(e, dict)
                    and e.get("type") == "system"
                    and e.get("subtype") == "init"
                ),
                None,
            )
            result_event = None
            for e in reversed(events):
                if isinstance(e, dict) and e.get("type") == "result":
                    result_event = e
                    break

            if result_event is None:
                raise TradeInsightsAiRunnerError(
                    "claude --print returned no result event: "
                    f"{_format_runner_failure(None, completed.stdout)}"
                )

            if result_event.get("is_error") is True:
                raise TradeInsightsAiRunnerError(
                    "claude --print API error "
                    f"(status={result_event.get('api_error_status')}): "
                    f"{result_event.get('result') or result_event.get('message') or 'unknown'}"
                )
            if result_event.get("subtype") != "success":
                raise TradeInsightsAiRunnerError(
                    f"claude --print returned non-success subtype "
                    f"{result_event.get('subtype')!r}: "
                    f"{_format_runner_failure(None, completed.stdout)}"
                )

            structured = result_event.get("structured_output")
            if isinstance(structured, dict):
                parsed: dict[str, Any] = structured
            else:
                result_str = result_event.get("result", "")
                candidate = _strip_markdown_fence(result_str)
                try:
                    fallback = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise TradeInsightsAiRunnerError(
                        "claude --print returned no structured_output and "
                        f"result field was not valid JSON: {result_str!r:.200}"
                    ) from exc
                if not isinstance(fallback, dict):
                    raise TradeInsightsAiRunnerError(
                        "claude --print result was not a JSON object"
                    )
                parsed = fallback

            resolved = (
                (init_event or {}).get("model")
                or result_event.get("model")
                or (model if model else "claude-default")
            )
            return RunnerResult(outcome=parsed, resolved_model=resolved)
