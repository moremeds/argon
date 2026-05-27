"""Test-only seed helpers for canary v2-A integration tests.

Each function takes (conn, *, schema) — operates on the per-test DB
provided by tests/integration/conftest.py's seeded_db_empty_cards fixture.
No subprocess, no env-var plumbing.

IMPORTANT: snapshot helpers use CanarySnapshotRepository.insert_snapshot(...)
so every NOT NULL column (tactical_score/structural_score/speed_score/
warning_state/payload_hash) is populated correctly. Raw SQL inserts have
caused fixture failures in earlier drafts.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

import numpy as np

from uw_scan.cards.canary_payload_hash import canonical_payload_hash
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _trading_days(start: date, n: int) -> list[date]:
    """Return n consecutive business-day-ish dates from start (skips Sat/Sun)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d = d + timedelta(days=1)
    return out


def seed_vol_index_full_history(
    conn,
    *,
    schema: str,
    start: date = date(2011, 2, 8),
    end: date = date(2026, 5, 21),
    seed: int = 42,
) -> list[date]:
    """Seed vol_index_daily with synthetic but realistic data covering [start, end].

    Returns the list of trade_dates inserted. SPX path is a sinusoidal + linear
    drift (guarantees mixed labels at all 3 forward horizons) so AUC computations
    don't degenerate. Uses the real schema column `trade_date` (NOT `data_date`).
    """
    dates = _trading_days(start, (end - start).days)
    dates = [d for d in dates if d <= end]
    n = len(dates)

    rng = np.random.default_rng(seed)
    spx = np.clip(
        1000.0 + 8.0 * np.sin(np.arange(n) / 7.0) + 0.05 * np.arange(n), 600.0, 6000.0
    )
    vix = np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 50.0)
    vvix = np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0)
    vix3m = np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0)
    cor1m = np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0)

    with conn.cursor() as cur:
        for i, d in enumerate(dates):
            for symbol, close in (
                ("SPX", spx[i]),
                ("VIX", vix[i]),
                ("VVIX", vvix[i]),
                ("VIX3M", vix3m[i]),
                ("COR1M", cor1m[i]),
            ):
                cur.execute(
                    f"INSERT INTO {schema}.vol_index_daily "
                    f"(symbol, trade_date, open, high, low, close, adj_close, volume) "
                    f"VALUES (%s, %s, %s, %s, %s, %s, %s, 0) "
                    f"ON CONFLICT (symbol, trade_date) DO NOTHING",
                    (
                        symbol,
                        d,
                        float(close),
                        float(close),
                        float(close),
                        float(close),
                        float(close),
                    ),
                )
    conn.commit()
    return dates


def seed_v1_walk_forward_runs(conn, *, schema: str) -> list[int]:
    """Seed 6 v1 walk-forward production runs (the PR #83 baseline).

    Each row has summary.aucs.composite.{up5d_2pct,up20d_5pct,up60d_10pct}.
    Returns the list of inserted run_ids.
    """
    repo = RegimeBacktestRepository(conn, schema=schema)
    ids: list[int] = []
    windows = [
        ("WF-1", date(2015, 1, 2), date(2016, 12, 30), 0.642),
        ("WF-2", date(2017, 1, 3), date(2018, 12, 31), 0.610),
        ("WF-3", date(2019, 1, 2), date(2020, 9, 30), 0.655),
        ("WF-4", date(2020, 10, 1), date(2022, 12, 30), 0.628),
        ("WF-5", date(2023, 1, 3), date(2024, 12, 31), 0.601),
        ("WF-6", date(2025, 1, 2), date(2026, 5, 21), 0.633),
    ]
    for wid, sd, ed, auc60 in windows:
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="1",
            start_date=sd,
            end_date=ed,
            window_days=350,
            n_days=(ed - sd).days,
            params={
                "phase": "walk_forward",
                "score_form": "linear",
                "window_id": wid,
                "train_end": "2014-12-31",
            },
            summary={
                "aucs": {
                    "composite": {
                        "up5d_2pct": 0.58,
                        "up20d_5pct": 0.56,
                        "up60d_10pct": auc60,
                    },
                    "vol_only": {
                        "up5d_2pct": 0.57,
                        "up20d_5pct": 0.51,
                        "up60d_10pct": auc60 + 0.01,
                    },
                    "speed_only": {
                        "up5d_2pct": 0.55,
                        "up20d_5pct": 0.62,
                        "up60d_10pct": 0.49,
                    },
                },
                "n_days": (ed - sd).days,
                "window_id": wid,
            },
            run_scope="production",
        )
        repo.mark_run_completed(run_id)
        ids.append(run_id)
    return ids


