from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from uw_scan.worker.jobs.trade_insights_ai import (
    TradeInsightsAiRunnerError,
    run_codex_trade_insights_analysis,
)


def test_codex_runner_uses_read_only_exec_command_and_stdin(monkeypatch):
    captured = {}

    def fake_run(cmd, *, input, text, capture_output, timeout, env, check):
        captured.update(
            {
                "cmd": cmd,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "timeout": timeout,
                "env": env,
                "check": check,
            }
        )
        result_path = Path(cmd[cmd.index("--output-last-message") + 1])
        result_path.write_text(json.dumps({"ok": True}))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    result = run_codex_trade_insights_analysis(
        "prompt text",
        {"type": "object"},
        model="gpt-5.4",
        timeout_seconds=12,
        max_output_bytes=1024,
    )

    assert result == {"ok": True}
    cmd = captured["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert "--ephemeral" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in cmd
    assert "--ignore-rules" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "--cd" in cmd
    assert "--output-schema" in cmd
    assert "--output-last-message" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5.4"
    assert cmd[-1] == "-"
    assert captured["input"] == "prompt text"
    assert captured["timeout"] == 12
    assert captured["check"] is False


def test_codex_runner_excludes_app_secrets_from_child_environment(
    monkeypatch,
):
    captured = {}
    monkeypatch.setenv("UW_SCAN_API_KEY", "secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "secret")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-home")

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        result_path = Path(cmd[cmd.index("--output-last-message") + 1])
        result_path.write_text(json.dumps({"ok": True}))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    run_codex_trade_insights_analysis(
        "prompt",
        {"type": "object"},
        model="",
        timeout_seconds=10,
        max_output_bytes=1024,
    )

    env = captured["env"]
    assert "UW_SCAN_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    assert "UW_SCAN_DB_PASSWORD" not in env
    assert env["CODEX_HOME"] == "/tmp/codex-home"


def test_codex_runner_timeout_raises_controlled_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="timed out"):
        run_codex_trade_insights_analysis(
            "prompt",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_codex_runner_nonzero_exit_raises_controlled_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="bad flag")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="codex exec failed"):
        run_codex_trade_insights_analysis(
            "prompt",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )


def test_codex_runner_lifts_error_lines_to_front_of_failure_message(monkeypatch):
    """Regression: when codex echoes a long prompt to stderr before dying, the
    real `ERROR:` line lives at the END of the stream. The worker must surface
    that line in the exception message so quota/auth failures show up in
    `trade_insight_ai_analyses.error_message` instead of a noisy banner.
    """
    banner_and_echoed_prompt = (
        "OpenAI Codex v0.132.0\n"
        "--------\n"
        "workdir: /tmp/x\nmodel: gpt-5.5\n"
        + ("user\nYou are an institutional options strategist...\n" * 50)
        + "\nERROR: You've hit your usage limit. Visit chatgpt.com/codex"
    )

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr=banner_and_echoed_prompt
        )

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError) as exc_info:
        run_codex_trade_insights_analysis(
            "prompt",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )
    message = str(exc_info.value)
    assert "codex exec failed with exit 1" in message
    # The lifted ERROR: prefix must appear before the [tail] section so the
    # actionable cause is the first thing an operator reads.
    assert "[errors]" in message
    assert "You've hit your usage limit" in message
    assert message.index("[errors]") < message.index("[tail]")


def test_codex_runner_falls_back_to_tail_when_no_error_lines(monkeypatch):
    """When stderr has no `ERROR:` lines (e.g. a generic non-zero exit),
    fall back to the TAIL of the combined streams — never the head, which
    is the boring banner/prompt echo."""
    long_noise = "x" * 5000 + "\nfinal-cause-line"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 7, stdout="", stderr=long_noise)

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError) as exc_info:
        run_codex_trade_insights_analysis(
            "prompt",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )
    message = str(exc_info.value)
    assert "final-cause-line" in message  # tail kept, not head
    assert message.count("x") < 4000  # the 5000-char banner head was dropped


def test_codex_runner_oversized_output_raises_controlled_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        result_path = Path(cmd[cmd.index("--output-last-message") + 1])
        result_path.write_text("x" * 2048)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        run_codex_trade_insights_analysis(
            "prompt",
            {"type": "object"},
            model="",
            timeout_seconds=1,
            max_output_bytes=1024,
        )
