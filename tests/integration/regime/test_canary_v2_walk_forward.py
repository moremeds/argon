"""Integration tests for canary v2-A walk-forward, robustness, cleanup,
parity, and dispatcher. Built up across Tasks 4, 6, 7, 8, 10, 11.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from datetime import date as _date

import pytest

from scripts.backtest_canary import cmd_walk_forward
from tests.integration.regime._canary_v2a_fixture import (
    seed_v1_walk_forward_runs,
    seed_vol_index_full_history,
)
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

pytestmark = pytest.mark.integration


def _wf_args(
    *, composite_version: int, batch_id: str | None = None
) -> argparse.Namespace:
    return argparse.Namespace(
        composite_version=composite_version,
        batch_id=batch_id,
    )


def _rb_args(
    *, composite_version: int, batch_id: str | None = None
) -> argparse.Namespace:
    return argparse.Namespace(
        composite_version=composite_version,
        batch_id=batch_id,
    )


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


# --- Task 6: v2 walk-forward tests ---


def test_v2_walk_forward_writes_6_research_rows(seeded_db_empty_cards):
    """cmd_walk_forward with composite_version=2 writes 6 research-scoped
    walk-forward rows, all sharing a batch_id, with WF-1..WF-6 window_ids."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21)
    )

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id', params->>'window_id', composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward' "
            f"ORDER BY params->>'window_id'"
        )
        rows = cur.fetchall()

    assert len(rows) == 6
    batch_ids = {r[0] for r in rows}
    assert len(batch_ids) == 1 and next(iter(batch_ids)) is not None
    window_ids = {r[1] for r in rows}
    assert window_ids == {f"WF-{i}" for i in range(1, 7)}
    for r in rows:
        assert r[2] == "2"
        assert r[3] == "research"


def test_v2_walk_forward_preserves_v1_production_rows(seeded_db_empty_cards):
    """v1 walk-forward production rows survive v2 walk-forward. Spec §6 Layer 2."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    v1_ids = seed_v1_walk_forward_runs(conn, schema=schema)
    seed_vol_index_full_history(
        conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21)
    )

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs WHERE id = ANY(%s)",
            (v1_ids,),
        )
        assert cur.fetchone()[0] == 6


def test_v2_walk_forward_summary_has_composite_aucs(seeded_db_empty_cards):
    """Each v2 walk-forward run's summary.aucs.composite contains the three
    horizons. AC-F4 reads these."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21)
    )

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT summary->'aucs'->'composite' "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward' LIMIT 1"
        )
        composite_aucs = cur.fetchone()[0]

    assert composite_aucs is not None
    for key in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert key in composite_aucs


# --- Task 7: v2 robustness tests ---


def test_v2_robustness_writes_1_research_row(seeded_db_empty_cards):
    """cmd_robustness with composite_version=2 writes 1 research-scoped row."""
    from scripts.backtest_canary import cmd_robustness

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21)
    )

    cmd_robustness(conn, schema=schema, args=_rb_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='robustness'"
        )
        assert cur.fetchone()[0] == 1


def test_v2_robustness_shares_batch_id_when_chained(seeded_db_empty_cards):
    """If --batch-id is passed, robustness row carries the same batch_id."""
    from scripts.backtest_canary import cmd_robustness

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(
        conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21)
    )

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT params->>'batch_id' "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward'"
        )
        wf_batch = cur.fetchone()[0]

    cmd_robustness(
        conn, schema=schema, args=_rb_args(composite_version=2, batch_id=wf_batch)
    )

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id' FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='robustness'"
        )
        rb_batch = cur.fetchone()[0]

    assert rb_batch == wf_batch