def seed_v2_walk_forward_runs(
    conn, *, schema: str, batch_id: str | None = None, per_window_60d_auc: float = 0.65
) -> tuple[str, list[int]]:
    """Seed 6 v2 walk-forward research runs + 1 v2 robustness research run,
    all sharing a batch_id. Returns (batch_id, run_ids)."""
    if batch_id is None:
        batch_id = str(uuid.uuid4())
    repo = RegimeBacktestRepository(conn, schema=schema)
    ids: list[int] = []
    for i, wid in enumerate(("WF-1", "WF-2", "WF-3", "WF-4", "WF-5", "WF-6")):
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="2",
            start_date=date(2015 + 2 * i, 1, 2),
            end_date=date(2015 + 2 * i + 1, 12, 30),
            window_days=350,
            n_days=500,
            params={
                "phase": "walk_forward",
                "score_form": "linear",
                "window_id": wid,
                "batch_id": batch_id,
            },
            summary={
                "aucs": {
                    "composite": {
                        "up5d_2pct": 0.62,
                        "up20d_5pct": 0.64,
                        "up60d_10pct": per_window_60d_auc,
                    },
                    "vol_only": {
                        "up5d_2pct": 0.62,
                        "up20d_5pct": 0.64,
                        "up60d_10pct": per_window_60d_auc,
                    },
                    "speed_only": {
                        "up5d_2pct": 0.50,
                        "up20d_5pct": 0.50,
                        "up60d_10pct": 0.50,
                    },
                },
                "n_days": 500,
                "window_id": wid,
            },
            run_scope="research",
        )
        repo.mark_run_completed(run_id)
        ids.append(run_id)
    rob_id = repo.insert_run(
        indicator="canary",
        composite_version="2",
        start_date=date(2011, 2, 8),
        end_date=date(2026, 5, 21),
        window_days=350,
        n_days=3843,
        params={"phase": "robustness", "score_form": "linear", "batch_id": batch_id},
        summary={"aucs": {"composite": {"up60d_10pct": 0.642}}},
        run_scope="research",
    )
    repo.mark_run_completed(rob_id)
    return batch_id, ids + [rob_id]


def seed_canary_snapshots_v2(
    conn,
    *,
    schema: str,
    dates: Sequence[date],
    cca_dates: Sequence[date] = (),
) -> int:
    """Seed v2 canary_snapshots for the given dates via insert_snapshot().

    Rows whose data_date is in `cca_dates` get
    payload.speed.confirmed_canary_active=True (used to satisfy AC-F3 in
    integration tests). Returns row count inserted.
    """
    cca_set = set(cca_dates)
    rng = np.random.default_rng(123)
    repo = CanarySnapshotRepository(conn, schema=schema)
    inserted = 0
    for d in dates:
        cca = d in cca_set
        raw = float(rng.uniform(0, 70))
        speed_score = 0 if cca else 8
        tactical_raw = round(raw * 0.4, 2)
        structural_raw = round(raw * 0.6, 2)
        score_v = max(0.0, min(100.0, tactical_raw + structural_raw))
        band = (
            "STRONG_BUY"
            if score_v >= 75
            else "BUY"
            if score_v >= 50
            else "WATCH"
            if score_v >= 25
            else "NONE"
        )
        warning_state = "CONFIRMED_CANARY_ACTIVE" if cca else "NONE"
        payload = {
            "tactical_vol": {"score": tactical_raw},
            "structural_vol": {"score": structural_raw},
            "speed": {
                "score": speed_score,
                "state": "CONFIRMED_CANARY_ACTIVE" if cca else "NEUTRAL",
                "confirmed_canary_active": cca,
                "buy_the_dip_active": False,
            },
            "canary": {
                "score": round(score_v, 2),
                "raw_score": round(score_v, 2),
                "band": band,
                "warning_state": warning_state,
                "composite_version": 2,
                "score_form": "linear",
            },
            "inputs": {"spx_close": float(1000.0 + d.toordinal() % 500)},
        }
        repo.insert_snapshot(
            payload=payload,
            data_date=d,
            composite_version=2,
            score_form="linear",
            score=Decimal(str(round(score_v, 2))),
            raw_score=Decimal(str(round(score_v, 2))),
            band=band,
            tactical_score=Decimal(str(tactical_raw)),
            structural_score=Decimal(str(structural_raw)),
            speed_score=speed_score,
            warning_state=warning_state,
            payload_hash=canonical_payload_hash(payload),
            on_conflict="noop",
        )
        inserted += 1
    conn.commit()
    return inserted
