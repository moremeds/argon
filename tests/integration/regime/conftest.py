"""Fixtures for regime integration tests.

`seed_cri_backtest_run` populates uw_scan.regime_backtest_runs with one
completed CRI run whose summary.oos.versions[] carries the LAST_KNOWN_AUC_*
constants from cri_scorers.py. The OOS gate test in test_cri_oos_gate.py
reads this run back. See the calibration-provenance contract in that file's
module docstring.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.cards.cri_scorers import (
    COMPOSITE_VERSION,
    LAST_KNOWN_AUC_DD5,
    LAST_KNOWN_AUC_DD10,
)
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


@pytest.fixture
def seed_cri_backtest_run(seeded_db_empty_cards) -> int:
    """Insert one completed CRI run + a minimal daily row into the test DB.

    Function-scoped, matching `seeded_db_empty_cards` which drops+migrates
    the schema per test. AUC numbers come from cri_scorers.py constants so
    a calibration PR's diff exposes any staleness.
    """
    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    existing = rb.find_latest_run("cri", composite_version=str(COMPOSITE_VERSION))
    if existing is not None:
        return int(existing["id"])

    run_id = rb.insert_run(
        indicator="cri",
        composite_version=str(COMPOSITE_VERSION),
        start_date=date(2007, 1, 3),
        end_date=date(2026, 5, 15),
        window_days=150,
        n_days=4873,
        params={"rolling_window": 150, "source": "seed_cri_backtest_run"},
        summary={
            "oos": {
                "as_of": "2026-05-25",
                "notebook": "scripts/backtest_cri.py",
                "method": (
                    "Forward-drawdown labels: dd5 = SPX -5% within 20 sessions; "
                    "dd10 = SPX -10% within 60 sessions."
                ),
                "labels": [
                    {
                        "name": "label_dd5",
                        "definition": "SPX -5% drawdown within 20 trading days",
                    },
                    {
                        "name": "label_dd10",
                        "definition": "SPX -10% drawdown within 60 trading days",
                    },
                ],
                "scores": [
                    {
                        "model": "CRI v1 (frozen baseline)",
                        "auc_dd5": 0.620,
                        "auc_vix30": None,
                        "auc_dd10": 0.647,
                    },
                    {
                        "model": f"CRI v{COMPOSITE_VERSION} (this run)",
                        "auc_dd5": LAST_KNOWN_AUC_DD5,
                        "auc_vix30": None,
                        "auc_dd10": LAST_KNOWN_AUC_DD10,
                    },
                ],
                "versions": [
                    {
                        "label": "CRI v1",
                        "version": 1,
                        "auc_dd5": 0.620,
                        "auc_dd10": 0.647,
                        "n_observations": 4873,
                        "notes": "Frozen baseline.",
                    },
                    {
                        "label": f"CRI v{COMPOSITE_VERSION}",
                        "version": COMPOSITE_VERSION,
                        "auc_dd5": LAST_KNOWN_AUC_DD5,
                        "auc_dd10": LAST_KNOWN_AUC_DD10,
                        "n_observations": 4873,
                        "notes": (
                            "Recorded by scripts/backtest_cri.py against the 20y "
                            "vol_index_daily history. Bumping COMPOSITE_VERSION "
                            "in cri_scorers.py requires updating LAST_KNOWN_AUC_* "
                            "in the same diff."
                        ),
                    },
                ],
                "interpretation": (
                    "Seed reads LAST_KNOWN_AUC_* from cri_scorers.py — "
                    "calibration-provenance contract enforced in PR review."
                ),
            },
            "extras": {"named_crash_hits": {}, "fired_count": 0},
        },
        note="seed_cri_backtest_run fixture",
    )
    rb.bulk_insert_daily(
        run_id,
        [
            {
                "trade_date": date(2026, 5, 15),
                "score": 12.0,
                "level": "LOW",
                "payload": {},
            }
        ],
    )
    rb.mark_run_completed(run_id)
    return run_id
