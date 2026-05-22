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


_JSON_ONLY_SYSTEM_PROMPT = (
    "You must emit a single raw JSON object that EXACTLY matches the supplied "
    "--json-schema. The schema enumerates every property name at every nesting "
    "level — use those exact field names. Every property listed in the schema "
    "is required at the level it appears at; do not omit any. "
    "additionalProperties is false at every level — do not invent extra fields "
    "the schema does not list. If you have a value that does not map to a "
    "schema field, drop it rather than adding a new key. "
    "Do not write a Markdown report. Do not wrap the JSON in code fences. "
    "Do not add commentary before or after the JSON. Use the StructuredOutput "
    "tool if available; otherwise emit the JSON object as the entire response."
)


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
