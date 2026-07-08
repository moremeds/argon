"""GET /api/stock/{ticker}/technicals — empty and ready paths."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.technicals_repository import TechnicalsRepository


def test_technicals_empty_when_no_rows(client, seeded_db_empty_cards):
    r = client.get("/api/stock/NVDA/technicals")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["backfill_status"] == "empty"
    assert body["series"] == []
    assert body["header"] is None


def test_technicals_ready_with_seeded_rows(client, seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    rows = [
        {
            "as_of": date(2026, 7, 6 + i),
            "close": 100.0 + i,
            "sma20": 100.0,
            "sma50": 99.0,
            "sma200": 95.0,
            "z_vs_200dma": 0.8,
            "z_band": "MILD HIGH",
            "sma200_slope_ann": 0.12,
            "slope_regime": "STRONG UPTREND",
            "rsi14": 60.0,
            "macd_hist_atr": 0.2,
            "rs_ratio": 1.05,
        }
        for i in range(2)
    ]
    trepo.upsert_series("NVDA", rows)
    trepo.set_latest_detail(
        "NVDA",
        date(2026, 7, 7),
        detail={
            "bars_n": 500,
            "composite": 0.55,
            "dist_pct": 0.06,
            "sigmoid": {"valid": False},
            "kinematics": {"alignment": 3},
            "distribution": {},
            "rsi": {},
            "macd": {"hist_atr": 0.2},
            "rs": {},
        },
        forward_returns=[
            {
                "band": "MILD HIGH",
                "horizon": 40,
                "count": 55,
                "mean": 0.021,
                "median": 0.018,
                "win_rate": 0.62,
            }
        ],
    )

    r = client.get("/api/stock/nvda/technicals")
    assert r.status_code == 200
    body = r.json()
    assert body["backfill_status"] == "ready"
    assert body["as_of"] == "2026-07-07"
    assert body["header"]["z_band"] == "MILD HIGH"
    assert body["header"]["slope_regime"] == "STRONG UPTREND"
    assert len(body["series"]) == 2
    assert body["forward_returns"][0]["count"] == 55
    assert body["detail"]["composite"] == 0.55


def test_technicals_model_exports():
    from uw_scan.models import (  # noqa: F401
        ForwardReturnBandRow,
        TechnicalsHeader,
        TechnicalsResponse,
        TechnicalsSeriesRow,
    )

    assert TechnicalsResponse.__module__ == "uw_scan.models"
