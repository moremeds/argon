"""Integration tests for canary --form-sweep-full and its renderer.

All tests use the synthetic vol-complex fixture in
_canary_form_sweep_fixture.py and the project's pytest-postgresql fixture
(real Postgres, migrations applied per tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest


def test_delete_runs_by_batch_id_removes_rows_and_cascades_daily(
    seeded_db_empty_cards,
):
    """Insert a 4-row form_sweep_full batch + daily rows, then delete
    by batch_id. All runs AND daily rows must be gone."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    batch_id = str(uuid.uuid4())

    inserted_run_ids: list[int] = []
    for form in ("linear", "convex", "concave", "sigmoid"):
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=100,
            params={
                "score_form": form,
                "phase": "form_sweep_full",
                "batch_id": batch_id,
                "purpose": "candidate_discovery_not_validation",
            },
            summary={
                "is_winning_form": False,
                "score_form": form,
                "batch_id": batch_id,
                "phase": "form_sweep_full",
            },
            run_scope="research",
        )
        inserted_run_ids.append(run_id)
        repo.bulk_insert_daily(
            run_id,
            [
                {
                    "trade_date": date(2024, 1, 2),
                    "score": 20.0,
                    "level": "NONE",
                    "payload": {"raw_score": 20.0},
                },
            ],
        )

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (batch_id,),
        )
        assert cur.fetchone()[0] == 4
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily "
            f"WHERE run_id = ANY(%s)",
            (inserted_run_ids,),
        )
        assert cur.fetchone()[0] == 4

    n_deleted = repo.delete_runs_by_batch_id(batch_id)
    assert n_deleted == 4

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (batch_id,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily "
            f"WHERE run_id = ANY(%s)",
            (inserted_run_ids,),
        )
        assert cur.fetchone()[0] == 0


def test_delete_runs_by_batch_id_returns_zero_when_no_match(seeded_db_empty_cards):
    """Calling with an unknown batch_id is a no-op returning 0."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    n = repo.delete_runs_by_batch_id("00000000-0000-0000-0000-000000000000")
    assert n == 0


def test_delete_runs_by_batch_id_scoped_to_canary_research_form_sweep_full(
    seeded_db_empty_cards,
):
    """A row with the same batch_id but a DIFFERENT indicator/scope/phase
    must NOT be deleted. Defends against UUID4 collisions and accidental
    over-scoping if the method is reused without thinking."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    batch_id = str(uuid.uuid4())

    lookalikes = [
        # Wrong indicator
        dict(
            indicator="vcg",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=10,
            params={"phase": "form_sweep_full", "batch_id": batch_id},
            summary={"phase": "form_sweep_full"},
            run_scope="research",
        ),
        # Wrong run_scope
        dict(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=10,
            params={"phase": "form_sweep_full", "batch_id": batch_id},
            summary={"phase": "form_sweep_full"},
            run_scope="production",
        ),
        # Wrong phase
        dict(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=10,
            params={"phase": "calibrate", "batch_id": batch_id},
            summary={"phase": "calibrate"},
            run_scope="research",
        ),
    ]
    lookalike_ids = [repo.insert_run(**spec) for spec in lookalikes]

    target_id = repo.insert_run(
        indicator="canary",
        composite_version="1",
        start_date=date(2011, 2, 8),
        end_date=date(2026, 5, 21),
        window_days=350,
        n_days=10,
        params={
            "score_form": "linear",
            "phase": "form_sweep_full",
            "batch_id": batch_id,
            "purpose": "candidate_discovery_not_validation",
        },
        summary={
            "is_winning_form": False,
            "score_form": "linear",
            "batch_id": batch_id,
            "phase": "form_sweep_full",
        },
        run_scope="research",
    )

    n_deleted = repo.delete_runs_by_batch_id(batch_id)
    assert n_deleted == 1, "only the in-scope target row should be deleted"

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {db_schema}.regime_backtest_runs WHERE id = ANY(%s)",
            (lookalike_ids,),
        )
        remaining = [r[0] for r in cur.fetchall()]
        assert sorted(remaining) == sorted(lookalike_ids), (
            "lookalike rows must remain — scoping violation"
        )
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs WHERE id = %s",
            (target_id,),
        )
        assert cur.fetchone()[0] == 0
