"""Integration tests for canary v2-A walk-forward, robustness, cleanup,
parity, and dispatcher. Built up across Tasks 4, 6, 7, 8, 10, 11.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

pytestmark = pytest.mark.integration


def _insert_research_run(
    repo: RegimeBacktestRepository,
    *,
    phase: str,
    window_id: str | None,
    batch_id: str,
    composite_version: str = "2",
) -> int:
    """Helper: insert one research-scoped canary run with the given phase."""
    params = {"phase": phase, "batch_id": batch_id, "score_form": "linear"}
    if window_id is not None:
        params["window_id"] = window_id
    return repo.insert_run(
        indicator="canary",
        composite_version=composite_version,
        start_date=date(2020, 1, 2),
        end_date=date(2020, 12, 30),
        window_days=350,
        n_days=250,
        params=params,
        summary={"is_winning_form": False, "phase": phase},
        run_scope="research",
    )


def test_delete_canary_research_runs_by_batch_id_and_phase_walk_forward(
    seeded_db_empty_cards,
):
    """Insert 6 walk-forward + 1 robustness + 4 form-sweep research rows.
    Delete walk-forward batch by (batch_id, phase='walk_forward').
    Assert: 6 walk-forward rows gone; robustness + form-sweep rows preserved.
    """
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)

    wf_batch = str(uuid.uuid4())
    fs_batch = str(uuid.uuid4())

    wf_ids = [
        _insert_research_run(
            repo, phase="walk_forward", window_id=f"WF-{i}", batch_id=wf_batch
        )
        for i in range(1, 7)
    ]
    robustness_id = _insert_research_run(
        repo, phase="robustness", window_id=None, batch_id=wf_batch
    )
    fs_ids = [
        _insert_research_run(
            repo,
            phase="form_sweep_full",
            window_id=None,
            batch_id=fs_batch,
            composite_version="1",
        )
        for _ in range(4)
    ]
    for rid in wf_ids + [robustness_id] + fs_ids:
        repo.mark_run_completed(rid)

    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        wf_batch, "walk_forward"
    )

    assert deleted == 6
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {schema}.regime_backtest_runs WHERE id = %s",
            (robustness_id,),
        )
        assert cur.fetchone() is not None
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (fs_batch,),
        )
        assert cur.fetchone()[0] == 4


def test_delete_canary_research_runs_by_batch_id_and_phase_no_op_when_no_match(
    seeded_db_empty_cards,
):
    """Returns 0 when no rows match (wrong batch_id, wrong phase, etc.)."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)
    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        str(uuid.uuid4()), "walk_forward"
    )
    assert deleted == 0


def test_delete_canary_research_runs_by_batch_id_and_phase_does_not_touch_production(
    seeded_db_empty_cards,
):
    """Defense-in-depth: production rows MUST NOT be deleted even on collision."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)

    same_batch = str(uuid.uuid4())
    research_id = _insert_research_run(
        repo, phase="walk_forward", window_id="WF-1", batch_id=same_batch
    )
    repo.mark_run_completed(research_id)

    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {schema}.regime_backtest_runs "
            f"(indicator, composite_version, start_date, end_date, window_days, "
            f" n_days, params, summary, run_scope, completed_at) "
            f"VALUES ('canary', '1', '2020-01-02', '2020-12-30', 350, 250, "
            f"        %s::jsonb, '{{}}'::jsonb, 'production', now()) RETURNING id",
            (
                f'{{"phase": "walk_forward", "batch_id": "{same_batch}", '
                f'"window_id": "WF-1", "score_form": "linear"}}',
            ),
        )
        prod_id = cur.fetchone()[0]
    conn.commit()

    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        same_batch, "walk_forward"
    )
    assert deleted == 1
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {schema}.regime_backtest_runs WHERE id = %s",
            (prod_id,),
        )
        assert cur.fetchone() is not None
