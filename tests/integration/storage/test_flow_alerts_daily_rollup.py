"""Flow-alert daily rollup persistence."""

from __future__ import annotations

import os
import subprocess
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from uw_scan.config import Settings
from uw_scan.models import FlowAlert

REPO_ROOT = Path(__file__).resolve().parents[3]


def _alert(
    alert_id: str,
    ticker: str = "GOOGL",
    *,
    option_type: str = "call",
    premium: Decimal = Decimal("1000"),
    rule: str = "RepeatedHits",
    created_at: datetime = datetime(2026, 5, 14, 14, 30, tzinfo=timezone.utc),
) -> FlowAlert:
    return FlowAlert(
        id=alert_id,
        ticker=ticker,
        type=option_type,
        total_premium=premium,
        total_ask_side_prem=premium * Decimal("0.7"),
        total_bid_side_prem=premium * Decimal("0.3"),
        alert_rule=rule,
        created_at=created_at,
    )


def test_flow_alerts_daily_rollup_computes_30d_baseline(seeded_db_empty_cards):
    repo = seeded_db_empty_cards

    for idx, count in enumerate([20, 30, 40], start=1):
        run_id = repo.insert_scan_run("GOOGL")
        repo.upsert_flow_alerts_daily_rollup(
            run_id=run_id,
            ticker="GOOGL",
            alerts=[_alert(f"hist-{idx}-{n}") for n in range(count)],
            alert_limit=100,
            trade_date=date(2026, 5, 10 + idx),
        )

    current_run_id = repo.insert_scan_run("GOOGL")
    repo.upsert_flow_alerts_daily_rollup(
        run_id=current_run_id,
        ticker="GOOGL",
        alerts=[_alert(f"current-{n}") for n in range(100)],
        alert_limit=100,
        trade_date=date(2026, 5, 15),
    )
    repo.conn.commit()

    baseline = repo.fetch_flow_alerts_daily_baseline(current_run_id, "GOOGL")

    assert baseline["alert_count"] == 100
    assert baseline["alert_count_is_limited"] is True
    assert baseline["top_alert_rule"] == "RepeatedHits"
    assert baseline["avg_30d_alert_count"] == Decimal("30.0000000000000000")
    assert baseline["flow_count_vs_30d_avg"] == Decimal("3.3333333333333333")
    assert baseline["baseline_days"] == 3


def test_backfill_migration_rolls_up_existing_flow_events(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    old_run = repo.insert_scan_run("GOOGL")
    repo.insert_flow_events(
        old_run,
        "GOOGL",
        [_alert("old-1", premium=Decimal("10"))],
    )
    latest_run = repo.insert_scan_run("GOOGL")
    repo.insert_flow_events(
        latest_run,
        "GOOGL",
        [
            _alert("new-1", option_type="call", premium=Decimal("100")),
            _alert("new-2", option_type="put", premium=Decimal("50")),
        ],
    )
    prior_run = repo.insert_scan_run("GOOGL")
    repo.insert_flow_events(
        prior_run,
        "GOOGL",
        [
            _alert(
                "prior-1",
                premium=Decimal("20"),
                created_at=datetime(2026, 5, 13, 14, 30, tzinfo=timezone.utc),
            ),
            _alert(
                "prior-2",
                premium=Decimal("20"),
                created_at=datetime(2026, 5, 13, 15, 30, tzinfo=timezone.utc),
            ),
        ],
    )
    repo.conn.commit()

    settings = Settings.from_env().model_copy(
        update={"db_name": os.environ["UW_SCAN_TEST_DB_NAME"]}
    )
    subprocess.run(
        [
            "psql",
            settings.db_dsn(),
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(
                REPO_ROOT
                / "src/uw_scan/storage/migrations/023_backfill_flow_alerts_daily_rollup.sql"
            ),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, alert_count, total_premium, bull_premium, bear_premium
            FROM uw_scan.flow_alerts_daily_rollup
            WHERE ticker = 'GOOGL' AND trade_date = '2026-05-14'
            """
        )
        current = cur.fetchone()
        cur.execute(
            """
            SELECT alert_count, avg_30d_alert_count, flow_count_vs_30d_avg
            FROM (
                WITH current_rollup AS (
                    SELECT ticker, trade_date, alert_count
                    FROM uw_scan.flow_alerts_daily_rollup
                    WHERE run_id = %s
                ), history AS (
                    SELECT h.alert_count
                    FROM uw_scan.flow_alerts_daily_rollup h
                    JOIN current_rollup c ON c.ticker = h.ticker
                    WHERE h.trade_date < c.trade_date
                      AND h.trade_date >= c.trade_date - (30 * INTERVAL '1 day')
                )
                SELECT
                    c.alert_count,
                    AVG(h.alert_count)::numeric AS avg_30d_alert_count,
                    ROUND(c.alert_count::numeric / AVG(h.alert_count)::numeric, 16)
                        AS flow_count_vs_30d_avg
                FROM current_rollup c
                LEFT JOIN history h ON true
                GROUP BY c.alert_count
            ) s
            """,
            (latest_run,),
        )
        baseline = cur.fetchone()

    assert current == (
        latest_run,
        2,
        Decimal("150.0000"),
        Decimal("100.0000"),
        Decimal("50.0000"),
    )
    assert baseline == (
        2,
        Decimal("2.0000000000000000"),
        Decimal("1.0000000000000000"),
    )
