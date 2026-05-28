"""Tests for shared helpers in trade_insights_ai_runners (Task 4)."""

from __future__ import annotations

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    _format_runner_failure,
    _runner_child_env,
)


def test_format_runner_failure_lifts_error_lines_to_front() -> None:
    banner = (
        "Codex banner line 1\n"
        + ("noise line\n" * 50)
        + "ERROR: You've hit your usage limit. Try again later."
    )
    msg = _format_runner_failure(banner, None)
    assert "[errors]" in msg
    assert "You've hit your usage limit" in msg
    assert msg.index("[errors]") < msg.index("[tail]")


def test_format_runner_failure_falls_back_to_tail_with_no_errors() -> None:
    long = "x" * 5000 + "\nfinal-cause"
    msg = _format_runner_failure(long, None)
    assert "final-cause" in msg
    assert msg.count("x") < 4000


def test_format_runner_failure_handles_empty_input() -> None:
    assert _format_runner_failure(None, None) == "(no output)"
    assert _format_runner_failure("", "") == "(no output)"


def test_format_runner_failure_combines_stderr_and_stdout() -> None:
    msg = _format_runner_failure("stderr-line", "stdout-line")
    assert "stderr-line" in msg
    assert "stdout-line" in msg


def test_runner_child_env_drops_app_secrets(monkeypatch) -> None:
    monkeypatch.setenv("UW_SCAN_API_KEY", "secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "secret")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-too")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-home")
    env = _runner_child_env()
    assert "UW_SCAN_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    assert "UW_SCAN_DB_PASSWORD" not in env
    # ANTHROPIC_API_KEY MUST be stripped — verified in pre-flight that leaving
    # it in env causes claude to use API-key billing instead of OAuth keychain.
    assert "ANTHROPIC_API_KEY" not in env
    assert env.get("CODEX_HOME") == "/tmp/codex-home"


def test_runner_child_env_preserves_path_and_locale(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    env = _runner_child_env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["LANG"] == "en_US.UTF-8"


def test_codex_runner_declares_strict_contract_flags() -> None:
    """Codex needs the full strict schema (additionalProperties:false + every
    field required) and the OpenAI-incompatible lookaround regex stripped."""
    from uw_scan.worker.jobs.trade_insights_codex_runner import CodexRunner

    runner = CodexRunner()
    assert runner.schema_strict is True
    assert runner.strip_lookaround_regex is True
    assert runner.requires_lenient_validation is False


def test_claude_runner_declares_lenient_contract_flags() -> None:
    """Claude's StructuredOutput tool silently drops to freeform JSON when
    the schema is too strict at every level, so the Claude path runs lenient.
    Anthropic accepts lookaround regex so no strip needed."""
    from uw_scan.worker.jobs.trade_insights_claude_runner import ClaudeRunner

    runner = ClaudeRunner()
    assert runner.schema_strict is False
    assert runner.strip_lookaround_regex is False
    assert runner.requires_lenient_validation is True
