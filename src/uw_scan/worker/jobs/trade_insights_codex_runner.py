"""Codex CLI runner — implements AiProviderRunner via local `codex exec`."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    RunnerResult,
    TradeInsightsAiRunnerError,
    _format_runner_failure,
    _runner_child_env,
)


class CodexRunner:
    """Local Codex CLI runner. Reads keychain auth via CODEX_HOME."""

    name = "codex"
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
        with tempfile.TemporaryDirectory(prefix="trade-insights-codex-") as tmp:
            tmpdir = Path(tmp)
            schema_path = tmpdir / "schema.json"
            result_path = tmpdir / "result.json"
            schema_path.write_text(json.dumps(schema, sort_keys=True), encoding="utf-8")

            cmd = [
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--cd",
                str(tmpdir),
            ]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(
                [
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(result_path),
                    "-",
                ]
            )

            try:
                completed = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    env=_runner_child_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise TradeInsightsAiRunnerError(
                    f"codex exec timed out after {timeout_seconds}s"
                ) from exc

            if completed.returncode != 0:
                detail = _format_runner_failure(completed.stderr, completed.stdout)
                raise TradeInsightsAiRunnerError(
                    f"codex exec failed with exit {completed.returncode}: {detail}"
                )
            if not result_path.exists():
                raise TradeInsightsAiRunnerError(
                    "codex exec did not write a final message"
                )

            output_bytes = result_path.read_bytes()
            if len(output_bytes) > max_output_bytes:
                raise TradeInsightsAiRunnerError(
                    f"codex output exceeded {max_output_bytes} bytes"
                )
            try:
                parsed = json.loads(output_bytes.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise TradeInsightsAiRunnerError(
                    "codex output was not valid JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise TradeInsightsAiRunnerError("codex output JSON must be an object")
            return RunnerResult(
                outcome=parsed,
                resolved_model=model or "codex-default",
            )
