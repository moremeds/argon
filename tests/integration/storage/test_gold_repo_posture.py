"""Repository methods for gold_posture_daily — replay-discipline read."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import pytest

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards
def _kwargs_for_posture(**overrides):
    base = dict(
        obs_date=date(2026, 5, 16),
        computed_at=datetime(2026, 5, 17, tzinfo=UTC),
        gauge_corr_60d=Decimal("-0.04"),
        gauge_corr_126d=Decimal("-0.05"),
        gauge_corr_252d=Decimal("-0.07"),
        gauge_corr_504d=Decimal("-0.31"),
        gauge_corr_252d_returns=Decimal("-0.06"),
        gauge_state="suspended",
        structural_state_label="structural-bid-intact",
        cb_strategic_12m_sum_t=Decimal("210.5"),
        cb_tactical_12m_sum_t=Decimal("12.0"),
        cb_diversifier_12m_sum_t=Decimal("34.0"),
        gld_holdings_t=Decimal("872.5"),
        gld_30d_net_flow_t=Decimal("-12.4"),
        comex_registered_oz=Decimal("17500100"),
        comex_20d_roc_pct=Decimal("0.14"),
        cot_mm_net_pct=Decimal("0.72"),
        cyclical_zone_label="moderate-trap",
        cpi_yoy=Decimal("2.8"),
        t5yifr=Decimal("2.31"),
        dfii10=Decimal("1.97"),
        dfii10_60d_change_bps=Decimal("12"),
        factors_jsonb={"F1": -0.4, "F5": 1.8, "F13": 0.6},
        valuation_flag="Severe",
        real_price_percentile=Decimal("0.92"),
        gold_m2_ratio_percentile=Decimal("0.78"),
        gold_spx_ratio_percentile=Decimal("0.64"),
        structural_posture_text="Structural bid intact.",
        cyclical_posture_text="Cyclical posture suspended.",
        valuation_posture_text="Mean-reversion risk: SEVERE.",
        inputs_jsonb={
            "DFII10": {
                "obs_date": "2026-05-16",
                "as_of": "2026-05-17T00:00:00Z",
            }
        },
    )
    base.update(overrides)
    return base


def test_insert_and_fetch_gold_posture_latest(repo: Repository) -> None:
    repo.insert_gold_posture_daily(**_kwargs_for_posture())
    latest = repo.fetch_gold_posture_latest()
    assert latest is not None
    assert latest["obs_date"] == date(2026, 5, 16)
    assert latest["gauge_state"] == "suspended"
    assert latest["factors_jsonb"]["F5"] == 1.8


def test_latest_skips_invalidated_rows(repo: Repository) -> None:
    repo.insert_gold_posture_daily(
        **_kwargs_for_posture(
            obs_date=date(2026, 5, 10),
            computed_at=datetime(2026, 5, 11, 21, tzinfo=UTC),
            gauge_state="suspended",
        )
    )
    repo.insert_gold_posture_daily(
        **_kwargs_for_posture(
            obs_date=date(2026, 5, 11),
            computed_at=datetime(2026, 5, 12, 21, tzinfo=UTC),
            gauge_state="partial",
        )
    )
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE uw_scan.gold_posture_daily
            SET row_status = 'invalidated',
                superseded_reason = 'test invalidation'
            WHERE obs_date = %s
            """,
            (date(2026, 5, 11),),
        )

    latest = repo.fetch_gold_posture_latest()

    assert latest is not None
    assert latest["obs_date"] == date(2026, 5, 10)
    assert latest["row_status"] == "active"


def test_replay_returns_first_computed(repo: Repository) -> None:
    """Multiple computed_at rows for same obs_date → replay picks the FIRST one."""
    repo.insert_gold_posture_daily(
        **_kwargs_for_posture(
            obs_date=date(2026, 5, 10),
            computed_at=datetime(2026, 5, 11, 21, tzinfo=UTC),
            gauge_state="suspended",
        )
    )
    repo.insert_gold_posture_daily(
        **_kwargs_for_posture(
            obs_date=date(2026, 5, 10),
            computed_at=datetime(2026, 5, 20, 21, tzinfo=UTC),
            gauge_state="partial",
        )
    )
    row = repo.fetch_gold_posture_for_obs_date(date(2026, 5, 10))
    assert row is not None
    assert row["gauge_state"] == "suspended"  # FIRST-computed


def test_replay_skips_invalidated_rows(repo: Repository) -> None:
    repo.insert_gold_posture_daily(
        **_kwargs_for_posture(
            obs_date=date(2026, 5, 10),
            computed_at=datetime(2026, 5, 11, 21, tzinfo=UTC),
            gauge_state="suspended",
        )
    )
    repo.insert_gold_posture_daily(
        **_kwargs_for_posture(
            obs_date=date(2026, 5, 10),
            computed_at=datetime(2026, 5, 20, 21, tzinfo=UTC),
            gauge_state="partial",
        )
    )
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE uw_scan.gold_posture_daily
            SET row_status = 'invalidated',
                superseded_reason = 'test invalidation'
            WHERE obs_date = %s AND computed_at = %s
            """,
            (date(2026, 5, 10), datetime(2026, 5, 11, 21, tzinfo=UTC)),
        )

    row = repo.fetch_gold_posture_for_obs_date(date(2026, 5, 10))

    assert row is not None
    assert row["gauge_state"] == "partial"
    assert row["row_status"] == "active"
