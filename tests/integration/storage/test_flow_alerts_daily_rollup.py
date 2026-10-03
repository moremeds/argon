"""Flow-alert daily rollup persistence."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import FlowAlert


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
