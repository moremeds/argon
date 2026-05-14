from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from tests.test_trade_insights_ai import _analysis_input, _sample_outcome_for
from uw_scan.config import Settings
from uw_scan.reports.trade_insights_ai import PROMPT_VERSION
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.trade_insights_ai import (
    TradeInsightsAiRunnerError,
    trade_insights_ai_tick,
)


def _settings_for_repo(repo: Repository) -> Settings:
    return Settings.from_env().model_copy(
        update={
            "db_name": repo.conn.info.dbname,
            "db_schema": repo._schema,
            "trade_insights_ai_enabled": True,
            "trade_insights_ai_model": "",
            "trade_insights_ai_timeout_seconds": 1.0,
            "trade_insights_ai_max_output_bytes": 262144,
            "trade_insights_ai_poll_seconds": 3,
        }
    )


def _create_snapshot(repo: Repository):
    run_id = repo.insert_scan_run("TSLA")
    payload = {
        "ticker": "TSLA",
        "header": {"confidence_label": "MEDIUM", "data_quality_label": "MIXED"},
        "source_reconciliation": {"status": "UNKNOWN"},
        "candidate_structures": [],
    }
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=run_id,
        ticker="TSLA",
        as_of=datetime(2026, 5, 13, tzinfo=timezone.utc),
        assembler_version="trade-insights-v1",
        input_hash="sha256-trade-insights",
        payload=payload,
    )
    return run_id, snapshot_id


def _enqueue_analysis(
    repo: Repository,
    *,
    prompt_version: str = PROMPT_VERSION,
) -> tuple[str, dict]:
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_input = _analysis_input()
    analysis_input["stored_marker"] = "queued-payload"
    analysis_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash=analysis_input["trade_insights_input_hash"],
        analysis_input_hash=analysis_input["analysis_input_hash"],
        analysis_input=analysis_input,
        prompt_version=prompt_version,
        model="codex-default",
    )
    repo.conn.commit()
    return analysis_id, analysis_input


def test_trade_insights_ai_tick_returns_false_when_queue_empty(seeded_db_empty_cards):
    settings = _settings_for_repo(seeded_db_empty_cards)

    assert trade_insights_ai_tick(settings) is False
    assert seeded_db_empty_cards.get_heartbeat("trade_insights_ai_tick") is not None


def test_trade_insights_ai_tick_claims_prepares_releases_and_completes(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    settings = _settings_for_repo(repo)
    analysis_id, analysis_input = _enqueue_analysis(repo)
    observed = {}

    def fake_runner(prompt, schema, *, model, timeout_seconds, max_output_bytes):
        observed["prompt_has_stored_payload"] = "queued-payload" in prompt
        observed["schema"] = schema
        observed["model"] = model
        with psycopg.connect(settings.db_dsn()) as conn:
            check_repo = Repository(conn, schema=settings.db_schema)
            row = check_repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
            observed["visible_before_runner"] = (
                row is not None
                and row["status"] == "running"
                and row["prompt_text"]
                and row["prompt_payload_jsonb"]
                and row["output_schema_jsonb"]
                and row["produced_at"] is not None
            )
            produced_at = row["produced_at"]
        outcome = _sample_outcome_for(analysis_input)
        outcome["analysis_produced_at"] = produced_at.isoformat().replace("+00:00", "Z")
        return outcome

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.run_codex_trade_insights_analysis",
        fake_runner,
    )

    assert trade_insights_ai_tick(settings) is True

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "succeeded"
    assert row["outcome_jsonb"]["ticker"] == "TSLA"
    assert row["markdown"]
    assert row["finished_at"] is not None
    assert observed["visible_before_runner"] is True
    assert observed["prompt_has_stored_payload"] is True
    assert observed["schema"]["title"] == "TradeInsightAiOutcome"
    assert observed["model"] == ""


def test_trade_insights_ai_tick_marks_invalid_output_failed(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    settings = _settings_for_repo(repo)
    analysis_id, _analysis_input_payload = _enqueue_analysis(repo)

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.run_codex_trade_insights_analysis",
        lambda *a, **k: {"not": "valid"},
    )

    assert trade_insights_ai_tick(settings) is True
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert row["error_message"]


def test_trade_insights_ai_tick_marks_obsolete_prompt_version_failed(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    settings = _settings_for_repo(repo)
    analysis_id, _analysis_input_payload = _enqueue_analysis(
        repo,
        prompt_version="trade-insights-ai-v1",
    )
    runner_called = False

    def fake_runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        return {}

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.run_codex_trade_insights_analysis",
        fake_runner,
    )

    assert trade_insights_ai_tick(settings) is True
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert "obsolete prompt_version" in row["error_message"]
    assert runner_called is False


def test_trade_insights_ai_tick_marks_mismatched_produced_at_failed(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    settings = _settings_for_repo(repo)
    analysis_id, analysis_input = _enqueue_analysis(repo)

    def fake_runner(*_args, **_kwargs):
        outcome = _sample_outcome_for(analysis_input)
        outcome["analysis_produced_at"] = "2026-03-24T20:19:42Z"
        return outcome

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.run_codex_trade_insights_analysis",
        fake_runner,
    )

    assert trade_insights_ai_tick(settings) is True
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert "analysis_produced_at" in row["error_message"]


def test_trade_insights_ai_tick_marks_runner_timeout_failed(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    settings = _settings_for_repo(repo)
    analysis_id, _analysis_input_payload = _enqueue_analysis(repo)

    def fake_runner(*_args, **_kwargs):
        raise TradeInsightsAiRunnerError("codex exec timed out")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_ai.run_codex_trade_insights_analysis",
        fake_runner,
    )

    assert trade_insights_ai_tick(settings) is True
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert "timed out" in row["error_message"]
