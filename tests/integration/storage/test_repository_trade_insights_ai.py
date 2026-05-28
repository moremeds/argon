from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.storage.trade_insight_outcomes_repository import (
    TradeInsightOutcomeRepository,
)


def _test_db_dsn() -> str:
    """Rebuild the test DSN from Settings (mirrors conftest._test_settings).

    Cannot rely on `repo.conn.info.dsn` for opening a second connection: in
    CI's pytest-postgresql setup, conn.info.dsn doesn't carry the auth
    credentials that the original connect() pulled from environment.
    """
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to point integration "
            "tests at the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db}).db_dsn()


def _create_snapshot(repo, *, ticker: str = "TSLA", input_hash: str = "ti-hash"):
    run_id = repo.insert_scan_run(ticker)
    payload = {
        "ticker": ticker,
        "header": {
            "confidence_label": "LOW",
            "data_quality_label": "INSUFFICIENT",
            "preferred_idea_id": None,
        },
        "source_reconciliation": {"status": "UNKNOWN"},
        "candidate_structures": [],
    }
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=run_id,
        ticker=ticker,
        as_of=datetime(2026, 5, 13, tzinfo=timezone.utc),
        assembler_version="trade-insights-v1",
        input_hash=input_hash,
        payload=payload,
    )
    return run_id, snapshot_id


def _enqueue(
    repo,
    *,
    snapshot_id: int,
    run_id: int,
    ticker: str = "TSLA",
    trade_insights_input_hash: str = "ti-hash",
    analysis_input_hash: str = "ai-hash",
    analysis_input: dict | None = None,
    model: str = "codex-default",
) -> str:
    return repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker=ticker,
        run_id=run_id,
        trade_insights_input_hash=trade_insights_input_hash,
        analysis_input_hash=analysis_input_hash,
        analysis_input=analysis_input or {"ticker": ticker, "tabs": {"flow": {}}},
        prompt_version="trade-insights-ai-v1",
        model=model,
    )


