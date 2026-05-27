"""Synthetic vol-complex fixture for canary form-sweep-full integration tests.

Seeds 600 trading days × 5 symbols into vol_index_daily (enough to clear the
350-bar MIN_ALIGNED_BARS warm-up with ~250 bars beyond) plus 200 days into
canary_snapshots so the MIN/MAX(data_date) window supports 60d forward labels
(60d AUC requires at least 60 buffer rows past the eval region).

Coherent but not realistic — designed to make the scoring pipeline run
without raising, NOT to produce meaningful AUC values. Tests in this PR
assert SHAPE (4 rows, batch_id present, etc.), not numeric correctness.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np


def _trading_days(start: date, n: int) -> list[date]:
    """n consecutive Mon-Fri days starting from `start` (skip Sat/Sun)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def seed_vol_index(conn, *, schema: str, n_days: int = 600) -> list[date]:
    """Insert n_days × {VIX, VVIX, VIX3M, COR1M, SPX} into vol_index_daily.

    Default is 600 (≥ 350 warm-up + ≥ 200 evaluable). Returns the list of
    trading dates (oldest first).
    """
    rng = np.random.default_rng(seed=42)
    dates = _trading_days(date(2010, 1, 4), n_days)

    spx = 1000.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n_days))
    vix = np.clip(15 + 5 * rng.standard_normal(n_days), 10, 50)
    vvix = np.clip(95 + 10 * rng.standard_normal(n_days), 70, 130)
    vix3m = vix * 1.05 + rng.normal(0, 0.5, n_days)
    cor1m = np.clip(50 + 8 * rng.standard_normal(n_days), 30, 70)

    rows = []
    for i, d in enumerate(dates):
        for sym, arr in (
            ("SPX", spx),
            ("VIX", vix),
            ("VVIX", vvix),
            ("VIX3M", vix3m),
            ("COR1M", cor1m),
        ):
            rows.append((sym, d, Decimal(str(round(float(arr[i]), 4)))))

    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {schema}.vol_index_daily "
            "(symbol, trade_date, close) VALUES (%s, %s, %s) "
            "ON CONFLICT (symbol, trade_date) DO NOTHING",
            rows,
        )
    conn.commit()
    return dates


def seed_canary_snapshots(
    conn, *, schema: str, dates: list[date], n_snapshots: int = 200
) -> tuple[date, date]:
    """Insert n_snapshots synthetic canary_snapshots rows.

    Default is 200 so that the form-sweep-full's 60d AUC labels are finite
    (200 - 60 = 140 evaluable rows per band). Uses the LAST n_snapshots from
    `dates` (i.e. the most recent slice). Returns (min_date, max_date).
    """
    seed_dates = dates[-n_snapshots:]
    rows = []
    for d in seed_dates:
        rows.append(
            (
                d,
                1,  # composite_version
                "linear",  # score_form
                Decimal("20.0"),  # score
                Decimal("20.0"),  # raw_score
                "NONE",  # band
                Decimal("5.0"),  # tactical_score
                Decimal("10.0"),  # structural_score
                0,  # speed_score (constraint allows 0, 8, or 20)
                "NONE",  # warning_state
                "abc123",  # payload_hash (any string)
                '{"inputs": {"spx_close": 1500.0}}',  # payload JSONB
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {schema}.canary_snapshots "
            "(data_date, composite_version, score_form, score, raw_score, "
            " band, tactical_score, structural_score, speed_score, "
            " warning_state, payload_hash, payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
            "ON CONFLICT (data_date, composite_version) DO NOTHING",
            rows,
        )
    conn.commit()
    return (seed_dates[0], seed_dates[-1])
