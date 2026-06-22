from __future__ import annotations

from datetime import date

# Real frozen VRP macro signal readouts — computed by reports/vrp_macro_signal.py
# from real VIX/SPX/VXN history (observed 2026-06-22). Hardcoded fixtures; tests
# never recompute or hit the network.
SPX_SKIP = dict(
    name="SPX",
    as_of=date(2026, 5, 21),
    spot=7445.72,
    iv=0.164,
    rv20=0.1612,
    vrp=0.0028,
    vrp_z=-1.953,
    weight=0.0,
    action="SKIP",
    short_put=None,
    long_put=None,
    put_width=None,
    credit=None,
    max_loss=None,
    hold_days=30,
    short_delta=0.25,
    wing_delta=0.125,
    bt_n=522,
    bt_sharpe=1.6524,
    bt_maxdd=-0.796,
    bt_annror=0.53,
    bt_calmar=0.67,
    config={"sizing": "ramp+", "short_delta": 0.25},
)
QQQ_TRADE = dict(
    name="QQQ",
    as_of=date(2026, 5, 15),
    spot=708.93,
    iv=0.2533,
    rv20=0.1672,
    vrp=0.0861,
    vrp_z=0.530,
    weight=1.0,
    action="TRADE",
    short_put=674.11,
    long_put=646.65,
    put_width=27.46,
    credit=5.67,
    max_loss=21.79,
    hold_days=30,
    short_delta=0.25,
    wing_delta=0.125,
    bt_n=422,
    bt_sharpe=1.0065,
    bt_maxdd=-0.7527,
    bt_annror=0.3543,
    bt_calmar=0.47,
    config={"sizing": "ramp+", "short_delta": 0.25},
)


def test_upsert_and_fetch_latest_per_name(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_signal(snapshot_date=date(2026, 6, 22), **SPX_SKIP)
    repo.upsert_vrp_macro_signal(snapshot_date=date(2026, 6, 22), **QQQ_TRADE)
    repo.conn.commit()

    by = {r["name"]: r for r in repo.fetch_latest_vrp_macro_signals()}
    assert set(by) == {"SPX", "QQQ"}
    assert by["SPX"]["action"] == "SKIP"
    assert float(by["SPX"]["weight"]) == 0.0
    assert float(by["SPX"]["bt_sharpe"]) == 1.6524
    assert by["SPX"]["short_put"] is None  # SKIP carries no structure
    assert by["QQQ"]["action"] == "TRADE"
    assert float(by["QQQ"]["credit"]) == 5.67
    assert by["QQQ"]["config_jsonb"] == {"sizing": "ramp+", "short_delta": 0.25}


def test_upsert_is_idempotent_same_day(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    snap = date(2026, 6, 22)
    repo.upsert_vrp_macro_signal(snapshot_date=snap, **SPX_SKIP)
    # same (name, snapshot_date) re-run overwrites in place — flip SKIP→TRADE
    repo.upsert_vrp_macro_signal(
        snapshot_date=snap, **{**SPX_SKIP, "action": "TRADE", "weight": 1.0}
    )
    repo.conn.commit()

    rows = repo.fetch_latest_vrp_macro_signals(names=["SPX"])
    assert len(rows) == 1  # one PK, not two
    assert rows[0]["action"] == "TRADE"
    assert float(rows[0]["weight"]) == 1.0


def test_fetch_latest_returns_newest_snapshot(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_signal(snapshot_date=date(2026, 6, 19), **SPX_SKIP)
    repo.upsert_vrp_macro_signal(
        snapshot_date=date(2026, 6, 22),
        **{**SPX_SKIP, "action": "TRADE", "weight": 1.0},
    )
    repo.conn.commit()

    rows = repo.fetch_latest_vrp_macro_signals(names=["spx"])  # case-insensitive
    assert len(rows) == 1
    assert rows[0]["snapshot_date"] == date(2026, 6, 22)  # newest wins
    assert rows[0]["action"] == "TRADE"


def test_fetch_latest_empty_is_empty_list(seeded_db_empty_cards) -> None:
    assert seeded_db_empty_cards.fetch_latest_vrp_macro_signals() == []
