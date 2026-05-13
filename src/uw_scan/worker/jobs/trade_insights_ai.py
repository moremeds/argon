"""Worker job for operator-triggered Trade Insights AI analysis."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.trade_insights_ai import (
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
    render_trade_insights_ai_markdown,
    trade_insights_ai_output_schema,
    validate_trade_insights_ai_outcome,
)
from uw_scan.storage.repository import Repository


class TradeInsightsAiRunnerError(RuntimeError):
    """Controlled failure from the local Codex CLI runner."""


def _codex_child_env() -> dict[str, str]:
    allowed_exact = {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
    }
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in allowed_exact or key.startswith("LC_"):
            env[key] = value
    return env


def run_codex_trade_insights_analysis(
    prompt: str,
    schema: dict[str, Any],
    *,
    model: str,
    timeout_seconds: float,
    max_output_bytes: int,
) -> dict[str, Any]:
    """Run local `codex exec` and return the structured JSON final response."""

    with tempfile.TemporaryDirectory(prefix="trade-insights-ai-") as tmp:
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
                env=_codex_child_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TradeInsightsAiRunnerError(
                f"codex exec timed out after {timeout_seconds}s"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise TradeInsightsAiRunnerError(
                f"codex exec failed with exit {completed.returncode}: {detail[:1000]}"
            )
        if not result_path.exists():
            raise TradeInsightsAiRunnerError("codex exec did not write a final message")

        output_bytes = result_path.read_bytes()
        if len(output_bytes) > max_output_bytes:
            raise TradeInsightsAiRunnerError(
                f"codex output exceeded {max_output_bytes} bytes"
            )
        try:
            parsed = json.loads(output_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise TradeInsightsAiRunnerError("codex output was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise TradeInsightsAiRunnerError("codex output JSON must be an object")
        return parsed


def _repo(settings: Settings) -> Repository:
    conn = psycopg.connect(settings.db_dsn())
    return Repository(conn, schema=settings.db_schema)


def _fail_analysis(settings: Settings, analysis_id: str, error_message: str) -> None:
    repo = _repo(settings)
    try:
        repo.fail_trade_insight_ai_analysis(analysis_id, error_message)
        repo.conn.commit()
    finally:
        repo.conn.close()


def trade_insights_ai_tick(settings: Settings) -> bool:
    """Claim and execute one queued Trade Insights AI analysis, if present."""

    repo = _repo(settings)
    analysis_id: str | None = None
    produced_at: datetime | None = None
    prompt_payload: dict[str, Any] | None = None
    try:
        repo.upsert_heartbeat("trade_insights_ai_tick")
        row = repo.claim_next_trade_insight_ai_analysis()
        if row is None:
            repo.conn.commit()
            return False
        analysis_id = str(row["analysis_id"])
        analysis_input = dict(row["analysis_input_jsonb"])
        produced_at = datetime.now(timezone.utc)
        prompt_payload = build_trade_insights_ai_prompt_payload(
            analysis_input,
            produced_at=produced_at,
        )
        prompt_text = build_trade_insights_ai_prompt(prompt_payload)
        output_schema = trade_insights_ai_output_schema()
        repo.prepare_trade_insight_ai_analysis(
            analysis_id,
            prompt_text=prompt_text,
            prompt_payload=prompt_payload,
            output_schema=output_schema,
            produced_at=produced_at,
        )
        repo.conn.commit()
    except Exception as exc:
        repo.conn.rollback()
        if analysis_id is not None:
            _fail_analysis(settings, analysis_id, repr(exc))
            return True
        raise
    finally:
        repo.conn.close()

    assert analysis_id is not None
    assert produced_at is not None
    assert prompt_payload is not None

    try:
        raw_outcome = run_codex_trade_insights_analysis(
            build_trade_insights_ai_prompt(prompt_payload),
            trade_insights_ai_output_schema(),
            model=settings.trade_insights_ai_model.strip(),
            timeout_seconds=settings.trade_insights_ai_timeout_seconds,
            max_output_bytes=settings.trade_insights_ai_max_output_bytes,
        )
        outcome = validate_trade_insights_ai_outcome(
            raw_outcome,
            prompt_payload,
            produced_at=produced_at,
        )
        markdown = render_trade_insights_ai_markdown(outcome)
        repo = _repo(settings)
        try:
            repo.complete_trade_insight_ai_analysis(
                analysis_id,
                outcome=outcome.model_dump(mode="json"),
                markdown=markdown,
            )
            repo.conn.commit()
        finally:
            repo.conn.close()
    except Exception as exc:
        _fail_analysis(settings, analysis_id, str(exc) or repr(exc))
    return True
