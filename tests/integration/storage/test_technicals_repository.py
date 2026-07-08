"""Integration tests for TechnicalsRepository (real Postgres)."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.technicals_repository import TechnicalsRepository


def _row(d: date, close: float, z: float | None = None) -> dict:
    return {
        "as_of": d,
        "close": close,
        "sma20": close,
        "sma50": close,
        "sma200": close,
        "z_vs_200dma": z,
        "z_band": "NEUTRAL" if z is not None else None,
        "sma200_slope_ann": 0.05,
        "slope_regime": "UPTREND",
        "rsi14": 55.0,
        "macd_hist_atr": 0.1,
        "rs_ratio": 1.0,
    }


def test_upsert_fetch_roundtrip_and_idempotency(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    trepo = TechnicalsRepository(repo.conn)
    rows = [_row(date(2026, 7, 6), 100.0, 0.2), _row(date(2026, 7, 7), 101.0, 0.3)]
    assert trepo.upsert_series("NVDA", rows) == 2
    assert trepo.upsert_series("NVDA", rows) == 2  # idempotent re-run

    got = trepo.fetch_series("NVDA")
    assert [r["as_of"] for r in got] == [date(2026, 7, 6), date(2026, 7, 7)]
    assert got[-1]["close"] == 101.0

    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM technical_daily WHERE ticker = 'NVDA'")
        assert cur.fetchone()[0] == 2  # upsert, not duplicate insert


def test_set_latest_detail_nulls_older_rows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    trepo = TechnicalsRepository(repo.conn)
    d1, d2 = date(2026, 7, 6), date(2026, 7, 7)
    trepo.upsert_series("NVDA", [_row(d1, 100.0), _row(d2, 101.0)])
    trepo.set_latest_detail("NVDA", d1, detail={"composite": 0.5}, forward_returns=[])
    trepo.set_latest_detail(
        "NVDA",
        d2,
        detail={"composite": 0.6},
        forward_returns=[
            {
                "band": "NEUTRAL",
                "horizon": 40,
                "count": 10,
                "mean": 0.01,
                "median": 0.008,
                "win_rate": 0.6,
            }
        ],
    )
    latest = trepo.fetch_latest("NVDA")
    assert latest["as_of"] == d2
    assert latest["detail"]["composite"] == 0.6
    assert latest["forward_returns"][0]["band"] == "NEUTRAL"
    series = trepo.fetch_series("NVDA")
    assert series[0]["detail"] is None  # older row's blob was NULLed


def test_fetch_latest_missing_ticker(seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    assert trepo.fetch_latest("ZZZZ") is None


def test_fetch_latest_macd_all(seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    trepo.upsert_series("AAA", [_row(date(2026, 7, 7), 100.0)])
    trepo.upsert_series(
        "BBB", [_row(date(2026, 7, 6), 100.0), _row(date(2026, 7, 7), 101.0)]
    )
    rows = trepo.fetch_latest_macd_all()
    assert {r["ticker"] for r in rows} >= {"AAA", "BBB"}
