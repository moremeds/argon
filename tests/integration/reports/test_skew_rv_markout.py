"""RV mean-reversion verdict: tail-split keys + walk-forward + catastrophic gate."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.reports.skew_markout import (
    _expected_drr_sign,
    _rv_walkforward,
    run_skew_markout,
)


@pytest.fixture
def repo(seeded_db_empty_cards):
    return seeded_db_empty_cards


def _seed_cheap_reverting_bucket(repo, ticker="QCOM"):
    """A single_name CHEAP/put_skew bucket whose 25d RR climbs (re-richens) across the
    whole window: forward ΔRR(T+20) is positive everywhere, so the time-ordered holdout
    survives. Seeds BOTH the snapshot anchors AND risk_reversal_skew_history (the forward
    RR series skew_markout._rr_series reads, delta=25). RR stays > 0 so every anchor
    buckets as tail=put_skew."""
    base = date(2025, 1, 2)
    snaps = []
    for i in range(80):
        d = base + timedelta(days=i)
        rr = 0.02 + 0.002 * i  # +0.02 .. +0.178, all put_skew, monotonically richening
        snaps.append(
            {
                "ticker": ticker,
                "market_date": d,
                "basis": "eod",
                "spot": 100.0 + i,
                "rr_25d": rr,
                "skew_25d": rr,
                "deviation_class": "CHEAP",
                "skew_term_class": "flat",
                "drive_class": "STRUCTURAL",
                "asset_class": "single_name",
                "regime": "LOW_VOL",
                "borrow_flag": "normal",
            }
        )
    repo.upsert_skew_analytics_snapshots(snaps)
    with repo.conn.cursor() as cur:
        for i in range(80):
            d = base + timedelta(days=i)
            rr = 0.02 + 0.002 * i
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry, risk_reversal) "
                "VALUES (%s, %s, 25, %s, %s) ON CONFLICT DO NOTHING",
                (ticker, d, base + timedelta(days=40), rr),
            )
    repo.conn.commit()


def test_rv_markout_writes_reverting_verdict(repo):
    _seed_cheap_reverting_bucket(repo)
    out = run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)
    assert "rv_reversion" in out and out["rv_verdicts_written"] >= 1
    v = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert v is not None
    assert v["verdict"] == "REVERTS"
    assert float(v["mean_drr"]) > 0  # CHEAP re-richens => positive ΔRR
    assert v["survives_walkforward"] is True
    assert (
        v["survives_window_gate"] is True
    )  # single-quarter seed: no sub-window blowup


def test_rv_markout_idempotent(repo):
    _seed_cheap_reverting_bucket(repo)
    run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)
    run_skew_markout(
        repo=repo, min_n=1, sep_threshold=0.005
    )  # second run = no-op upsert
    v = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert v["verdict"] == "REVERTS"


def test_walkforward_rejects_when_holdout_flips():
    # full-sample positive but the recent holdout goes negative => NONE
    obs = [
        {"drr": 0.02, "market_date": date(2025, 1, 1) + timedelta(days=i)}
        for i in range(40)
    ]
    obs += [
        {"drr": -0.03, "market_date": date(2025, 3, 1) + timedelta(days=i)}
        for i in range(40)
    ]
    out = _rv_walkforward(obs, _expected_drr_sign("CHEAP"))
    assert out["verdict"] == "NONE"
    assert out["survives_walkforward"] is False


def test_walkforward_skips_normal_and_small_n():
    assert _rv_walkforward([], _expected_drr_sign("NORMAL"))["verdict"] == "NONE"
    tiny = [{"drr": 0.05, "market_date": date(2025, 1, 1)}]
    assert _rv_walkforward(tiny, _expected_drr_sign("CHEAP"))["verdict"] == "NONE"


def test_walkforward_rejects_when_a_quarter_blows_up():
    # full-sample AND holdout positive, but Q2 reverses harder than the aggregate ->
    # catastrophic-degradation gate fails -> NONE (mirrors the directional AC-F4 gate).
    obs = [
        {"drr": 0.05, "market_date": date(2025, 1, 1) + timedelta(days=i)}
        for i in range(40)
    ]  # Q1 +0.05
    obs += [
        {"drr": -0.20, "market_date": date(2025, 4, 1) + timedelta(days=i)}
        for i in range(10)
    ]  # Q2 big negative
    obs += [
        {"drr": 0.05, "market_date": date(2025, 7, 1) + timedelta(days=i)}
        for i in range(40)
    ]  # Q3 +0.05 (holdout)
    out = _rv_walkforward(obs, _expected_drr_sign("CHEAP"))
    assert out["survives_walkforward"] is True  # holdout (Q3) is clean
    assert out["survives_window_gate"] is False  # Q2 blowup caught
    assert out["verdict"] == "NONE"
