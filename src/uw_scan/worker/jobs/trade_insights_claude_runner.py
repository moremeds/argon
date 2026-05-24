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
import logging
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

logger = logging.getLogger(__name__)


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


def _extract_first_balanced_json_object(text: str) -> str | None:
    """Find the first balanced {...} substring in `text` and return it.

    Walks the string tracking brace depth so a JSON object embedded in
    prose ("Looking at TSLA, here's my analysis: {...} Hope this helps.")
    can be recovered when the StructuredOutput tool didn't fire.

    String literals (including escaped quotes) are skipped so braces
    inside JSON string values don't confuse the depth counter.
    Returns None if no balanced object is found.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    i = start
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        i += 1
    return None


def _try_parse_claude_text(text: str) -> Any:
    """Best-effort JSON recovery from a Claude result.text payload.

    Tries (in order): fenced markdown strip + parse, raw parse, and
    balanced-object extraction. Returns the parsed value on success,
    None on total failure.
    """
    if not text:
        return None
    candidate = _strip_markdown_fence(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.debug("fenced parse miss: %s", repr(exc))
    extracted = _extract_first_balanced_json_object(text)
    if extracted is None:
        return None
    try:
        return json.loads(extracted)
    except json.JSONDecodeError as exc:
        logger.debug("balanced parse miss: %s", repr(exc))
        return None


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
- headline.dte_band MUST be one of: "momentum", "standard", "trend". v5.1 \
  restored the standard band (31-44 DTE). The DTE of the chosen \
  preferred_entry_expiry MUST fall inside the band: momentum=[14,30], \
  standard=[31,44], trend=[45,75].
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
- title (v5.2: 10-20 words, naming bias + structure + trigger level + DTE band — \
  NOT the page title "NVDA AI Analysis"; example: \
  "NVDA SHORT_DELTA bear_put_spread fires on daily close below 215, 35 DTE standard band."),
- stance_label, conviction_label, top_reason, primary_risk, watch_trigger.

section_cards has THREE required keys: market_structure, volatility, \
flow_positioning. Each MUST have title, summary (>=1 sentence of real \
analysis), data_quality, and >=1 highlight or level with a real source_path \
from the supplied payload.

vrp_assessment is REQUIRED (not null). Provide {signal, title, summary, \
metrics, reason}. When data is incomplete, set signal="neutral" and explain \
in summary/reason.

preferred_expression: provide {idea_id, structure, title, why, \
status_observed, risk_flags_observed, strike_role, legs}. \
strike_role is a nested object with {long_leg_role, short_leg_role, \
trigger_level, target_level, invalid_level, trigger_source_path, \
target_source_path, invalid_source_path}. v5.2: trigger_level / \
target_level / invalid_level MUST be a NUMERIC PRICE STRING (e.g. "215" \
or "215.00") — NOT a dict, NOT a row object from the payload.

v5.3 LEGS REQUIREMENT (HARD): preferred_expression.legs is an array of \
option legs, each {option_type: "call"|"put", side: "long"|"short", \
strike: numeric, expiry: "YYYY-MM-DD"}. Required structures: \
bear_put_spread / put_debit_spread = 2 legs (long put + short put, \
long_strike > short_strike, same expiry); bull_call_spread / \
call_debit_spread = 2 legs (long call + short call, long_strike < \
short_strike, same expiry); put_credit_spread = 2 legs (short put + \
long put, short_strike > long_strike, same expiry, DEFINED-RISK); \
call_credit_spread = 2 legs (short call + long call, short_strike < \
long_strike, same expiry, DEFINED-RISK); long_call = 1 long call; \
long_put = 1 long put. NO NAKED SHORTS — every credit-spread family MUST \
include the protective long leg. no_trade / strategy_review can have \
legs=[].

v5.3 LEGS_ALIGN_WITH_TRIGGERS (HARD): for any spread, the long leg's \
strike MUST be within 2% of either entry_trigger.level or \
thesis_trigger.level. This binds the proposed spread to the trigger \
state machine.

For estimated_entry, max_profit_observed, max_loss_observed, reward_risk: \
if entry_state=CONDITIONAL and the trigger has NOT fired, set \
status_observed="strategy_review" with blanks or the placeholder string \
"Repriced post-trigger — observed pre-trigger numerics are reference only." \
v5.2 removed the "candidate_pre_trigger" escape hatch as dead code — \
under CONDITIONAL always use strategy_review. For trade_intent= \
range_income or directional_bias=WAIT, structure="no_trade" is \
acceptable; the other fields then describe the conditional setup.

v5.3 TRIGGER COMPONENTS (HARD): emit thesis_trigger, entry_trigger, and \
invalidation as TOP-LEVEL TriggerComponent blocks on the outcome (NOT \
inside preferred_expression). Each block has {level: numeric, meaning: \
short label, fired: bool, evidence_close: numeric, evidence_date: \
"YYYY-MM-DD", source_path: "tabs.market_structure.stock_history.rows[N].spot"}. \
thesis_trigger is the level that validates the spatial archetype \
(broken put_wall for support_breakdown, broken call_wall for \
breakout_continuation). entry_trigger is the level that signals the \
actual trade entry — often the long-leg strike. invalidation is the \
level that kills the thesis. For thesis/entry, fired=true requires a \
COMPLETED daily close that crossed `level` in the relevant direction; \
intraday spot is NOT sufficient. The two triggers MAY share the same \
level but their meaning strings MUST differ.

v5.3 ENTRY_STATE DERIVATION (HARD; mechanical, validator rejects \
mismatches): entry_state = ACTIVE iff thesis_trigger.fired AND \
entry_trigger.fired AND NOT invalidation.fired. entry_state = \
CONDITIONAL iff thesis_trigger.fired AND NOT entry_trigger.fired (or \
neither fired but the setup is otherwise valid). entry_state = NO_ENTRY \
iff invalidation.fired OR directional_bias=WAIT.

TRIGGER-STRIKE CONSISTENCY (HARD; validator will reject otherwise):
- For LONG_DELTA breakouts, the spread's short leg strike MUST be STRICTLY \
  GREATER than strike_role.trigger_level. A 425/430 bull_call_spread with \
  trigger_level=430 is rejected — the short call caps payoff at the \
  trigger. Move both legs up so short sits at the next target (e.g. 435 \
  second_magnet, 440 next call wall).
- For SHORT_DELTA downside breaks, the spread's short leg strike MUST be \
  STRICTLY LESS than trigger_level.

DTE-BAND CONSISTENCY (HARD; validator will reject otherwise):
- The chosen preferred_entry_expiry's DTE must be inside the band emitted \
  in headline.dte_band: momentum=[14,30], standard=[31,44], trend=[45,75].

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
                # Fallback chain when Claude skipped the StructuredOutput tool
                # (observed repeatedly on TSLA-shape payloads):
                #   1. strip markdown fences and json.loads the whole thing
                #   2. extract first balanced {…} block from prose-prefaced
                #      responses ("Looking at TSLA, here's my analysis: {…}")
                #   3. give up — but raise with the FULL result_str so the
                #      orchestrator can persist it to raw_outcome_jsonb.
                #      Truncated repr in the error message was insufficient
                #      to diagnose the v5.2/v5.3 TSLA drops.
                result_str = result_event.get("result", "")
                fallback = _try_parse_claude_text(result_str)
                if fallback is None:
                    preview = result_str[:200]
                    raise TradeInsightsAiRunnerError(
                        "claude --print returned no structured_output and "
                        "no parseable JSON object could be extracted from the "
                        f"result text (len={len(result_str)}, preview={preview!r}); "
                        f"full text: {result_str}"
                    )
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
