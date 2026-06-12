"""Migration 070 — basis column + chart generated columns on cri/vcg snapshots."""

from __future__ import annotations

import json


def _cols(conn, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = 'uw_scan' AND table_name = %s
            """,
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


def test_070_adds_basis_and_chart_columns(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    cri = _cols(conn, "cri_snapshots")
    assert {"basis", "spx", "vix3m", "vrp", "vix_zscore_30d", "vix_vix3m_ratio"} <= cri
    vcg = _cols(conn, "vcg_snapshots")
    assert {"basis", "residual", "credit_5d_return", "beta1", "beta2"} <= vcg


def test_070_basis_defaults_to_eod_and_generated_cols_extract(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    payload = {
        "date": "2026-06-11",
        "vix": 22.22,
        "vvix": 108.16,
        "spy": 7266.99,
        "cor1m": 17.8,
        "vix3m": 22.89,
        "vrp": 7.82,
        "vix_zscore_30d": 3.6,
        "vix_vix3m_ratio": 0.971,
        "realized_vol": 14.4,
        "spx_distance_pct": 3.7,
        "cri": {"score": 41.0, "level": "ELEVATED"},
        "crash_trigger": {"fired": False},
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.cri_snapshots (data_date, payload) "
            "VALUES ('2026-06-11', %s::jsonb) RETURNING basis, spx::float8, "
            "vix3m::float8, vrp::float8, vix_zscore_30d::float8, "
            "vix_vix3m_ratio::float8",
            (json.dumps(payload),),
        )
        basis, spx, vix3m, vrp, vix_z, ratio = cur.fetchone()
    conn.commit()
    assert basis == "eod"
    assert (spx, vix3m, vrp, vix_z, ratio) == (7266.99, 22.89, 7.82, 3.6, 0.971)


def test_070_vcg_generated_cols_extract(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    payload = {
        "date": "2026-06-11",
        "credit_proxy": "HYG",
        "signal": {
            "vcg": 1.44,
            "vcg_adj": 1.44,
            "residual": 0.003446,
            "credit_5d_return_pct": -0.19,
            "beta1_vvix": 0.013704,
            "beta2_vix": -0.025669,
            "vix": 19.87,
            "vvix": 95.81,
            "credit_price": 79.75,
        },
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.vcg_snapshots (data_date, payload) "
            "VALUES ('2026-06-11', %s::jsonb) RETURNING basis, residual::float8, "
            "credit_5d_return::float8, beta1::float8, beta2::float8",
            (json.dumps(payload),),
        )
        basis, residual, c5d, b1, b2 = cur.fetchone()
    conn.commit()
    assert basis == "eod"
    assert (residual, c5d, b1, b2) == (0.003446, -0.19, 0.013704, -0.025669)
