"""Integration test: skew markout buckets snapshots, scores forwards, writes verdicts.

End-to-end safety property: a seeded TRADABLE_* verdict surfaces as a non-neutral
lean on the next rollup; no verdict => NEUTRAL.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.reports.skew_markout import run_skew_markout


@pytest.fixture
def repo(seeded_db_empty_cards):
    return seeded_db_empty_cards


def _snap(ticker, d, deviation, drive):
    return {
        "ticker": ticker,
        "market_date": d,
        "basis": "eod",
        "spot": Decimal("100"),
        "rr_25d": Decimal("0.05"),
        "skew_25d": Decimal("0.05"),
        "rr_z_180d": Decimal("2.0"),
        "rr_pct_252d": Decimal("95"),
        "deviation_class": deviation,
        "skew_term_class": "flat",
        "front_rr": Decimal("0.05"),
        "back_rr": None,
        "rho_spotvol_63d": Decimal("-0.5"),
        "rho_spotvol_21d": Decimal("-0.6"),
        "rho_sign": -1,
        "drive_class": drive,
        "asset_class": "single_name",
        "class_expected_sign": "mixed",
        "borrow_flag": "normal",
        "borrow_fee_rate": Decimal("0.25"),
        "days_to_cover": Decimal("1"),
        "earnings_gate": "pass",
        "regime": "HIGH_VOL",
        "directional_lean": "NEUTRAL",
        "lean_confidence": "low",
        "lean_basis": "seed",
        "read_summary": "seed",
        "read_json": {},
    }


def _seed_snapshot_and_forwards(repo, ticker="NVDA"):
    base = date(2026, 2, 1)
    repo.upsert_skew_analytics_snapshots(
        [
            _snap(ticker, base, "RICH", "PANIC"),  # the bucket under test
            _snap("PEERCO", base, "NORMAL", "STRUCTURAL"),  # flat cross-section peer
        ]
    )
    # Cross-sectional demeaning: the RICH name (ticker) falls ~4% over T+20 while
    # the NORMAL peer is flat, so on each date `ticker` underperforms the universe
    # mean -> negative excess -> the RICH/PANIC bucket earns TRADABLE_BEAR.
    # >=20 forward TRADING-day rows needed (positional horizon).
    with repo.conn.cursor() as cur:
        for off in range(1, 26):
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, base + timedelta(days=off), 100 - off * 0.2),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price) VALUES ('PEERCO',%s,100) "
                "ON CONFLICT DO NOTHING",
                (base + timedelta(days=off),),
            )
    repo.conn.commit()


def test_markout_writes_bear_verdict_on_separation(repo):
    _seed_snapshot_and_forwards(repo, "NVDA")
    counts = run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)
    v = repo.get_skew_directional_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        drive_class="PANIC",
        regime="HIGH_VOL",
    )
    assert v is not None
    assert v["verdict"] == "TRADABLE_BEAR"
    assert counts["verdicts_written"] >= 1


def test_markout_none_when_below_min_n(repo):
    _seed_snapshot_and_forwards(repo, "NVDA")
    run_skew_markout(repo=repo, min_n=50, sep_threshold=0.005)
    v = repo.get_skew_directional_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        drive_class="PANIC",
        regime="HIGH_VOL",
    )
    assert v is not None and v["verdict"] == "NONE"
