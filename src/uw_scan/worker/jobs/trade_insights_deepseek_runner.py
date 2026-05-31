"""DeepSeek HTTP runner — implements AiProviderRunner via DeepSeek's
OpenAI-compatible /chat/completions endpoint.

Configuration (canonical, as of 2026-05-29):

  thinking: {type: enabled}    # v4-pro's reasoning phase ON
  tool_choice: omitted          # model decides; v4-pro rejects forced
                                # tool_choice while thinking is enabled
  tools[0].strict: true         # server-side schema validation
  stream: true                  # SSE — non-stream cap is ~60 s

The model still calls the structured-output tool voluntarily in
practice — the tool definition + Pydantic-strict prompt is sufficient.
The runner accepts EITHER channel as a defensive fallback:

  - tool_calls path (preferred): accumulate function.arguments delta
    chunks; finish_reason=tool_calls.
  - content path (fallback): accumulate delta.content, then extract a
    JSON object via _extract_json_from_text (fenced ```json block →
    first balanced {...} → raw). Triggers only if the model decides to
    answer in prose despite the tool offering.

Streaming is also load-bearing: DeepSeek closes idle non-streaming
connections at ~60 s — well before our ~350 KB trade-analysis prompts
finish generating in thinking mode.

reasoning_content (the thinking trace) is captured as full text and
returned in RunnerResult.reasoning_content so the orchestrator can
persist it to provider_metadata_jsonb.

Docs:
- Create Chat Completion:
  https://api-docs.deepseek.com/api/create-chat-completion
- Function calling + strict mode (Beta):
  https://api-docs.deepseek.com/guides/function_calling

Auth: DEEPSEEK_API_KEY read from process env at call time. Unlike the
subprocess runners, no _runner_child_env allow-list dance — this runs
in-process so the existing process env is available directly. The key
itself is never logged or echoed in error messages.

Cost note: thinking mode roughly 2x output tokens per call (structured
output + reasoning trace). Same per-token rate; the extra cost buys
chain-of-thought visibility (persisted via provider_metadata_jsonb).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    RunnerResult,
    TradeInsightsAiRunnerError,
)

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_TOOL_NAME = "emit_trade_insight"

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_from_text(text: str) -> str:
    """Probe helper — pull a JSON object out of free-form content.

    Tries: fenced ```json``` block → first complete {...} object via a
    string-aware decoder → raw. Lets json.loads raise downstream if nothing
    usable was found.

    A thinking model often appends prose after the JSON object (DeepSeek's
    content channel). The first complete object must be isolated with a
    string-aware scan: ``json.JSONDecoder().raw_decode`` correctly skips
    braces that appear inside string literals, which a naive brace-depth
    counter mis-counts — leaving trailing text that makes ``json.loads`` fail
    with "Extra data".
    """
    fence = _FENCED_JSON_RE.search(text)
    if fence:
        return fence.group(1)
    start = text.find("{")
    if start < 0:
        return text
    try:
        _obj, end = json.JSONDecoder().raw_decode(text, start)
        return text[start:end]
    except json.JSONDecodeError as exc:
        logger.debug(
            "raw_decode failed at pos %d: %r, trying brace-depth fallback",
            start,
            repr(exc),
        )
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return text[start:]


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
            "thinking": {"type": "enabled"},
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
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Accumulators populated as SSE chunks arrive.
        # Probe mode: model may emit via tool_calls OR delta.content; track both.
        # Track arguments per tool-call index: DeepSeek's thinking model can
        # split a single logical response across multiple tool-call indices
        # (index 0 gets the first ~32 KB, index 1 gets the rest including
        # the framework block). Merging the dicts recovers the full output.
        emitted_tool_name: str | None = None
        arguments_by_index: dict[int, list[str]] = {}
        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        resolved_model: str | None = None
        finish_reason: str | None = None
        total_output_bytes = 0

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
                            call_idx = call_delta.get("index", 0)
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
                                total_output_bytes += len(arg_chunk.encode("utf-8"))
                                if total_output_bytes > max_output_bytes:
                                    raise TradeInsightsAiRunnerError(
                                        "deepseek output (args + content + "
                                        f"reasoning) exceeded {max_output_bytes} "
                                        "bytes"
                                    )
                                arguments_by_index.setdefault(call_idx, []).append(
                                    arg_chunk
                                )
                        content_chunk = delta.get("content")
                        if content_chunk:
                            total_output_bytes += len(content_chunk.encode("utf-8"))
                            if total_output_bytes > max_output_bytes:
                                raise TradeInsightsAiRunnerError(
                                    "deepseek output (args + content + "
                                    f"reasoning) exceeded {max_output_bytes} "
                                    "bytes"
                                )
                            content_chunks.append(content_chunk)
                        reasoning_chunk = delta.get("reasoning_content")
                        if reasoning_chunk:
                            total_output_bytes += len(reasoning_chunk.encode("utf-8"))
                            if total_output_bytes > max_output_bytes:
                                raise TradeInsightsAiRunnerError(
                                    "deepseek output (args + content + "
                                    f"reasoning) exceeded {max_output_bytes} "
                                    "bytes"
                                )
                            reasoning_chunks.append(reasoning_chunk)
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

        if finish_reason and finish_reason not in ("tool_calls", "stop"):
            logger.warning(
                "deepseek stream finished with reason=%s (continuing)",
                finish_reason,
            )

        reasoning_text = "".join(reasoning_chunks)
        reasoning_bytes = len(reasoning_text.encode("utf-8"))
        content_text = "".join(content_chunks)
        content_bytes = len(content_text.encode("utf-8"))

        # Reassemble per-index tool call arguments. When the thinking model
        # splits a single logical response across multiple tool-call indices,
        # each index yields a valid JSON object; merge them so the framework
        # block (often in index 1) is not lost.
        sorted_indices = sorted(arguments_by_index.keys())
        args_texts = {idx: "".join(arguments_by_index[idx]) for idx in sorted_indices}
        all_args_bytes = sum(len(t.encode("utf-8")) for t in args_texts.values())

        # Disposition: prefer tool_calls if present, else parse text.
        output_channel: str
        if arguments_by_index:
            if emitted_tool_name and emitted_tool_name != DEEPSEEK_TOOL_NAME:
                raise TradeInsightsAiRunnerError(
                    "deepseek emitted unexpected tool name "
                    f"{emitted_tool_name!r} (expected {DEEPSEEK_TOOL_NAME!r})"
                )
            output_channel = "tool_calls"
        elif content_chunks:
            output_channel = "content"
        else:
            raise TradeInsightsAiRunnerError(
                "deepseek: stream ended with neither tool_calls nor content "
                f"(finish_reason={finish_reason}, "
                f"reasoning_bytes={reasoning_bytes})"
            )

        logger.info(
            "deepseek channel=%s tool=%s tool_indices=%s args=%d content=%d reasoning=%d finish=%s",
            output_channel,
            emitted_tool_name,
            sorted_indices or "none",
            all_args_bytes,
            content_bytes,
            reasoning_bytes,
            finish_reason,
        )

        if output_channel == "tool_calls":
            # Parse each tool-call index as a separate JSON object and merge.
            merged: dict[str, Any] = {}
            for idx in sorted_indices:
                raw = args_texts[idx].strip()
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        obj, _ = json.JSONDecoder().raw_decode(raw)
                    except json.JSONDecodeError as exc:
                        raise TradeInsightsAiRunnerError(
                            f"deepseek: tool_calls index {idx} was not valid JSON: {exc}"
                        ) from exc
                if isinstance(obj, dict):
                    merged.update(obj)
                elif not merged:
                    merged = obj  # type: ignore[assignment]
            parsed = merged
        else:
            raw_json = _extract_json_from_text(content_text)
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise TradeInsightsAiRunnerError(
                    f"deepseek: extracted output was not valid JSON: {exc}"
                ) from exc

        if not isinstance(parsed, dict):
            raise TradeInsightsAiRunnerError(
                "deepseek: parsed output must be a JSON object "
                f"(got {type(parsed).__name__})"
            )

        resolved = resolved_model or effective_model or "deepseek-default"
        return RunnerResult(
            outcome=parsed,
            resolved_model=resolved,
            reasoning_content=reasoning_text or None,
            output_channel=output_channel,
        )
