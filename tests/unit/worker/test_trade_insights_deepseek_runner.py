"""DeepSeek HTTP runner tests. Mocks httpx — never hits the network."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest


def _mock_success_response(
    monkeypatch, outcome_obj, *, resolved_model: str = "deepseek-v4-pro"
):
    """Replace httpx.Client.post with a stub returning a DeepSeek-shaped
    success envelope where tool_calls[0].function.arguments is
    json.dumps(outcome_obj). Returns a captured dict that the caller can
    inspect for url/json/headers/timeout sent."""
    body = {
        "model": resolved_model,
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "emit_trade_insight",
                                "arguments": json.dumps(outcome_obj),
                            }
                        }
                    ],
                }
            }
        ],
    }
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = body
    response.raise_for_status.return_value = None
    response.text = json.dumps(body)
    captured: dict = {}

    def fake_post(self, url, *, json, headers, timeout):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return captured


def test_deepseek_runner_posts_function_call_with_strict_true(monkeypatch) -> None:
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


def test_deepseek_runner_raises_when_api_key_missing(monkeypatch) -> None:
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )

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
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kw: err_response)
    with pytest.raises(TradeInsightsAiRunnerError):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_when_response_missing_tool_calls(monkeypatch) -> None:
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
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_rejects_unexpected_tool_name(monkeypatch) -> None:
    """tool_choice was forced; if DeepSeek returns a tool_call whose name is
    something other than 'emit_trade_insight' (model hallucinated a different
    tool), parsing the arguments would silently bind output to a schema we
    never asked for. Reject loudly instead."""
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "model": "deepseek-v4-pro",
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_web",
                                "arguments": json.dumps({"q": "AAPL"}),
                            }
                        }
                    ]
                }
            }
        ],
    }
    response.raise_for_status.return_value = None
    response.text = json.dumps(response.json.return_value)
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kw: response)
    with pytest.raises(TradeInsightsAiRunnerError, match="unexpected tool name"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_on_timeout(monkeypatch) -> None:
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
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=4096,
        )


def test_deepseek_runner_raises_when_output_exceeds_max_bytes(monkeypatch) -> None:
    from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

    from uw_scan.worker.jobs.trade_insights_ai_runners import (
        TradeInsightsAiRunnerError,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    huge_outcome = {"schema_version": "trade-insights-ai-v5.3", "blob": "x" * 5000}
    _mock_success_response(monkeypatch, huge_outcome)
    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        DeepSeekRunner().run(
            prompt="x",
            schema={},
            model="deepseek-v4-pro",
            timeout_seconds=10.0,
            max_output_bytes=512,
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
