"""Shared abstractions for Trade Insights AI provider runners.

Each provider (codex, claude) has its own runner module that implements the
AiProviderRunner Protocol. The worker tick dispatches via the RUNNERS registry
in trade_insights_ai.py — no if/else branching on provider.
"""

from __future__ import annotations

import os
from typing import Any, NamedTuple, Protocol


class TradeInsightsAiRunnerError(RuntimeError):
    """Controlled failure from any provider's CLI runner."""


class RunnerResult(NamedTuple):
    """What a runner returns on success."""

    outcome: dict[str, Any]
    """The structured JSON the model produced (already JSON-decoded)."""

    resolved_model: str
    """Canonical model ID the provider actually used (post-hoc capture).

    For Claude, comes from the system/init event in the output envelope. For
    Codex, from the output envelope if exposed, else the configured value or
    a sentinel default.
    """


class AiProviderRunner(Protocol):
    """Interface every provider runner must satisfy."""

    name: str  # "codex" | "claude" | "deepseek"

    # Schema-generation flags consumed by the orchestrator. Each runner
    # declares them once as class attributes; the orchestrator never branches
    # on runner.name. Adding a fourth provider = add a class + register; no
    # orchestrator change.
    schema_strict: bool
    strip_lookaround_regex: bool
    requires_lenient_validation: bool

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult: ...


def _format_runner_failure(
    stderr: str | None,
    stdout: str | None,
    *,
    tail_chars: int = 1500,
) -> str:
    """Format provider stderr/stdout for an analysis row's error_message.

    Both `codex exec --output-schema` and `claude --print --json-schema` echo
    the prompt + banner to stderr as a side effect. When the provider fails,
    the human-readable cause (usage limit, auth, schema validation) lives at
    the END of the stream, not the start — keeping the first N chars is
    exactly the worst slice. This helper keeps the TAIL and lifts any
    `ERROR:` lines to the front.
    """
    stderr_clean = (stderr or "").strip()
    stdout_clean = (stdout or "").strip()
    combined = "\n".join(p for p in (stderr_clean, stdout_clean) if p)
    if not combined:
        return "(no output)"
    error_lines: dict[str, None] = {}
    for ln in combined.splitlines():
        stripped = ln.strip()
        if stripped.startswith(("ERROR:", "error:", "Error:")):
            error_lines.setdefault(stripped, None)
    tail = combined[-tail_chars:] if len(combined) > tail_chars else combined
    if error_lines:
        return "[errors] " + " | ".join(error_lines.keys()) + " | [tail] " + tail
    return tail


def _runner_child_env() -> dict[str, str]:
    """Allow-listed environment for any CLI runner subprocess.

    Forwards only neutral environment (PATH, locale, TMPDIR, CODEX_HOME, USER)
    and drops every app secret (UW_SCAN_API_KEY, MASSIVE_API_KEY, *_DB_PASSWORD,
    ANTHROPIC_API_KEY, etc.). Both Codex and Claude work with this allow-list:
    Codex uses CODEX_HOME, Claude uses macOS keychain OAuth (no env var).

    Critical: ANTHROPIC_API_KEY must NOT be forwarded — verified in pre-flight
    that with it set, claude reports apiKeySource=ANTHROPIC_API_KEY and uses
    API-key billing instead of the user's OAuth/keychain subscription.

    USER/LOGNAME are required: Claude Code uses process.env.USER as the macOS
    Keychain account selector ("Claude Code-credentials" service, account=$USER).
    Without USER, the OAuth lookup misses and claude --print fails with
    "Not logged in · Please run /login" even when the keychain entry exists.
    """
    allowed_exact = {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
        "USER",
    }
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in allowed_exact or key.startswith("LC_"):
            env[key] = value
    return env
