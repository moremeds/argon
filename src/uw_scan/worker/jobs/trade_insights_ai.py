"""Worker job for operator-triggered Trade Insights AI analysis.

Orchestration only — runners live in `trade_insights_codex_runner.py` and
`trade_insights_claude_runner.py`. Dispatch goes via the RUNNERS registry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.trade_insights_ai import (
    PROMPT_VERSION,
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
    render_trade_insights_ai_markdown,
    trade_insights_ai_output_schema,
    validate_trade_insights_ai_outcome,
)
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.trade_insights_ai_runners import (
    AiProviderRunner,
    TradeInsightsAiRunnerError,
)
from uw_scan.worker.jobs.trade_insights_claude_runner import ClaudeRunner
from uw_scan.worker.jobs.trade_insights_codex_runner import CodexRunner

RUNNERS: dict[str, AiProviderRunner] = {
    "codex": CodexRunner(),
    "claude": ClaudeRunner(),
}


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


def _heartbeat_key(provider_filter: str | None) -> str:
    if provider_filter is None:
        return "trade_insights_ai_tick"
    return f"trade_insights_ai_tick_{provider_filter}"


def _provider_model_and_timeout(settings: Settings, provider: str) -> tuple[str, float]:
    if provider == "codex":
        return (
            settings.trade_insights_ai_model.strip(),
            settings.trade_insights_ai_timeout_seconds,
        )
    if provider == "claude":
        return (
            settings.trade_insights_ai_claude_model.strip(),
            settings.trade_insights_ai_claude_timeout_seconds,
        )
    raise TradeInsightsAiRunnerError(f"unknown provider {provider!r}")


def trade_insights_ai_tick(
    settings: Settings,
    *,
    provider_filter: str | None = None,
) -> bool:
    """Claim and execute one queued Trade Insights AI analysis, if present.

    `provider_filter` pins this tick to a single provider's queue — used by
    provider-pinned worker roles (`ai-codex`, `ai-claude`). When None, the
    legacy single-pool behavior claims any provider's row.
    """

    repo = _repo(settings)
    analysis_id: str | None = None
    produced_at: datetime | None = None
    prompt_payload: dict[str, Any] | None = None
    row_provider: str | None = None
    try:
        repo.upsert_heartbeat(_heartbeat_key(provider_filter))
        stale_running_before = datetime.now(timezone.utc) - timedelta(
            seconds=settings.trade_insights_ai_timeout_seconds + 60
        )
        row = repo.claim_next_trade_insight_ai_analysis(
            stale_running_before=stale_running_before,
            provider=provider_filter,
        )
        if row is None:
            repo.conn.commit()
            return False
        analysis_id = str(row["analysis_id"])
        row_provider = row.get("provider") or "codex"
        if row["prompt_version"] != PROMPT_VERSION:
            repo.fail_trade_insight_ai_analysis(
                analysis_id,
                f"obsolete prompt_version {row['prompt_version']} superseded by {PROMPT_VERSION}",
            )
            repo.conn.commit()
            return True
        if row_provider not in RUNNERS:
            repo.fail_trade_insight_ai_analysis(
                analysis_id,
                f"unknown provider {row_provider!r}",
            )
            repo.conn.commit()
            return True
        analysis_input = dict(row["analysis_input_jsonb"])
        produced_at = datetime.now(timezone.utc)
        prompt_payload = build_trade_insights_ai_prompt_payload(
            analysis_input,
            produced_at=produced_at,
        )
        prompt_text = build_trade_insights_ai_prompt(prompt_payload)
        output_schema = trade_insights_ai_output_schema(
            strict=(row_provider != "claude"),
        )
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
    assert row_provider is not None

    runner = RUNNERS[row_provider]
    model_env, timeout = _provider_model_and_timeout(settings, row_provider)

    try:
        result = runner.run(
            build_trade_insights_ai_prompt(prompt_payload),
            trade_insights_ai_output_schema(strict=(row_provider != "claude")),
            model=model_env,
            timeout_seconds=timeout,
            max_output_bytes=settings.trade_insights_ai_max_output_bytes,
        )
        outcome = validate_trade_insights_ai_outcome(
            result.outcome,
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
                resolved_model=result.resolved_model,
            )
            repo.conn.commit()
        finally:
            repo.conn.close()
    except Exception as exc:
        _fail_analysis(settings, analysis_id, str(exc) or repr(exc))
    return True
