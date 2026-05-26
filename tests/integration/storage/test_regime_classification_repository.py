from __future__ import annotations

from datetime import date

import pytest

from uw_scan.storage.regime_classification_repository import (
    ClassificationRunAlreadyExists,
    RegimeClassificationRepository,
)


def test_insert_classification_run_uses_credit_proxy_sentinel(seeded_db_empty_cards):
    """classification runs: credit_proxy='CLASSIFICATION', composite_method='classification_accuracy'."""
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    run_id = rcr.insert_classification_run(
        vcg_source_run_id=42,
        composite_version="1",
        eval_start=date(2007, 1, 3),
        eval_end=date(2026, 5, 26),
        label_version=1,
        n_days=4545,
        summary={"placeholder": True},
        note="smoke test",
    )
    assert run_id > 0
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT run_scope, composite_method, indicator, credit_proxy, window_days, params "
            f"FROM {repo._schema}.regime_backtest_runs WHERE id=%s",
            (run_id,),
        )
        row = cur.fetchone()
    assert row[0] == "research"
    assert row[1] == "classification_accuracy"
    assert row[2] == "vcg"
    assert row[3] == "CLASSIFICATION"
    assert row[4] == 1
    assert row[5]["label_version"] == 1
    assert row[5]["vcg_source_run_id"] == 42


def test_bulk_insert_daily_classifications_stores_full_components(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    run_id = rcr.insert_classification_run(
        vcg_source_run_id=42,
        composite_version="1",
        eval_start=date(2007, 1, 3),
        eval_end=date(2026, 5, 26),
        label_version=1,
        n_days=1,
        summary={},
        note="smoke",
    )
    rcr.bulk_insert_daily_classifications(
        run_id,
        [
            {
                "trade_date": date(2020, 3, 23),
                "vcg_label": "RISK_OFF",
                "truth_label": "PANIC",
                "match": False,
                "label_components": {
                    "vix_pct": 0.99,
                    "vvix_pct": 0.98,
                    "rv_pct": 0.97,
                    "credit_pct": 0.94,
                    "dd": -0.30,
                    "NFCI_value": 0.85,
                    "instant_label": "PANIC",
                },
                "label_version": 1,
            },
        ],
    )
    repo.conn.commit()
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT level, payload FROM {repo._schema}.regime_backtest_daily WHERE run_id=%s",
            (run_id,),
        )
        row = cur.fetchone()
    assert row[0] == "RISK_OFF"
    assert row[1]["truth_label"] == "PANIC"
    assert row[1]["label_components"]["NFCI_value"] == 0.85  # v0.3 / CL-3


def test_insert_complete_run_is_atomic(seeded_db_empty_cards):
    """v0.3 / CL-8: insert + bulk + mark in one transaction."""
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    run_id = rcr.insert_complete_run(
        vcg_source_run_id=42,
        composite_version="1",
        eval_start=date(2007, 1, 3),
        eval_end=date(2026, 5, 26),
        label_version=1,
        summary={"placeholder": True},
        note="atomic test",
        daily_rows=[
            {
                "trade_date": date(2020, 3, 23),
                "vcg_label": "RISK_OFF",
                "truth_label": "PANIC",
                "match": False,
                "label_components": {},
                "label_version": 1,
            },
        ],
    )
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT completed_at FROM {repo._schema}.regime_backtest_runs WHERE id=%s",
            (run_id,),
        )
        assert cur.fetchone()[0] is not None


def test_insert_complete_run_catches_unique_violation(seeded_db_empty_cards):
    """v0.3 / CR-2: migration 062's unique index -> raises typed exception."""
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    args = dict(
        vcg_source_run_id=42,
        composite_version="1",
        eval_start=date(2007, 1, 3),
        eval_end=date(2026, 5, 26),
        label_version=1,
        summary={},
        note="dup test",
        daily_rows=[
            {
                "trade_date": date(2020, 3, 23),
                "vcg_label": "NORMAL",
                "truth_label": "NORMAL",
                "match": True,
                "label_components": {},
                "label_version": 1,
            },
        ],
    )
    run_id = rcr.insert_complete_run(**args)
    assert run_id > 0
    with pytest.raises(ClassificationRunAlreadyExists):
        rcr.insert_complete_run(**args)
