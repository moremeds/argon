"""Block-merge gate. Reads the latest is_winning_form=true row from
regime_backtest_runs for indicator='canary' at the current composite_version.

Acceptance bar — see spec §8.6 + §8.7.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.cards.canary_calibration import COMPOSITE_VERSION
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

pytestmark = pytest.mark.integration

# These values are SET in the v1 publish PR after the report runs.
LAST_KNOWN_AUC_UP5D_2PCT = 0.55
LAST_KNOWN_AUC_UP20D_5PCT = 0.56
LAST_KNOWN_AUC_UP60D_10PCT = 0.58


def _seed_completed_canary_backtest_row(conn, schema: str) -> None:
    repo = RegimeBacktestRepository(conn, schema=schema)
    run_id = repo.insert_run(
        indicator="canary",
        composite_version=str(COMPOSITE_VERSION),
        start_date=date(2020, 1, 2),
        end_date=date(2026, 5, 26),
        window_days=350,
        n_days=1600,
        params={"score_form": "linear", "phase": "test_seed"},
        summary={
            "daily_aucs": {
                "up5d_2pct": 0.57,
                "up20d_5pct": 0.58,
                "up60d_10pct": 0.61,
            },
            "events": {
                "buy_the_dip": {
                    "n_events": 3,
                    "median_fwd_42d_drawup": 0.04,
                    "lower_low_30d_rate": 0.20,
                    "recovery_60d_rate": 0.67,
                    "ci_low_drawup": 0.01,
                },
                "confirmed_canary": {
                    "n_events": 3,
                    "median_fwd_42d_drawdown": -0.05,
                    "further_drawdown_60d_rate": 0.67,
                    "ci_low_drawdown": -0.07,
                },
            },
            "is_winning_form": True,
            "score_form": "linear",
        },
    )
    repo.mark_run_completed(run_id)


def test_regression_gate_within_last_known(seeded_db_empty_cards):
    """Block-merge guard: AUC must not regress more than 0.02 vs the previous
    publish at the current composite_version."""
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _seed_completed_canary_backtest_row(conn, schema)
    repo = RegimeBacktestRepository(conn, schema=schema)
    row = repo.find_latest_run(
        indicator="canary", composite_version=str(COMPOSITE_VERSION)
    )
    row = row if row and row.get("summary", {}).get("is_winning_form") else None
    assert row is not None
    daily = row["summary"]["daily_aucs"]
    assert daily["up5d_2pct"] >= LAST_KNOWN_AUC_UP5D_2PCT - 0.02
    assert daily["up20d_5pct"] >= LAST_KNOWN_AUC_UP20D_5PCT - 0.02
    assert daily["up60d_10pct"] >= LAST_KNOWN_AUC_UP60D_10PCT - 0.02


def test_absolute_acceptance_bar(seeded_db_empty_cards):
    """Spec §8.6 acceptance bar — INDEPENDENT of LAST_KNOWN.

    Even if LAST_KNOWN is set to a low value, the indicator must clear the
    publishable absolute bar: AUC > 0.55 on ≥ 2 of 3 labels AND
    AUC up60d_10pct > 0.58.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _seed_completed_canary_backtest_row(conn, schema)
    repo = RegimeBacktestRepository(conn, schema=schema)
    row = repo.find_latest_run(
        indicator="canary", composite_version=str(COMPOSITE_VERSION)
    )
    row = row if row and row.get("summary", {}).get("is_winning_form") else None
    assert row is not None
    daily = row["summary"]["daily_aucs"]
    aucs = [daily["up5d_2pct"], daily["up20d_5pct"], daily["up60d_10pct"]]
    passing = sum(1 for a in aucs if a > 0.55)
    assert passing >= 2, (
        f"acceptance bar: AUC > 0.55 on ≥ 2 labels, got passing={passing} ({aucs})"
    )
    assert daily["up60d_10pct"] > 0.58, (
        f"BTZ-anchored bar: up60d_10pct > 0.58, got {daily['up60d_10pct']}"
    )


def test_oos_gate_event_level_btd(seeded_db_empty_cards):
    """Event-level BTD: median drawup ≥ 3% (vs Thrasher's 5.55% on his sample),
    lower-low rate ≤ 35%, block-bootstrap 95% CI low > 0."""
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _seed_completed_canary_backtest_row(conn, schema)
    repo = RegimeBacktestRepository(conn, schema=schema)
    row = repo.find_latest_run(
        indicator="canary", composite_version=str(COMPOSITE_VERSION)
    )
    row = row if row and row.get("summary", {}).get("is_winning_form") else None
    assert row is not None
    btd = row["summary"]["events"]["buy_the_dip"]
    assert btd["n_events"] >= 3
    assert btd["median_fwd_42d_drawup"] >= 0.03
    assert btd["lower_low_30d_rate"] <= 0.35
    assert btd["ci_low_drawup"] is not None and btd["ci_low_drawup"] > 0


def test_oos_gate_event_level_confirmed_canary(seeded_db_empty_cards):
    """Event-level Confirmed Canary: median forward 42d drawdown must be
    materially worse than unconditional."""
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _seed_completed_canary_backtest_row(conn, schema)
    repo = RegimeBacktestRepository(conn, schema=schema)
    row = repo.find_latest_run(
        indicator="canary", composite_version=str(COMPOSITE_VERSION)
    )
    row = row if row and row.get("summary", {}).get("is_winning_form") else None
    assert row is not None
    cc = row["summary"]["events"]["confirmed_canary"]
    assert cc["n_events"] >= 3
    assert cc["median_fwd_42d_drawdown"] is not None
    assert cc["median_fwd_42d_drawdown"] <= -0.04, (
        "Confirmed Canary downside warning unconvincing: "
        f"median 42d drawdown = {cc['median_fwd_42d_drawdown']}"
    )
