from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from uw_scan.cards import vcg_scoring
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _seed_run(
    conn: psycopg.Connection,
    *,
    composite_version: str,
    run_scope: str,
    credit_proxy: str,
    composite_method: str,
    completed: bool = True,
) -> int:
    completed_at = datetime.now(timezone.utc) if completed else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
              (indicator, composite_version, start_date, end_date,
               window_days, n_days, params, summary, note,
               run_scope, composite_method, credit_proxy,
               created_at, completed_at)
            VALUES ('vcg', %s, '2007-01-03', '2024-12-31',
                    252, 4500, '{}'::jsonb, '{}'::jsonb, 'test seed',
                    %s, %s, %s, NOW(), %s)
            RETURNING id
            """,
            (composite_version, run_scope, composite_method, credit_proxy, completed_at),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_default_validation_selects_v2_after_bump(seeded_db_empty_cards) -> None:
    assert vcg_scoring.COMPOSITE_VERSION == 2
    conn = seeded_db_empty_cards.conn

    v1_prod_id = _seed_run(
        conn,
        composite_version="1",
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
    )
    v2_prod_id = _seed_run(
        conn,
        composite_version="2",
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
    )
    v2_research_id = _seed_run(
        conn,
        composite_version="2",
        run_scope="research",
        credit_proxy="HYG",
        composite_method="single_proxy",
    )
    conn.commit()

    repo = RegimeBacktestRepository(conn)
    selected = repo.find_latest_run("vcg")

    assert selected is not None
    assert selected["id"] == v2_prod_id, (
        f"expected production v2 id={v2_prod_id}, got id={selected['id']}; "
        f"v1_prod={v1_prod_id}, v2_research={v2_research_id}"
    )
    assert selected["composite_version"] == "2"
    assert selected["run_scope"] == "production"


def test_research_v2_does_not_satisfy_production_default(
    seeded_db_empty_cards,
) -> None:
    assert vcg_scoring.COMPOSITE_VERSION == 2
    conn = seeded_db_empty_cards.conn
    _seed_run(
        conn,
        composite_version="2",
        run_scope="research",
        credit_proxy="HYG",
        composite_method="single_proxy",
    )
    conn.commit()

    repo = RegimeBacktestRepository(conn)
    selected = repo.find_latest_run("vcg")

    assert selected is None
