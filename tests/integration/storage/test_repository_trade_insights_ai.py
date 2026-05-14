from __future__ import annotations

from datetime import datetime, timedelta, timezone


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
    assert row["prompt_payload_jsonb"]["analysis_produced_at"] == produced_at.isoformat()
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
    assert repo.get_trade_insight_ai_analysis(analysis_id, ticker="AAPL") is None