def test_enqueue_trade_insight_ai_analysis_stores_input_hashes_and_json(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)

    analysis_id = _enqueue(
        repo,
        snapshot_id=snapshot_id,
        run_id=run_id,
        analysis_input={"ticker": "TSLA", "tabs": {"flow": {"net_premium": "100"}}},
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row is not None
    assert row["status"] == "queued"
    assert row["trade_insights_input_hash"] == "ti-hash"
    assert row["analysis_input_hash"] == "ai-hash"
    assert row["analysis_input_jsonb"]["tabs"]["flow"]["net_premium"] == "100"


def test_prepare_trade_insight_ai_analysis_persists_audit_payloads(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)

    repo.prepare_trade_insight_ai_analysis(
        analysis_id,
        prompt_text="Analyze this deterministic payload.",
        prompt_payload={"analysis_produced_at": produced_at.isoformat()},
        output_schema={"type": "object"},
        produced_at=produced_at,
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id)
    assert row["prompt_text"] == "Analyze this deterministic payload."
    assert (
        row["prompt_payload_jsonb"]["analysis_produced_at"] == produced_at.isoformat()
    )
    assert row["output_schema_jsonb"] == {"type": "object"}
    assert row["produced_at"] == produced_at


def test_find_completed_trade_insight_ai_analysis_reuses_most_recent_success(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    first_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    second_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    with repo.conn.cursor() as cur:
        cur.execute(
            f"DROP INDEX {repo._schema}.idx_trade_insight_ai_analyses_succeeded_reuse"
        )
        cur.execute(
            f"""
            UPDATE {repo._schema}.trade_insight_ai_analyses
            SET status='succeeded',
                outcome_jsonb='{{}}'::jsonb,
                markdown='old',
                finished_at=%s
            WHERE analysis_id=%s
            """,
            (datetime.now(timezone.utc) - timedelta(minutes=5), first_id),
        )
        cur.execute(
            f"""
            UPDATE {repo._schema}.trade_insight_ai_analyses
            SET status='succeeded',
                outcome_jsonb='{{}}'::jsonb,
                markdown='new',
                finished_at=%s
            WHERE analysis_id=%s
            """,
            (datetime.now(timezone.utc), second_id),
        )

    found = repo.find_completed_trade_insight_ai_analysis(
        ticker="TSLA",
        analysis_input_hash="ai-hash",
        prompt_version="trade-insights-ai-v1",
        model="codex-default",
    )

    assert found is not None
    assert str(found["analysis_id"]) == second_id
    assert found["markdown"] == "new"


def test_find_latest_trade_insight_ai_analysis_prefers_active_progress(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    succeeded_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    repo.complete_trade_insight_ai_analysis(
        succeeded_id,
        outcome={"schema_version": "trade-insights-ai-v1"},
        markdown="done",
    )
    queued_id = _enqueue(
        repo,
        snapshot_id=snapshot_id,
        run_id=run_id,
        analysis_input_hash="new-ai-hash",
    )

    found = repo.find_latest_trade_insight_ai_analysis(
        ticker="TSLA",
        prompt_version="trade-insights-ai-v1",
        model="codex-default",
    )

    assert found is not None
    assert str(found["analysis_id"]) == queued_id
    assert found["status"] == "queued"


def test_fetch_pending_with_analysis_returns_joined_pending_rows(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    repo.complete_trade_insight_ai_analysis(
        analysis_id,
        outcome={"schema_version": "trade-insights-ai-v1"},
        markdown="done",
    )
    outcome_repo = TradeInsightOutcomeRepository(repo.conn)
    outcome_repo.upsert(
        analysis_id=analysis_id,
        ticker="TSLA",
        provider="codex",
        prompt_version="trade-insights-ai-v1",
        snapshot_date=date(2026, 5, 13),
        snapshot_close=None,
        resolved_outcome="pending",
    )

    rows = outcome_repo.fetch_pending_with_analysis(limit=10)

    assert len(rows) == 1
    assert str(rows[0].analysis_id) == analysis_id
    assert rows[0].snapshot_date == date(2026, 5, 13)
    assert rows[0].ticker == "TSLA"
    assert rows[0].provider == "codex"
    assert rows[0].prompt_version == "trade-insights-ai-v1"
    assert rows[0].outcome_jsonb == {"schema_version": "trade-insights-ai-v1"}


def test_changed_analysis_input_hash_does_not_reuse_completed_row(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    repo.complete_trade_insight_ai_analysis(
        analysis_id,
        outcome={"schema_version": "trade-insights-ai-v1"},
        markdown="done",
    )

    found = repo.find_completed_trade_insight_ai_analysis(
        ticker="TSLA",
        analysis_input_hash="different-ai-hash",
        prompt_version="trade-insights-ai-v1",
        model="codex-default",
    )

    assert found is None


def test_enqueue_reuses_active_row_for_same_hash(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)

    first_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    second_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    assert first_id == second_id


def test_failed_analysis_can_enqueue_new_row_for_same_hash(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)

    first_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    repo.fail_trade_insight_ai_analysis(first_id, "codex failed")
    second_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    assert first_id != second_id


def test_claim_transitions_next_queued_analysis_to_running(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    claimed = repo.claim_next_trade_insight_ai_analysis()

    assert claimed is not None
    assert str(claimed["analysis_id"]) == analysis_id
    assert claimed["status"] == "running"
    assert claimed["started_at"] is not None
    row = repo.get_trade_insight_ai_analysis(analysis_id)
    assert row["status"] == "running"


def test_claim_reclaims_stale_running_analysis(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    stale_started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {repo._schema}.trade_insight_ai_analyses
            SET status='running', started_at=%s
            WHERE analysis_id=%s
            """,
            (stale_started_at, analysis_id),
        )

    claimed = repo.claim_next_trade_insight_ai_analysis(
        stale_running_before=datetime.now(timezone.utc) - timedelta(minutes=5)
    )

    assert claimed is not None
    assert str(claimed["analysis_id"]) == analysis_id
    assert claimed["status"] == "running"
    assert claimed["started_at"] > stale_started_at


def test_two_concurrent_claimers_get_distinct_rows(seeded_db_empty_cards):
    """Two `ai` workers on separate connections must not double-process.

    PR #53 ships a second AI worker; correctness relies on
    `claim_next_trade_insight_ai_analysis` using FOR UPDATE SKIP LOCKED so
    the second claimer skips the row the first one just locked. Without
    that, both workers would race on `status='queued'` reads and could both
    flip the same row to running.
    """
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo, ticker="TSLA", input_hash="ti-1")
    id_a = _enqueue(
        repo,
        snapshot_id=snapshot_id,
        run_id=run_id,
        analysis_input_hash="ai-1",
        analysis_input={"ticker": "TSLA", "tabs": {"flow": {"x": 1}}},
    )
    id_b = _enqueue(
        repo,
        snapshot_id=snapshot_id,
        run_id=run_id,
        analysis_input_hash="ai-2",
        analysis_input={"ticker": "TSLA", "tabs": {"flow": {"x": 2}}},
    )
    assert id_a != id_b
    repo.conn.commit()

    # Open a second connection on the same DSN — simulates a separate worker.
    conn_b = psycopg.connect(_test_db_dsn())
    try:
        repo_b = Repository(conn_b, schema=repo._schema)

        # Claim from worker A — its inner SELECT FOR UPDATE locks one row.
        claimed_a = repo.claim_next_trade_insight_ai_analysis()
        # Claim from worker B BEFORE A commits — must SKIP the locked row
        # and grab the other queued one (or return None if SKIP LOCKED is
        # broken and B sees only the row A locked).
        claimed_b = repo_b.claim_next_trade_insight_ai_analysis()

        assert claimed_a is not None, "worker A should claim a row"
        assert claimed_b is not None, (
            "worker B should claim the OTHER row, not skip out — "
            "FOR UPDATE SKIP LOCKED is the contract here"
        )
        assert str(claimed_a["analysis_id"]) != str(claimed_b["analysis_id"]), (
            "two workers claimed the SAME row — concurrency invariant broken"
        )
        assert {str(claimed_a["analysis_id"]), str(claimed_b["analysis_id"])} == {
            id_a,
            id_b,
        }

        # Commit both so the third claim sees both as 'running'; with no
        # queued or stale-running rows, it should return None.
        repo.conn.commit()
        repo_b.conn.commit()
        third = repo.claim_next_trade_insight_ai_analysis()
        assert third is None, "no more queued rows; third claim should be empty"
    finally:
        conn_b.close()


def test_complete_stores_outcome_markdown_and_preserves_produced_at(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)
    produced_at = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
    repo.prepare_trade_insight_ai_analysis(
        analysis_id,
        prompt_text="prompt",
        prompt_payload={"analysis_produced_at": "2026-03-24T20:18:42Z"},
        output_schema={"type": "object"},
        produced_at=produced_at,
    )

    repo.complete_trade_insight_ai_analysis(
        analysis_id,
        outcome={"schema_version": "trade-insights-ai-v1"},
        markdown="markdown",
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id)
    assert row["status"] == "succeeded"
    assert row["outcome_jsonb"] == {"schema_version": "trade-insights-ai-v1"}
    assert row["markdown"] == "markdown"
    assert row["produced_at"] == produced_at
    assert row["finished_at"] is not None


def test_fail_stores_error_and_fetch_scopes_by_ticker(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    repo.fail_trade_insight_ai_analysis(analysis_id, "codex timed out")

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert row["error_message"] == "codex timed out"
    assert row["finished_at"] is not None
    assert row["raw_outcome_jsonb"] is None
    assert repo.get_trade_insight_ai_analysis(analysis_id, ticker="AAPL") is None


def test_fail_persists_raw_outcome_when_validation_rejected(seeded_db_empty_cards):
    """When a runner returned a parseable JSON object that downstream
    validation rejected, the raw payload must survive in raw_outcome_jsonb so
    the failure is diagnosable without re-running."""
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    rejected = {
        "schema_version": "trade-insights-ai-v5.3",
        "best_expressions": [
            {"idea_id": "F", "status_observed": "preferred", "junk": 1},
        ],
    }
    repo.fail_trade_insight_ai_analysis(
        analysis_id,
        "status_observed changed for idea_id F",
        raw_outcome=rejected,
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert row["error_message"] == "status_observed changed for idea_id F"
    assert row["raw_outcome_jsonb"] == rejected


def test_complete_persists_provider_metadata_jsonb(seeded_db_empty_cards):
    """Provider-specific runtime metadata (DeepSeek's reasoning_content +
    output_channel + byte sizes) must round-trip through Jsonb() into the
    provider_metadata_jsonb column."""
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    metadata = {
        "reasoning_content": "Step 1 — pick X.\nStep 2 — confirm.",
        "reasoning_bytes": 36,
        "output_channel": "tool_calls",
    }
    repo.complete_trade_insight_ai_analysis(
        analysis_id,
        outcome={"schema_version": "trade-insights-ai-v1"},
        markdown="done",
        provider_metadata=metadata,
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "succeeded"
    assert row["provider_metadata_jsonb"] == metadata


def test_complete_leaves_provider_metadata_null_when_not_passed(
    seeded_db_empty_cards,
):
    """Codex/Claude runners do not populate reasoning_content; orchestrator
    passes provider_metadata=None for them. The column must stay NULL to
    preserve the 'metadata is provider-specific and optional' contract."""
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    repo.complete_trade_insight_ai_analysis(
        analysis_id,
        outcome={"schema_version": "trade-insights-ai-v1"},
        markdown="done",
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "succeeded"
    assert row["provider_metadata_jsonb"] is None


def test_fail_persists_provider_metadata_for_validation_failures(
    seeded_db_empty_cards,
):
    """When a runner returns reasoning_content and the validator REJECTS the
    outcome, the reasoning trace must survive in provider_metadata_jsonb so
    operators can diagnose how the model arrived at the invalid output. The
    raw outcome and metadata are persisted in parallel via fail_*."""
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _create_snapshot(repo)
    analysis_id = _enqueue(repo, snapshot_id=snapshot_id, run_id=run_id)

    rejected = {"schema_version": "trade-insights-ai-v5.3", "junk": 1}
    metadata = {
        "reasoning_content": "I decided to emit junk because reasons.",
        "reasoning_bytes": 40,
        "output_channel": "tool_calls",
    }
    repo.fail_trade_insight_ai_analysis(
        analysis_id,
        "validator rejected unknown field 'junk'",
        raw_outcome=rejected,
        provider_metadata=metadata,
    )

    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker="TSLA")
    assert row["status"] == "failed"
    assert row["raw_outcome_jsonb"] == rejected
    assert row["provider_metadata_jsonb"] == metadata
