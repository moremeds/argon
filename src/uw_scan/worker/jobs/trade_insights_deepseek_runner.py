"""DeepSeek HTTP runner — implements AiProviderRunner via DeepSeek's
OpenAI-compatible /chat/completions endpoint.

Unlike Codex/Claude, this runner is in-process HTTP (httpx) rather than a
subprocess. DeepSeek's API is OpenAI-compatible in shape, but its
structured-output story is different: response_format only supports
{type: "json_object"} (no strict json_schema). The schema-enforcement path
is function-calling with strict:true (Beta) — define one tool whose
parameters is the TradeInsightAiOutcome schema, force tool_choice to that
tool, and DeepSeek validates server-side.

Docs:
- Create Chat Completion:
  https://api-docs.deepseek.com/api/create-chat-completion
- Function calling + strict mode (Beta):
  https://api-docs.deepseek.com/guides/function_calling
- JSON mode (response_format=json_object only):
  https://api-docs.deepseek.com/guides/json_mode

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
            raise TradeInsightsAiRunnerError(
                "deepseek response JSON was not an object "
                f"(got {type(envelope).__name__})"
            )

        choices = envelope.get("choices") or []
        if not choices:
            raise TradeInsightsAiRunnerError("deepseek response had no choices[]")
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
