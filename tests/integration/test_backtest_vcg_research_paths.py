"""Repository tests for the research-scope columns added in migration 059.

API-layer selection isolation lives in tests/unit/api/test_vcg_run_selection.py.
"""

from __future__ import annotations

from datetime import date

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _seed_run(
    repo: RegimeBacktestRepository,
    *,
    run_scope: str,
    credit_proxy: str,
    composite_method: str,
    composite_version: str = "1",
) -> int:
    run_id = repo.insert_run(
        indicator="vcg",
        composite_version=composite_version,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        window_days=21,
        n_days=252,
        params={},
        summary={"extras": {"credit_proxy": credit_proxy}},
        note=None,
        run_scope=run_scope,
        composite_method=composite_method,
        credit_proxy=credit_proxy,
    )
    repo.mark_run_completed(run_id)
    return run_id


def test_insert_run_writes_new_columns(seeded_db_empty_cards) -> None:
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    run_id = _seed_run(
        repo,
        run_scope="research",
        credit_proxy="COMPOSITE_RP3",
        composite_method="risk_parity_3",
        composite_version="2-candidate-rp3",
    )
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT run_scope, composite_method, credit_proxy "
            "FROM uw_scan.regime_backtest_runs WHERE id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    assert row == ("research", "risk_parity_3", "COMPOSITE_RP3")


def test_find_latest_run_defaults_exclude_research(seeded_db_empty_cards) -> None:
    """Production HYG row must win over a NEWER research row at v1."""
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    prod = _seed_run(
        repo,
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
        composite_version="1",
    )
    research = _seed_run(
        repo,
        run_scope="research",
        credit_proxy="JNK",
        composite_method="single_proxy",
        composite_version="1",
    )
    assert research > prod  # research is newer

    latest = repo.find_latest_run("vcg")
    assert latest is not None
    assert latest["id"] == prod
    assert latest["run_scope"] == "production"
    assert latest["credit_proxy"] == "HYG"


def test_find_latest_run_with_credit_proxy_filter(seeded_db_empty_cards) -> None:
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    hyg = _seed_run(
        repo,
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
        composite_version="1",
    )
    _seed_run(
        repo,
        run_scope="production",
        credit_proxy="JNK",
        composite_method="single_proxy",
        composite_version="1",
    )
    latest = repo.find_latest_run("vcg", credit_proxy="HYG")
    assert latest is not None
    assert latest["id"] == hyg


def test_list_research_runs_excludes_production(seeded_db_empty_cards) -> None:
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    _seed_run(
        repo,
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
        composite_version="1",
    )
    r1 = _seed_run(
        repo,
        run_scope="research",
        credit_proxy="COMPOSITE_RP3",
        composite_method="risk_parity_3",
        composite_version="2-candidate-rp3",
    )
    r2 = _seed_run(
        repo,
        run_scope="research",
        credit_proxy="JNK",
        composite_method="single_proxy",
        composite_version="1",
    )
    runs = repo.list_research_runs(indicator="vcg")
    ids = {r["id"] for r in runs}
    assert ids == {r1, r2}
