"""Shared abstractions for Trade Insights AI provider runners.

Each provider's runner module implements the AiProviderRunner Protocol. The
worker tick dispatches via the RUNNERS registry in trade_insights_ai.py — no
if/else branching on provider.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Protocol


class TradeInsightsAiRunnerError(RuntimeError):
    """Controlled failure from a provider runner."""


class RunnerResult(NamedTuple):
    """What a runner returns on success."""

    outcome: dict[str, Any]
    """The structured JSON the model produced (already JSON-decoded)."""

    resolved_model: str
    """Canonical model ID the provider actually used (post-hoc capture).

    Comes from the provider's response envelope when exposed, else the
    configured value or a sentinel default.
    """

    reasoning_content: str | None = None
    """Chain-of-thought text the provider emitted alongside the answer.

    Provider-specific: DeepSeek populates this when thinking mode is enabled
    (delta.reasoning_content stream channel). A provider without a separate
    reasoning stream leaves this None.
    """

    output_channel: str | None = None
    """Which response channel won, when more than one is possible.

    DeepSeek may emit through `tool_calls` (function-calling, preferred) or
    `delta.content` (free-form text fallback). Recorded for observability so
    we can spot regressions when a provider stops calling the tool. Other
    runners that only have one channel leave this None.
    """


class AiProviderRunner(Protocol):
    """Interface every provider runner must satisfy."""

    name: str  # e.g. "deepseek"

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
