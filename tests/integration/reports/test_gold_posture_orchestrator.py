"""Integration test for the gold_posture orchestrator."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import pytest

from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
def _seed_minimum(repo: Repository, today: date) -> None:
    """Seed enough data for the orchestrator to produce a non-empty posture."""
    base = today - timedelta(days=300)
    for i in range(301):
        d = base + timedelta(days=i)
        repo.insert_macro_series_daily(
            "GLD_CLOSE",
            d,
            Decimal(str(1800 + i * 0.5)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "MASSIVE",
            None,
        )
        repo.insert_macro_series_daily(
            "DFII10",
            d,
            Decimal(str(2.0 - i * 0.005)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "FRED",
            None,
        )
    repo.insert_macro_series_monthly(
        "CPIAUCSL",
        date(today.year, today.month, 1),
        Decimal("315.0"),
        datetime.now(UTC),
        date(today.year, today.month, 14),
        "FRED",
        None,
    )
    repo.insert_macro_series_daily(
        "T5YIFR",
        today,
        Decimal("2.31"),
        datetime.now(UTC),
        None,
        "FRED",
        None,
    )
    repo.insert_etf_holdings_daily(
        ticker="GLD",
        obs_date=today,
        holdings_oz=Decimal("32150746.6"),
        shares_out=None,
        nav_per_share=Decimal("420.50"),
        premium_pct=Decimal("0.01"),
        as_of=datetime.now(UTC),
        source="SPDR",
    )


def test_orchestrator_writes_posture_row(repo: Repository) -> None:
    today = date(2026, 5, 16)
    _seed_minimum(repo, today)
    compute_and_persist_gold_posture(
        repo,
        as_of=today,
        computed_at=datetime(2026, 5, 17, tzinfo=UTC),
    )
    row = repo.fetch_gold_posture_for_obs_date(today)
    assert row is not None
    assert row["obs_date"] == today
    assert row["gauge_state"] in {"operative", "partial", "suspended"}
    assert row["inputs_jsonb"] is not None
    assert "DFII10" in row["inputs_jsonb"]
    # GOLD COMPASS extensions populated
    assert row["valuation_posture_chip"] in {
        "FAVORABLE",
        "NEUTRAL",
        "STRETCHED",
        "SUSPENDED",
        "DEGRADED",
    }
    assert row["gld_history_jsonb"][-1]["obs_date"] == today.isoformat()
    assert Decimal(row["gld_history_jsonb"][-1]["value"]) == Decimal("1000")
    freshness_by_id = {item["id"]: item for item in row["data_freshness_jsonb"]}
    assert freshness_by_id["COMEX"]["status"] == "missing"
    assert freshness_by_id["COT"]["status"] == "missing"
    assert freshness_by_id["WGC"]["status"] == "missing"


def test_orchestrator_idempotent_same_inputs(repo: Repository) -> None:
    """Running twice with same (obs_date, computed_at) is a no-op."""
    today = date(2026, 5, 16)
    _seed_minimum(repo, today)
    computed_at = datetime(2026, 5, 17, tzinfo=UTC)
    compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
    compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.gold_posture_daily WHERE obs_date = %s",
            (today,),
        )
        assert cur.fetchone()[0] == 1
