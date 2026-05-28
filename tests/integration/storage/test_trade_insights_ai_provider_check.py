"""Integration: trade_insight_ai_analyses.provider CHECK constraint after
migration 063 admits deepseek but still rejects unknown providers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest


def _seed_snapshot(repo) -> str:
    """Create a minimal trade_insight_snapshot to satisfy the FK on
    trade_insight_ai_analyses.snapshot_id."""
    run_id = repo.insert_scan_run("TEST")
    return repo.upsert_trade_insight_snapshot(
        run_id=run_id,
        ticker="TEST",
        as_of=datetime(2026, 5, 28, tzinfo=timezone.utc),
        assembler_version="trade-insights-v1",
        input_hash="sha256-provider-check",
        payload={"ticker": "TEST"},
    )


def _insert_with_provider(repo, snapshot_id, provider: str, model: str) -> None:
    """Insert a row with the given provider. Caller controls txn."""
    sql = (
        f"INSERT INTO {repo._schema}.trade_insight_ai_analyses ("
        "  analysis_id, snapshot_id, ticker, run_id,"
        "  trade_insights_input_hash, analysis_input_hash,"
        "  analysis_input_jsonb, prompt_version, model, provider,"
        "  status, requested_at"
        ") VALUES (%s, %s, 'TEST', 1, 'h1', 'h2', '{}'::jsonb,"
        "  'trade-insights-ai-v5.3', %s, %s, 'queued', %s)"
    )
    with repo._conn.cursor() as cur:
        cur.execute(
            sql,
            (uuid4(), snapshot_id, model, provider, datetime.now(timezone.utc)),
        )


def test_provider_check_constraint_accepts_deepseek(seeded_db_empty_cards) -> None:
    """Insert with provider='deepseek' MUST succeed after migration 063.
    Without 063, the CHECK constraint from 053 would reject this row."""
    repo = seeded_db_empty_cards
    snapshot_id = _seed_snapshot(repo)
    _insert_with_provider(
        repo, snapshot_id, provider="deepseek", model="deepseek-v4-pro"
    )
    repo._conn.commit()


def test_provider_check_constraint_still_rejects_unknown(
    seeded_db_empty_cards,
) -> None:
    """Regression guard: 063 widens the CHECK constraint to add deepseek;
    it does NOT remove it. Inserting 'openai' must still fail."""
    repo = seeded_db_empty_cards
    snapshot_id = _seed_snapshot(repo)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_with_provider(repo, snapshot_id, provider="openai", model="gpt-4")
    repo._conn.rollback()
