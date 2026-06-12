"""basis-aware snapshot repo surface: insert, fetch_latest filter,
intraday session grouping, daily history."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository

ET_NOON_UTC = 16  # 12:00 ET == 16:00 UTC in June (EDT)


def _cri_payload(d: str, score: float) -> dict:
    return {
        "date": d,
        "vix": 22.0,
        "vvix": 108.0,
        "spy": 7266.0,
        "cor1m": 17.8,
        "vix3m": 22.9,
        "vrp": 7.8,
        "vix_zscore_30d": 3.6,
        "vix_vix3m_ratio": 0.971,
        "realized_vol": 14.4,
        "spx_distance_pct": 3.7,
        "cri": {"score": score, "level": "ELEVATED"},
        "crash_trigger": {"fired": False},
    }


def _set_scanned_at(conn, table: str, row_id: int, ts: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE uw_scan.{table} SET scanned_at = %s WHERE id = %s", (ts, row_id)
        )
    conn.commit()


def test_cri_fetch_latest_defaults_to_eod(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    repo = CriSnapshotRepository(conn)
    repo.insert_snapshot(
        payload=_cri_payload("2026-06-11", 41.0), data_date=date(2026, 6, 11)
    )
    repo.insert_snapshot(
        payload={**_cri_payload("2026-06-12", 44.0), "basis": "live"},
        data_date=date(2026, 6, 12),
        basis="live",
    )
    latest = repo.fetch_latest()
    assert latest["cri"]["score"] == 41.0  # live row must NOT shadow eod default
    latest_live = repo.fetch_latest(basis="live")
    assert latest_live["cri"]["score"] == 44.0
    # the pre-live history surface must keep excluding live rows
    hist = repo.fetch_history(limit=30)
    assert [r["cri_score"] for r in hist] == [41.0]


def test_cri_intraday_sessions_group_by_et_date(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    repo = CriSnapshotRepository(conn)
    # two live points on 06-11, one on 06-12, one eod row that must be excluded
    rid1 = repo.insert_snapshot(
        payload=_cri_payload("2026-06-11", 40.0),
        data_date=date(2026, 6, 11),
        basis="live",
    )
    rid2 = repo.insert_snapshot(
        payload=_cri_payload("2026-06-11", 41.0),
        data_date=date(2026, 6, 11),
        basis="live",
    )
    rid3 = repo.insert_snapshot(
        payload=_cri_payload("2026-06-12", 43.0),
        data_date=date(2026, 6, 12),
        basis="live",
    )
    repo.insert_snapshot(
        payload=_cri_payload("2026-06-12", 99.0),
        data_date=date(2026, 6, 12),
        basis="eod",
    )
    base = datetime(2026, 6, 11, ET_NOON_UTC, 0, tzinfo=timezone.utc)
    _set_scanned_at(conn, "cri_snapshots", rid1, base)
    _set_scanned_at(conn, "cri_snapshots", rid2, base + timedelta(minutes=5))
    _set_scanned_at(conn, "cri_snapshots", rid3, base + timedelta(days=1))
    sessions = repo.fetch_intraday_sessions(sessions=5, rth_only=True)
    assert [s["et_date"].isoformat() for s in sessions] == ["2026-06-11", "2026-06-12"]
    assert [p["cri_score"] for p in sessions[0]["points"]] == [40.0, 41.0]
    assert sessions[1]["points"][0]["spx"] == 7266.0


def test_cri_daily_history_latest_eod_per_day(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    repo = CriSnapshotRepository(conn)
    repo.insert_snapshot(
        payload=_cri_payload("2026-06-10", 30.0), data_date=date(2026, 6, 10)
    )
    repo.insert_snapshot(
        payload=_cri_payload("2026-06-10", 31.0), data_date=date(2026, 6, 10)
    )
    repo.insert_snapshot(
        payload=_cri_payload("2026-06-11", 41.0), data_date=date(2026, 6, 11)
    )
    repo.insert_snapshot(
        payload=_cri_payload("2026-06-11", 88.0),
        data_date=date(2026, 6, 11),
        basis="live",
    )
    rows = repo.fetch_daily_history(days=90)
    assert [(r["date"].isoformat(), r["cri_score"]) for r in rows] == [
        ("2026-06-10", 31.0),
        ("2026-06-11", 41.0),
    ]


def _vcg_payload(d: str, vcg: float) -> dict:
    return {
        "date": d,
        "credit_proxy": "HYG",
        "signal": {
            "vcg": vcg,
            "vcg_adj": vcg,
            "residual": 0.003,
            "credit_5d_return_pct": -0.19,
            "beta1_vvix": 0.0137,
            "beta2_vix": -0.0257,
            "vix": 19.9,
            "vvix": 95.8,
            "credit_price": 79.75,
        },
    }


def test_vcg_intraday_and_daily(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    repo = VcgSnapshotRepository(conn)
    rid = repo.insert_snapshot(
        payload=_vcg_payload("2026-06-11", 1.44),
        data_date=date(2026, 6, 11),
        basis="live",
    )
    repo.insert_snapshot(
        payload=_vcg_payload("2026-06-11", 1.40), data_date=date(2026, 6, 11)
    )
    _set_scanned_at(
        conn,
        "vcg_snapshots",
        rid,
        datetime(2026, 6, 11, ET_NOON_UTC, 0, tzinfo=timezone.utc),
    )
    sessions = repo.fetch_intraday_sessions(proxy="HYG", sessions=5, rth_only=True)
    assert len(sessions) == 1
    assert sessions[0]["points"][0]["vcg"] == 1.44
    assert sessions[0]["points"][0]["credit_price"] == 79.75
    daily = repo.fetch_daily_history(proxy="HYG", days=90)
    assert [(r["date"].isoformat(), r["vcg"]) for r in daily] == [("2026-06-11", 1.40)]
    assert repo.fetch_latest(proxy="HYG")["signal"]["vcg"] == 1.40  # eod default
    # the pre-live history surface must keep excluding live rows
    hist = repo.fetch_history(proxy="HYG", limit=30)
    assert [r["vcg_score"] for r in hist] == [1.40]
