"""DeepSeek HTTP runner — implements AiProviderRunner via DeepSeek's
OpenAI-compatible /chat/completions endpoint.

Unlike Codex/Claude, this runner is in-process HTTP (httpx) rather than a
subprocess. DeepSeek's API is OpenAI-compatible in shape, but its
structured-output story is different: response_format only supports
{type: "json_object"} (no strict json_schema). The schema-enforcement
path is function-calling with strict:true (Beta) — define one tool
whose parameters is the TradeInsightAiOutcome schema and DeepSeek
validates server-side.

Two runtime constraints discovered during smoke testing — both encoded
in the request body below:

1. **`thinking: {type: disabled}`.** v4-pro defaults to thinking-mode
   ON, but DeepSeek's API rejects `tool_choice` with HTTP 400
   "Thinking mode does not support this tool_choice" in that state.
   Forcing thinking off lifts the restriction and keeps v4-pro using
   its pro architecture (just without the reasoning_content phase).

2. **`stream: true` + SSE parsing.** Non-streaming requests with our
   ~350 KB trade-analysis prompts trigger a server-side ~60 s
   compute-and-connection cap on DeepSeek's side, producing
   RemoteProtocolError "peer closed connection without sending complete
   message body" before any response is emitted. Streaming bypasses
   this because the server starts emitting tokens immediately and the
   connection stays alive through the full generation. We reassemble
   the `tool_calls[0].function.arguments` string from delta chunks.

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
            "thinking": {"type": "disabled"},
            "stream": True,
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

        # Accumulators populated as SSE chunks arrive.
        emitted_tool_name: str | None = None
        arguments_chunks: list[str] = []
        resolved_model: str | None = None
        finish_reason: str | None = None
        total_arg_bytes = 0

        try:
            with httpx.Client() as client:
                with client.stream(
                    "POST",
                    DEEPSEEK_CHAT_COMPLETIONS_URL,
                    json=body,
                    headers=headers,
                    timeout=timeout_seconds,
                ) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        # response.read() may be necessary before .text on a
                        # stream context — read defensively, truncate the
                        # body to avoid leaking secrets/full prompt in logs.
                        body_preview = ""
                        try:
                            body_preview = response.read().decode(
                                "utf-8", errors="replace"
                            )[:500]
                        except Exception as read_exc:
                            logger.debug(
                                "deepseek error-body read failed: %s",
                                repr(read_exc),
                            )
                        raise TradeInsightsAiRunnerError(
                            f"deepseek HTTP {response.status_code}: {body_preview}"
                        ) from exc

                    for raw_line in response.iter_lines():
                        if not raw_line:
                            continue
                        if not raw_line.startswith("data:"):
                            continue
                        payload = raw_line[len("data:") :].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError as exc:
                            raise TradeInsightsAiRunnerError(
                                "deepseek stream emitted non-JSON SSE chunk"
                            ) from exc
                        if not isinstance(event, dict):
                            raise TradeInsightsAiRunnerError(
                                "deepseek stream SSE chunk was not an object "
                                f"(got {type(event).__name__})"
                            )
                        resolved_model = event.get("model") or resolved_model
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        for call_delta in delta.get("tool_calls") or []:
                            fn = call_delta.get("function") or {}
                            name = fn.get("name")
                            if name:
                                if (
                                    emitted_tool_name is not None
                                    and emitted_tool_name != name
                                ):
                                    raise TradeInsightsAiRunnerError(
                                        "deepseek emitted two distinct tool "
                                        f"names {emitted_tool_name!r} vs "
                                        f"{name!r}"
                                    )
                                emitted_tool_name = name
                            arg_chunk = fn.get("arguments")
                            if arg_chunk:
                                total_arg_bytes += len(arg_chunk.encode("utf-8"))
                                if total_arg_bytes > max_output_bytes:
                                    raise TradeInsightsAiRunnerError(
                                        "deepseek tool-call arguments "
                                        f"exceeded {max_output_bytes} bytes"
                                    )
                                arguments_chunks.append(arg_chunk)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except httpx.TimeoutException as exc:
            raise TradeInsightsAiRunnerError(
                f"deepseek HTTP timed out after {timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise TradeInsightsAiRunnerError(
                f"deepseek HTTP transport error: {exc!r}"
            ) from exc

        if emitted_tool_name is None:
            raise TradeInsightsAiRunnerError(
                "deepseek stream ended without any tool_calls — model did "
                "not emit structured output despite tool_choice forcing."
            )
        if emitted_tool_name != DEEPSEEK_TOOL_NAME:
            raise TradeInsightsAiRunnerError(
                "deepseek emitted unexpected tool name "
                f"{emitted_tool_name!r} (expected {DEEPSEEK_TOOL_NAME!r})"
            )
        if finish_reason and finish_reason not in ("tool_calls", "stop"):
            logger.warning(
                "deepseek stream finished with reason=%s (continuing)",
                finish_reason,
            )

        arguments = "".join(arguments_chunks)
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

        resolved = resolved_model or effective_model or "deepseek-default"
        return RunnerResult(outcome=parsed, resolved_model=resolved)
