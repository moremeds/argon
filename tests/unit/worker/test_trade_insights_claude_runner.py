"""Unit tests for ClaudeRunner (Task 6).

NOTE on output format: `claude --print --output-format json` returns a JSON
*array* of events: a `system/init` event (with `model`), zero or more
`assistant` events, and a final `result` event (with the stringified `result`
string and an `is_error` flag).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from uw_scan.worker.jobs.trade_insights_ai_runners import TradeInsightsAiRunnerError
from uw_scan.worker.jobs.trade_insights_claude_runner import ClaudeRunner


def _success_stdout(result_payload: dict, model: str = "claude-opus-4-7") -> str:
    """Build a stdout array matching `claude --print --output-format json`."""
    return json.dumps(
        [
            {
                "type": "system",
                "subtype": "init",
                "model": model,
                "session_id": "s",
                "apiKeySource": "oauth",
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": json.dumps(result_payload),
                "model": model,
                "session_id": "s",
            },
        ]
    )


SUCCESS_STDOUT = _success_stdout({"answer": "ok"})


def test_claude_runner_uses_print_mode_with_locked_down_flags(monkeypatch):
    captured = {}

    def fake_run(cmd, *, input, text, capture_output, timeout, env, check, cwd):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=SUCCESS_STDOUT, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    result = ClaudeRunner().run(
        "prompt text",
        {"type": "object"},
        model="opus",
        timeout_seconds=12,
        max_output_bytes=1024,
    )

    assert result.outcome == {"answer": "ok"}
    assert result.resolved_model == "claude-opus-4-7"

    cmd = captured["cmd"]
    assert cmd[:2] == ["claude", "--print"]
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--disable-slash-commands" in cmd
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers": {}}'
    assert "--no-session-persistence" in cmd
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--json-schema" in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert "--add-dir" in cmd


def test_claude_runner_omits_model_flag_when_blank(monkeypatch):
    captured = {}

    def fake_run(cmd, **_):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=SUCCESS_STDOUT, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    ClaudeRunner().run(
        "p",
        {"type": "object"},
        model="",
        timeout_seconds=10,
        max_output_bytes=1024,
    )

    cmd = captured["cmd"]
    assert "--model" not in cmd


def test_claude_runner_resolved_model_falls_back_when_envelope_lacks_model(monkeypatch):
    arr = json.dumps(
        [
            {"type": "system", "subtype": "init", "session_id": "s"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": json.dumps({"ok": True}),
                "session_id": "s",
            },
        ]
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    r = ClaudeRunner().run(
        "p",
        {"type": "object"},
        model="sonnet",
        timeout_seconds=10,
        max_output_bytes=1024,
    )
    assert r.resolved_model == "sonnet"


def test_claude_runner_resolved_model_falls_back_to_default(monkeypatch):
    arr = json.dumps(
        [
            {"type": "system", "subtype": "init", "session_id": "s"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": json.dumps({"ok": True}),
                "session_id": "s",
            },
        ]
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    r = ClaudeRunner().run(
        "p",
        {"type": "object"},
        model="",
        timeout_seconds=10,
        max_output_bytes=1024,
    )
    assert r.resolved_model == "claude-default"


def test_claude_runner_treats_is_error_true_as_failure_even_with_success_subtype(
    monkeypatch,
):
    """Verified-from-pre-flight regression: Claude returns subtype:'success'
    AND is_error:true for billing/API errors. The runner MUST treat is_error:true
    as a failure regardless of subtype."""
    arr = json.dumps(
        [
            {"type": "system", "subtype": "init", "model": "claude-opus-4-7"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "api_error_status": 400,
                "result": "Credit balance is too low",
                "model": "claude-opus-4-7",
            },
        ]
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="API error|Credit balance"):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=4096,
        )


def test_claude_runner_excludes_app_secrets_from_child_environment(monkeypatch):
    """ANTHROPIC_API_KEY exclusion is load-bearing — pre-flight verified that
    with it set, claude reports apiKeySource=ANTHROPIC_API_KEY and uses
    API-key billing instead of OAuth keychain."""
    captured = {}
    monkeypatch.setenv("UW_SCAN_API_KEY", "secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "secret")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-too")
    monkeypatch.setenv("PATH", "/usr/bin")

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout=SUCCESS_STDOUT, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    ClaudeRunner().run(
        "p",
        {"type": "object"},
        model="",
        timeout_seconds=10,
        max_output_bytes=1024,
    )

    env = captured["env"]
    assert "UW_SCAN_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    assert "UW_SCAN_DB_PASSWORD" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_claude_runner_timeout_raises_controlled_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="timed out"):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_claude_runner_nonzero_exit_raises_with_lifted_error(monkeypatch):
    stderr = (
        "OpenAI Codex banner...\n"
        + "echoed prompt\n" * 30
        + "ERROR: Authentication failed."
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError) as exc_info:
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )
    msg = str(exc_info.value)
    assert "claude --print failed with exit 1" in msg
    assert "[errors]" in msg
    assert "Authentication failed" in msg


def test_claude_runner_rejects_non_success_subtype(monkeypatch):
    arr = json.dumps(
        [
            {"type": "system", "subtype": "init", "model": "x"},
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "message": "bad",
            },
        ]
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=4096,
        )


def test_claude_runner_rejects_stdout_not_array(monkeypatch):
    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"single": "object"}', stderr=""
        )

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="expected JSON array"):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_claude_runner_rejects_missing_result_event(monkeypatch):
    """Stdout array has system+assistant but no result event — malformed."""
    arr = json.dumps(
        [
            {"type": "system", "subtype": "init", "model": "x"},
            {"type": "assistant", "message": {}},
        ]
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="no result event"):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_claude_runner_rejects_malformed_stdout_json(monkeypatch):
    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="not valid JSON"):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_claude_runner_rejects_invalid_result_field(monkeypatch):
    arr = json.dumps(
        [
            {"type": "system", "subtype": "init", "model": "x"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "{not json",
                "model": "x",
            },
        ]
    )

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(
        TradeInsightsAiRunnerError, match="result field was not valid JSON"
    ):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_claude_runner_oversized_output_raises(monkeypatch):
    huge = _success_stdout({"data": "x" * 4096})

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=huge, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        ClaudeRunner().run(
            "p",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )
