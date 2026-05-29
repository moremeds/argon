"""DeepSeek HTTP runner tests. Mocks httpx — never hits the network.

The runner uses Server-Sent Events (SSE) streaming via `httpx.Client.stream`,
not single-shot POST. These mocks emulate the SSE chunks DeepSeek emits when
function-calling in thinking-enabled mode (tool_choice is NOT forced — the
model voluntarily calls the tool). Reasoning content is also streamed via
the `delta.reasoning_content` channel and surfaces in RunnerResult.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx
import pytest


def _sse_chunks_for_outcome(
    outcome_obj,
    *,
    resolved_model: str = "deepseek-v4-pro",
    chunk_size: int = 50,
    reasoning_text: str | None = None,
):
    """Build the SSE `data: ...` lines DeepSeek would emit for a happy-path
    tool_calls response. First chunk announces the role; optional reasoning
    chunks stream chain-of-thought via delta.reasoning_content; then the
    tool name; subsequent chunks stream the arguments string in slices;
    final chunk announces finish_reason=tool_calls; trailer is [DONE]."""
    args = json.dumps(outcome_obj)
    chunks: list[str] = []

    def _data(event: dict) -> str:
        return f"data: {json.dumps(event)}"

    chunks.append(
        _data(
            {
                "model": resolved_model,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": ""}}
                ],
            }
        )
    )
    if reasoning_text:
        for i in range(0, len(reasoning_text), chunk_size):
            chunks.append(
                _data(
                    {
                        "model": resolved_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "reasoning_content": reasoning_text[
                                        i : i + chunk_size
                                    ]
                                },
                            }
                        ],
                    }
                )
            )
    chunks.append(
        _data(
            {
                "model": resolved_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_xyz",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_trade_insight",
                                        "arguments": "",
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        )
    )
    for i in range(0, len(args), chunk_size):
        slice_ = args[i : i + chunk_size]
        chunks.append(
            _data(
                {
                    "model": resolved_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": slice_},
                                    }
                                ]
                            },
                        }
                    ],
                }
            )
        )
    chunks.append(
        _data(
            {
                "model": resolved_model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            }
        )
    )
    chunks.append("data: [DONE]")
    return chunks


def _patch_stream(
    monkeypatch,
    *,
    sse_lines: list[str] | None = None,
    raise_on_enter: BaseException | None = None,
    status_code: int = 200,
    error_body: bytes = b"",
):
    """Replace `httpx.Client.stream` with a fake context manager that yields
    a mock response. Returns a `captured` dict the caller can inspect."""
    captured: dict = {}

    @contextmanager
    def fake_stream(self, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        captured["timeout"] = kwargs.get("timeout")
        if raise_on_enter is not None:
            raise raise_on_enter
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        if status_code >= 400:
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                str(status_code), request=MagicMock(), response=response
            )
            response.read.return_value = error_body
        else:
            response.raise_for_status.return_value = None
            response.iter_lines.return_value = iter(sse_lines or [])
        yield response

    monkeypatch.setattr(httpx.Client, "stream", fake_stream)
    return captured


def test_deepseek_runner_streams_thinking_enabled_without_forced_tool_choice(
    monkeypatch,
) -> None:
    """Canonical request shape: thinking ON, no tool_choice, strict tool.

    v4-pro returns HTTP 400 if tool_choice is forced while thinking is
    enabled. The runner relies on the model voluntarily calling the
    structured-output tool (the strict schema + Pydantic-strict prompt is
    sufficient).
    """
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    outcome = {"schema_version": "trade-insights-ai-v5.3", "ticker": "TEST"}
    sse_lines = _sse_chunks_for_outcome(outcome, reasoning_text="step 1: pick X")
    captured = _patch_stream(monkeypatch, sse_lines=sse_lines)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    result = DeepSeekRunner().run(
        prompt="analyze TEST",
        schema={"type": "object", "properties": {}},
        model="deepseek-v4-pro",
        timeout_seconds=10.0,
        max_output_bytes=4096,
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    body = captured["json"]
    assert body["model"] == "deepseek-v4-pro"
    assert body["stream"] is True, (
        "Streaming is required: non-streaming requests with ~350 KB prompts "
        "hit DeepSeek's ~60 s server-side compute cap. Streaming keeps the "
        "connection alive throughout the response."
    )
    assert body["thinking"] == {"type": "enabled"}, (
        "thinking must be explicitly enabled — captures reasoning_content "
        "and is the canonical quality default for v4-pro."
    )
    assert "tool_choice" not in body, (
        "tool_choice MUST be omitted in thinking-enabled mode. v4-pro "
        "returns HTTP 400 'Thinking mode does not support this tool_choice' "
        "if it is present. The model still calls the tool voluntarily."
    )
    tool = body["tools"][0]["function"]
    assert tool["name"] == "emit_trade_insight"
    assert tool["strict"] is True
    assert tool["parameters"] == {"type": "object", "properties": {}}
    assert result.outcome == outcome
    assert result.resolved_model == "deepseek-v4-pro"
    assert result.output_channel == "tool_calls"
    assert result.reasoning_content == "step 1: pick X", (
        "Reasoning content streamed via delta.reasoning_content must be "
        "reassembled and returned for persistence to provider_metadata_jsonb."
    )


def test_deepseek_runner_raises_when_api_key_missing(monkeypatch) -> None:
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(TradeInsightsAiRunnerError, match="DEEPSEEK_API_KEY"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_on_non_2xx(monkeypatch) -> None:
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    _patch_stream(
        monkeypatch,
        status_code=429,
        error_body=b'{"error":{"message":"rate limited"}}',
    )
    with pytest.raises(TradeInsightsAiRunnerError, match="429"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_falls_back_to_content_channel_with_fenced_json(
    monkeypatch,
) -> None:
    """If the model declines to call the tool and instead emits a fenced
    ```json``` block in delta.content, the runner extracts and parses it.
    output_channel is reported as 'content' for observability."""
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    outcome = {"schema_version": "trade-insights-ai-v5.3", "ticker": "FALLBACK"}
    fenced = "Here is the result:\n```json\n" + json.dumps(outcome) + "\n```\nDone."
    sse_lines = [
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {'content': fenced}}]})}",
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}",
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, sse_lines=sse_lines)

    result = DeepSeekRunner().run(
        prompt="x",
        schema={},
        model="deepseek-v4-pro",
        timeout_seconds=10.0,
        max_output_bytes=8192,
    )
    assert result.outcome == outcome
    assert result.output_channel == "content"
    assert result.reasoning_content is None


def test_deepseek_runner_raises_when_stream_ends_with_neither_channel(
    monkeypatch,
) -> None:
    """Empty assistant turn — no tool_calls and no content — is a model
    failure we cannot recover from. Raise loudly."""
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    sse_lines = [
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {'role': 'assistant'}}]})}",
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}",
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, sse_lines=sse_lines)
    with pytest.raises(
        TradeInsightsAiRunnerError, match="neither tool_calls nor content"
    ):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_when_content_path_yields_invalid_json(
    monkeypatch,
) -> None:
    """delta.content with no extractable JSON object must fail loudly
    instead of silently returning garbage."""
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    sse_lines = [
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {'content': 'just plain prose, no json'}}]})}",
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}",
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, sse_lines=sse_lines)
    with pytest.raises(TradeInsightsAiRunnerError, match="not valid JSON"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_rejects_unexpected_tool_name(monkeypatch) -> None:
    """If the stream emits a tool_call whose name is something other than
    'emit_trade_insight', the arguments would silently bind to a schema we
    never asked for. Reject loudly."""
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    sse_lines = [
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'function': {'name': 'search_web', 'arguments': '{}'}}]}}]})}",
        f"data: {json.dumps({'model': 'deepseek-v4-pro', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}",
        "data: [DONE]",
    ]
    _patch_stream(monkeypatch, sse_lines=sse_lines)
    with pytest.raises(TradeInsightsAiRunnerError, match="unexpected tool name"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_on_timeout(monkeypatch) -> None:
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    _patch_stream(monkeypatch, raise_on_enter=httpx.TimeoutException("timed out"))
    with pytest.raises(TradeInsightsAiRunnerError, match="timed out"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_when_output_exceeds_max_bytes(monkeypatch) -> None:
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    huge_outcome = {"schema_version": "trade-insights-ai-v5.3", "blob": "x" * 5000}
    sse_lines = _sse_chunks_for_outcome(huge_outcome, chunk_size=200)
    _patch_stream(monkeypatch, sse_lines=sse_lines)
    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=512,
        )


def test_deepseek_runner_bounds_reasoning_content_against_max_bytes(
    monkeypatch,
) -> None:
    """reasoning_content streams alongside tool_calls; without a budget check
    a pathological prompt could blow past max_output_bytes via the reasoning
    channel alone. Args + content + reasoning all count against the same cap."""
    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    tiny_outcome = {"ticker": "Z"}
    huge_reasoning = "step-" * 200  # 1000 bytes
    sse_lines = _sse_chunks_for_outcome(
        tiny_outcome, chunk_size=50, reasoning_text=huge_reasoning
    )
    _patch_stream(monkeypatch, sse_lines=sse_lines)
    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=500,
        )


def test_deepseek_runner_declares_strict_contract_flags() -> None:
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    runner = DeepSeekRunner()
    assert runner.name == "deepseek"
    assert runner.schema_strict is True
    assert runner.strip_lookaround_regex is True
    assert runner.requires_lenient_validation is False


def test_deepseek_api_key_is_not_in_subprocess_child_env_allowlist(
    monkeypatch,
) -> None:
    """Regression guard: the _runner_child_env allow-list forwards a fixed set
    of neutral env vars to Codex/Claude subprocesses. Adding DEEPSEEK_API_KEY
    to that allow-list would leak the key to subprocesses that don't need it
    (codex exec, claude --print), violating the standing rule "no secrets to
    local Codex subprocesses".

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
