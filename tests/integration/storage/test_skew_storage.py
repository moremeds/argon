"""Integration tests for _SkewMixin (pytest-postgresql)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan import models


@pytest.fixture
def repo(seeded_db_empty_cards):
    """Alias: the canonical bare-Repository fixture (see tests/integration/conftest.py)."""
    return seeded_db_empty_cards


def _snap(ticker: str, d: date, **over) -> dict:
    base = {
        "ticker": ticker,
        "market_date": d,
        "basis": "eod",
        "spot": Decimal("100"),
        "rr_25d": Decimal("0.01"),
        "skew_25d": Decimal("0.01"),
        "rr_z_180d": Decimal("1.7"),
        "rr_pct_252d": Decimal("90"),
        "deviation_class": "RICH",
        "skew_term_class": "flat",
        "front_rr": Decimal("0.01"),
        "back_rr": None,
        "rho_spotvol_63d": Decimal("-0.4"),
        "rho_spotvol_21d": Decimal("-0.5"),
        "rho_sign": -1,
        "drive_class": "PANIC",
        "asset_class": "single_name",
        "class_expected_sign": "mixed",
        "borrow_flag": "normal",
        "borrow_fee_rate": Decimal("0.25"),
        "days_to_cover": Decimal("1.5"),
        "earnings_gate": "pass",
        "regime": "HIGH_VOL",
        "directional_lean": "NEUTRAL",
        "lean_confidence": "low",
        "lean_basis": "no verdict",
        "read_summary": "test",
        "read_json": {"k": "v"},
    }
    base.update(over)
    return base


def test_upsert_snapshot_is_idempotent(repo):
    d = date(2026, 6, 1)
    assert repo.upsert_skew_analytics_snapshots([_snap("AAPL", d)]) == 1
    repo.upsert_skew_analytics_snapshots([_snap("AAPL", d, rr_25d=Decimal("0.02"))])
    repo.conn.commit()
    latest = repo.get_skew_analytics_latest("AAPL")
    assert latest is not None
    assert latest["rr_25d"] == Decimal("0.02")  # updated, not duplicated


def test_history_returns_ascending(repo):
    repo.upsert_skew_analytics_snapshots(
        [_snap("MSFT", date(2026, 5, 1)), _snap("MSFT", date(2026, 5, 2))]
    )
    repo.conn.commit()
    rows = repo.fetch_skew_analytics_history("MSFT", days=400)
    assert [r["market_date"] for r in rows] == [date(2026, 5, 1), date(2026, 5, 2)]


def test_verdict_roundtrip(repo):
    repo.upsert_skew_directional_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        drive_class="PANIC",
        regime="HIGH_VOL",
        verdict="TRADABLE_BEAR",
        confidence="med",
        forward_sep=Decimal("-0.021"),
        n=42,
        borrow_clean=True,
        survives_gate=True,
        as_of=date(2026, 6, 1),
    )
    repo.conn.commit()
    v = repo.get_skew_directional_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        drive_class="PANIC",
        regime="HIGH_VOL",
    )
    assert v is not None and v["verdict"] == "TRADABLE_BEAR" and v["n"] == 42
    assert (
        repo.get_skew_directional_verdict(
            asset_class="index_macro",
            deviation_class="RICH",
            drive_class="PANIC",
            regime="HIGH_VOL",
        )
        is None
    )


def test_latest_next_earnings_date(repo):
    # flow_events requires run_id (FK -> scan_runs) + alert_id (NOT NULL),
    # UNIQUE(run_id, alert_id). Latest non-null next_earnings_date wins.
    run_id = repo.insert_scan_run(ticker="NFLX")
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date, inserted_at) "
            "VALUES (%s, 'a1', 'NFLX', %s, now() - interval '2 days'), "
            "       (%s, 'a2', 'NFLX', %s, now())",
            (run_id, date(2026, 7, 1), run_id, date(2026, 7, 15)),
        )
    repo.conn.commit()
    assert repo.fetch_latest_next_earnings_date("NFLX") == date(2026, 7, 15)
    assert repo.fetch_latest_next_earnings_date("ZZZZ") is None


def test_fetch_watchlist_sector(repo):
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist (ticker, sector) VALUES ('ZZTOP', 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
    repo.conn.commit()
    assert repo.fetch_watchlist_sector("ZZTOP") == "Macro"
    assert repo.fetch_watchlist_sector("NOPE") is None


def test_rv_reversion_verdict_roundtrip(repo):
    repo.upsert_skew_rv_reversion_verdict(
        asset_class="single_name",
        deviation_class="CHEAP",
        tail="put_skew",
        verdict="REVERTS",
        mean_drr=0.0514,
        mean_drr_holdout=0.041,
        n=1472,
        n_holdout=520,
        survives_walkforward=True,
        survives_window_gate=True,
        as_of=date(2026, 6, 16),
    )
    repo.conn.commit()
    got = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert got is not None
    assert got["verdict"] == "REVERTS"
    assert got["survives_walkforward"] is True
    assert got["survives_window_gate"] is True
    # upsert is idempotent on the PK
    repo.upsert_skew_rv_reversion_verdict(
        asset_class="single_name",
        deviation_class="CHEAP",
        tail="put_skew",
        verdict="NONE",
        mean_drr=0.0,
        mean_drr_holdout=0.0,
        n=1,
        n_holdout=0,
        survives_walkforward=False,
        survives_window_gate=False,
        as_of=date(2026, 6, 16),
    )
    repo.conn.commit()
    got2 = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert got2["verdict"] == "NONE"


def test_fetch_latest_exposures_by_strike(repo):
    run_id = repo.insert_scan_run(ticker="QCOM")
    rows = [
        models.GreekExposureRow(
            date=date(2026, 6, 15),
            expiry=date(2026, 7, 18),
            strike=Decimal("95"),
            dte=33,
            call_delta=Decimal("0.62"),
            put_delta=Decimal("-0.38"),
        ),
        models.GreekExposureRow(
            date=date(2026, 6, 15),
            expiry=date(2026, 7, 18),
            strike=Decimal("90"),
            dte=33,
            call_delta=Decimal("0.74"),
            put_delta=Decimal("-0.26"),
        ),
    ]
    repo.insert_greek_exposure_rows(run_id, "QCOM", rows)
    repo.conn.commit()
    got = repo.fetch_latest_exposures_by_strike("QCOM", dte_max=70)
    assert len(got) == 2
    assert {r["strike"] for r in got} == {Decimal("95"), Decimal("90")}
    assert all("put_delta" in r and "dte" in r for r in got)


def test_fetch_latest_exposures_reads_only_the_newest_run(repo):
    ex = date(2026, 7, 18)
    # two runs on the SAME market_date — the later run (higher run_id) wins.
    old = repo.insert_scan_run(ticker="ABCD")
    repo.insert_greek_exposure_rows(
        old,
        "ABCD",
        [
            models.GreekExposureRow(
                date=date(2026, 6, 15),
                expiry=ex,
                strike=Decimal("70"),
                dte=33,
                put_delta=Decimal("-0.20"),
            )
        ],
    )
    new = repo.insert_scan_run(ticker="ABCD")
    repo.insert_greek_exposure_rows(
        new,
        "ABCD",
        [
            models.GreekExposureRow(
                date=date(2026, 6, 15),
                expiry=ex,
                strike=Decimal("95"),
                dte=33,
                put_delta=Decimal("-0.26"),
            )
        ],
    )
    repo.conn.commit()
    got = repo.fetch_latest_exposures_by_strike("ABCD", dte_max=70)
    assert {r["strike"] for r in got} == {Decimal("95")}  # only the newest run's chain


def test_snapshot_persists_structure_detail_with_decimal_and_date(repo):
    row = {
        "ticker": "QCOM",
        "market_date": date(2026, 6, 16),
        "basis": "eod",
        "deviation_class": "CHEAP",
        "directional_lean": "BEARISH_TILT",
        "read_summary": "x",
        "read_json": {
            "directional_lean": {
                "lean": "BEARISH_TILT",
                "structure_detail": {
                    "kind": "put_debit_spread",
                    "dte_target": 33,
                    "status": "ready",
                    "note": "defined risk",
                    "legs": [
                        {
                            "action": "BUY",
                            "right": "PUT",
                            "strike": Decimal("95"),
                            "target_delta": Decimal("-0.25"),
                            "actual_delta": Decimal("-0.26"),
                            "expiry": date(2026, 7, 18),
                            "dte": 33,
                        }
                    ],
                },
            },
        },
    }
    repo.upsert_skew_analytics_snapshots([row])  # must NOT raise on Decimal/date
    repo.conn.commit()
    got = repo.get_skew_analytics_latest("QCOM")
    sd = got["read_json"]["directional_lean"]["structure_detail"]
    assert sd["legs"][0]["strike"] == "95"  # stringified by default=str
    assert sd["legs"][0]["expiry"] == "2026-07-18"
