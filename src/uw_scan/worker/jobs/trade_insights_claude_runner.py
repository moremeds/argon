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

# Sentinel distinguishing "stdout was non-empty but not parseable JSON"
# from "stdout was empty" (None) — both need different error messages.
_JSON_DECODE_FAILED = object()


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


class ClaudeRunner:
    """Local `claude --print` runner. Reads keychain OAuth (no env var)."""

    name = "claude"
    schema_strict = False
    strip_lookaround_regex = False
    requires_lenient_validation = True

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

            stdout_bytes = completed.stdout.encode("utf-8")
            if len(stdout_bytes) > max_output_bytes:
                raise TradeInsightsAiRunnerError(
                    f"claude --print output exceeded {max_output_bytes} bytes"
                )

            # Parse the envelope BEFORE the returncode short-circuit. On
            # transient API errors (socket closures, gateway timeouts) claude
            # exits non-zero AND prints a complete result event with
            # is_error=true. Surfacing the readable `result` message via the
            # existing is_error handler (below) keeps error_message short
            # enough for the UI's red banner; falling through to
            # _format_runner_failure here would dump the full JSON envelope
            # as the user-visible error.
            parsed_stdout: Any
            try:
                parsed_stdout = (
                    json.loads(completed.stdout) if completed.stdout else None
                )
            except json.JSONDecodeError as exc:
                _ = repr(exc)
                parsed_stdout = _JSON_DECODE_FAILED

            if completed.returncode != 0 and not isinstance(parsed_stdout, list):
                # Non-zero exit with no usable envelope: fall back to the
                # stderr/stdout tail. This covers auth/launch failures that
                # never produce the JSON array (e.g. "Not logged in").
                detail = _format_runner_failure(completed.stderr, completed.stdout)
                raise TradeInsightsAiRunnerError(
                    f"claude --print failed with exit {completed.returncode}: {detail}"
                )

            if parsed_stdout is _JSON_DECODE_FAILED or parsed_stdout is None:
                raise TradeInsightsAiRunnerError(
                    "claude --print stdout was not valid JSON"
                )

            if not isinstance(parsed_stdout, list):
                raise TradeInsightsAiRunnerError(
                    "claude --print stdout expected JSON array of events"
                )

            events = parsed_stdout

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
            if completed.returncode != 0:
                result_text = result_event.get("result") or result_event.get("message")
                detail = _format_runner_failure(
                    completed.stderr,
                    str(result_text) if result_text is not None else None,
                )
                raise TradeInsightsAiRunnerError(
                    f"claude --print failed with exit {completed.returncode}: {detail}"
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
