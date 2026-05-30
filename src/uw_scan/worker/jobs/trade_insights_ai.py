"""Worker job for operator-triggered Trade Insights AI analysis.

Orchestration only — runners live in `trade_insights_codex_runner.py` and
`trade_insights_claude_runner.py`. Dispatch goes via the RUNNERS registry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.trade_blast import (
    PROMPT_VERSION as BLAST_PROMPT_VERSION,
)
from uw_scan.reports.trade_blast import (
    build_trade_insights_ai_prompt as build_blast_prompt,
)
from uw_scan.reports.trade_blast import (
    build_trade_insights_ai_prompt_payload as build_blast_payload,
)
from uw_scan.reports.trade_blast import (
    render_trade_insights_ai_markdown as render_blast_markdown,
)
from uw_scan.reports.trade_blast import (
    trade_insights_ai_output_schema as blast_output_schema,
)
from uw_scan.reports.trade_blast import (
    validate_trade_insights_ai_outcome as validate_blast_outcome,
)
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
from uw_scan.worker.jobs.trade_insights_deepseek_runner import DeepSeekRunner

RUNNERS: dict[str, AiProviderRunner] = {
    "codex": CodexRunner(),
    "claude": ClaudeRunner(),
    "deepseek": DeepSeekRunner(),
}


def _repo(settings: Settings) -> Repository:
    conn = psycopg.connect(settings.db_dsn())
    return Repository(conn, schema=settings.db_schema)


def _fail_analysis(
    settings: Settings,
    analysis_id: str,
    error_message: str,
    *,
    raw_outcome: dict[str, Any] | None = None,
    provider_metadata: dict[str, Any] | None = None,
) -> None:
    repo = _repo(settings)
    try:
        repo.fail_trade_insight_ai_analysis(
            analysis_id,
            error_message,
            raw_outcome=raw_outcome,
            provider_metadata=provider_metadata,
        )
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
    if provider == "deepseek":
        return (
            settings.trade_insights_ai_deepseek_model.strip(),
            settings.trade_insights_ai_deepseek_timeout_seconds,
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
    is_blast: bool = False
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
        # Lane routing: blast rows use the trade_blast prompt/schema/validator;
        # insights rows use the production v5.3 card lane (unchanged behavior).
        is_blast = (row.get("analysis_kind") or "insights") == "blast"
        expected_version = BLAST_PROMPT_VERSION if is_blast else PROMPT_VERSION
        build_payload = (
            build_blast_payload if is_blast else build_trade_insights_ai_prompt_payload
        )
        build_prompt = (
            build_blast_prompt if is_blast else build_trade_insights_ai_prompt
        )
        build_schema = (
            blast_output_schema if is_blast else trade_insights_ai_output_schema
        )
        if row["prompt_version"] != expected_version:
            repo.fail_trade_insight_ai_analysis(
                analysis_id,
                f"obsolete prompt_version {row['prompt_version']} superseded by {expected_version}",
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
        runner = RUNNERS[row_provider]
        analysis_input = dict(row["analysis_input_jsonb"])
        produced_at = datetime.now(timezone.utc)
        prompt_payload = build_payload(
            analysis_input,
            produced_at=produced_at,
        )
        prompt_text = build_prompt(prompt_payload)
        output_schema = build_schema(
            strict=runner.schema_strict,
            strip_lookaround_regex=runner.strip_lookaround_regex,
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

    raw_outcome: dict[str, Any] | None = None
    provider_metadata: dict[str, Any] | None = None
    try:
        if is_blast:
            run_prompt = build_blast_prompt(prompt_payload)
            run_schema = blast_output_schema(
                strict=runner.schema_strict,
                strip_lookaround_regex=runner.strip_lookaround_regex,
            )
        else:
            run_prompt = build_trade_insights_ai_prompt(prompt_payload)
            run_schema = trade_insights_ai_output_schema(
                strict=runner.schema_strict,
                strip_lookaround_regex=runner.strip_lookaround_regex,
            )
        result = runner.run(
            run_prompt,
            run_schema,
            model=model_env,
            timeout_seconds=timeout,
            max_output_bytes=settings.trade_insights_ai_max_output_bytes,
        )
        # Snapshot before validation so a downstream rejection still leaves
        # the raw payload diagnosable via raw_outcome_jsonb, and the
        # reasoning trace via provider_metadata_jsonb.
        raw_outcome = result.outcome
        provider_metadata = _build_provider_metadata(result)
        if is_blast:
            # Blast lane: soft-validate so framework output always renders;
            # only the no-naked-shorts safety property is hard. Lenient
            # coercion fills required v5.x fields so the shared model parses.
            outcome = validate_blast_outcome(
                result.outcome,
                prompt_payload,
                produced_at=produced_at,
                lenient=True,
                soft=True,
            )
            markdown = render_blast_markdown(outcome)
        else:
            outcome = validate_trade_insights_ai_outcome(
                result.outcome,
                prompt_payload,
                produced_at=produced_at,
                lenient=runner.requires_lenient_validation,
            )
            markdown = render_trade_insights_ai_markdown(outcome)
        repo = _repo(settings)
        try:
            repo.complete_trade_insight_ai_analysis(
                analysis_id,
                outcome=outcome.model_dump(mode="json"),
                markdown=markdown,
                resolved_model=result.resolved_model,
                provider_metadata=provider_metadata,
            )
            repo.conn.commit()
        finally:
            repo.conn.close()
    except Exception as exc:
        _fail_analysis(
            settings,
            analysis_id,
            str(exc) or repr(exc),
            raw_outcome=raw_outcome,
            provider_metadata=provider_metadata,
        )
    return True


def _build_provider_metadata(result: Any) -> dict[str, Any] | None:
    """Assemble the provider_metadata_jsonb payload from a RunnerResult.

    Returns None when the runner emitted no metadata (codex/claude today) so
    callers can pass it through transparently; otherwise returns a dict with
    only the populated fields. Schemaless by design — see migration 064.
    """
    if result.reasoning_content is None and result.output_channel is None:
        return None
    metadata: dict[str, Any] = {}
    if result.reasoning_content is not None:
        metadata["reasoning_content"] = result.reasoning_content
        metadata["reasoning_bytes"] = len(result.reasoning_content.encode("utf-8"))
    if result.output_channel is not None:
        metadata["output_channel"] = result.output_channel
    return metadata
