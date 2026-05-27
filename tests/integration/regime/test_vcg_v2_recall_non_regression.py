from __future__ import annotations

from pathlib import Path

import pandas as pd

from tests.integration.regime.test_vcg_v2_contradiction import (
    _latest_v2_run_id,
    _load_fixture,
    _run_backtest_vcg,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
V1_CRISIS_RECALL_BASELINE = 52 / 528
EXPECTED_TRUTH_STRESS_DENOMINATOR = 528
STRESS_INTERPRETATIONS = ("WATCH", "EDR", "RISK_OFF", "PANIC", "BOUNCE")
TRUTH_STRESS_STATUSES = ("EDR", "RISK_OFF", "PANIC")


def test_v2_does_not_reduce_crisis_recall(seeded_db_empty_cards) -> None:
    conn = seeded_db_empty_cards.conn
    _load_fixture(conn)
    _run_backtest_vcg(conn)
    run_id = _latest_v2_run_id(conn)

    truth_df = pd.read_parquet(FIXTURE_DIR / "seven_crisis_truth_labels.parquet")
    truth_stress = truth_df[truth_df["truth_status"].isin(TRUTH_STRESS_STATUSES)].copy()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, payload->>'interpretation' AS interpretation "
            "FROM uw_scan.regime_backtest_daily WHERE run_id = %s",
            (run_id,),
        )
        daily = pd.DataFrame(cur.fetchall(), columns=["trade_date", "interpretation"])

    truth_stress["trade_date"] = pd.to_datetime(truth_stress["trade_date"]).dt.date
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.date
    joined = truth_stress.merge(daily, on="trade_date", how="left", validate="one_to_one")
    missing = int(joined["interpretation"].isna().sum())
    assert missing == 0, f"{missing} truth-stress fixture dates missing VCG rows"

    truth_stress_days = len(joined)
    assert truth_stress_days == EXPECTED_TRUTH_STRESS_DENOMINATOR

    v2_hits = int(joined["interpretation"].isin(STRESS_INTERPRETATIONS).sum())
    v2_recall = v2_hits / truth_stress_days

    assert v2_recall >= V1_CRISIS_RECALL_BASELINE, (
        f"v2 crisis-window stress recall = {v2_recall:.4f} "
        f"({v2_hits}/{truth_stress_days}), below v1 baseline "
        f"{V1_CRISIS_RECALL_BASELINE:.4f} (52/528)"
    )
