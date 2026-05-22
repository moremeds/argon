"""Tests for provider-aware trade_insights_ai repository methods (Task 3)."""

from __future__ import annotations

from uw_scan.storage.repository import Repository


def _seed_snapshot(repo: Repository) -> tuple[int, int]:
    """Insert a minimal scan_run + trade_insight_snapshot; return (run_id, snapshot_id)."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs(ticker, status) "
            "VALUES ('TSLA', 'finished') RETURNING run_id"
        )
        run_id = cur.fetchone()[0]
        cur.execute(
            f"INSERT INTO {repo._schema}.trade_insight_snapshots("
            "  run_id, ticker, assembler_version, input_hash, payload_jsonb) "
            "VALUES (%s, 'TSLA', 'trade-insights-v1', 'ti-hash', '{}'::jsonb) "
            "RETURNING snapshot_id",
            (run_id,),
        )
        snapshot_id = cur.fetchone()[0]
    repo.conn.commit()
    return run_id, snapshot_id


def test_enqueue_with_provider_creates_separate_rows_per_provider(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={"k": "v"},
        prompt_version="trade-insights-ai-v4",
        model="codex-default",
        provider="codex",
    )
    claude_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={"k": "v"},
        prompt_version="trade-insights-ai-v4",
        model="claude-default",
        provider="claude",
    )
    assert codex_id != claude_id


def test_unique_reuse_allows_same_input_different_providers(
    seeded_db_empty_cards: Repository,
) -> None:
    """Load-bearing for migration 053: same input hash + prompt_version
    + model BUT different provider must NOT collide on the active-reuse index."""
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={"k": "v"},
        prompt_version="v",
        model="m",
        provider="codex",
    )
    # Same hash/version/model — only provider differs. Must succeed.
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={"k": "v"},
        prompt_version="v",
        model="m",
        provider="claude",
    )


def test_claim_next_with_provider_filter_returns_only_matching_rows(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={},
        prompt_version="v",
        model="m",
        provider="codex",
    )
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="hb",
        analysis_input={},
        prompt_version="v",
        model="m",
        provider="claude",
    )
    claimed = repo.claim_next_trade_insight_ai_analysis(provider="codex")
    assert claimed is not None
    assert str(claimed["analysis_id"]) == str(codex_id)
    assert claimed["provider"] == "codex"


def test_claim_next_without_provider_filter_returns_any_provider(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={},
        prompt_version="v",
        model="m",
        provider="claude",
    )
    claimed = repo.claim_next_trade_insight_ai_analysis(provider=None)
    assert claimed is not None
    assert claimed["provider"] == "claude"


def test_latest_pair_returns_keyed_dict_per_provider(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={},
        prompt_version="v",
        model="m",
        provider="codex",
    )
    repo.complete_trade_insight_ai_analysis(
        codex_id,
        outcome={"x": 1},
        markdown="md",
        resolved_model="codex-default",
    )
    repo.conn.commit()
    pair = repo.find_latest_trade_insight_ai_analyses_per_provider(
        ticker="TSLA",
        prompt_version="v",
    )
    assert pair["codex"] is not None
    assert pair["claude"] is None
    assert str(pair["codex"]["analysis_id"]) == str(codex_id)
    # Resolved model should overwrite the configured one
    assert pair["codex"]["model"] == "codex-default"


def test_complete_persists_resolved_model_overriding_initial(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    aid = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={},
        prompt_version="v",
        model="opus",
        provider="claude",
    )
    repo.complete_trade_insight_ai_analysis(
        aid,
        outcome={"x": 1},
        markdown="md",
        resolved_model="claude-opus-4-7",
    )
    repo.conn.commit()
    row = repo.get_trade_insight_ai_analysis(aid)
    assert row is not None
    assert row["model"] == "claude-opus-4-7"
    assert row["provider"] == "claude"


def test_find_reusable_filters_by_provider(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    run_id, snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=run_id,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={},
        prompt_version="v",
        model="m",
        provider="codex",
    )
    repo.complete_trade_insight_ai_analysis(
        codex_id,
        outcome={"x": 1},
        markdown="md",
        resolved_model="m",
    )
    repo.conn.commit()
    # Same key for claude should NOT find the codex row.
    found = repo.find_reusable_trade_insight_ai_analysis(
        ticker="TSLA",
        analysis_input_hash="ha",
        prompt_version="v",
        model="m",
        provider="claude",
    )
    assert found is None
    found_codex = repo.find_reusable_trade_insight_ai_analysis(
        ticker="TSLA",
        analysis_input_hash="ha",
        prompt_version="v",
        model="m",
        provider="codex",
    )
    assert found_codex is not None
