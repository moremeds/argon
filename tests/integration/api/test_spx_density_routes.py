"""Route contract: empty DB -> null forecast; seeded rows -> full shape."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.spx_density_repository import SpxDensityRepository


def test_empty_db_returns_null_forecast(client, seeded_db_empty_cards):
    body = client.get("/api/regime/spx-density").json()
    assert body["forecast"] is None
    assert body["recent_path"] == []
    assert "not a trading signal" in body["disclaimer"].lower()


def test_seeded_rows_round_trip(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    base = {
        "as_of": date(2026, 7, 30),
        "target_date": date(2026, 7, 31),
        "q05": -0.016333,
        "q10": -0.011705,
        "q25": -0.004442,
        "q50": 0.001009,
        "q75": 0.006935,
        "q90": 0.012317,
        "q95": 0.015372,
        "baseline_q05": -0.014103,
        "baseline_q10": -0.011005,
        "baseline_q25": -0.005807,
        "baseline_q50": 0.0,
        "baseline_q75": 0.005841,
        "baseline_q90": 0.011127,
        "baseline_q95": 0.014304,
        "band80_width": 0.024022,
        "baseline_band80_width": 0.022132,
        "width_ratio": 1.085441,
        "anchor_close": 7437.63,
        "params_jsonb": {
            "omega": 0.0394,
            "alpha": 0.0141,
            "gamma": 0.2364,
            "beta": 0.8339,
        },
        "fallback_used": False,
        "origin": "prospective",
        "provenance_jsonb": {"series_index": 4239},
    }
    sdr.upsert_rows(
        [{**base, "h": h, "scored_horizon": h in (1, 2, 3, 5)} for h in range(1, 6)]
    )

    body = client.get("/api/regime/spx-density").json()
    f = body["forecast"]
    assert f["as_of"] == "2026-07-30"
    assert [r["h"] for r in f["rows"]] == [1, 2, 3, 4, 5]
    assert f["rows"][3]["scored_horizon"] is False  # h=4 unscored
    assert f["fallback_used"] is False
    assert f["rows"][0]["realised_return"] is None

    issued = client.get("/api/regime/spx-density/issued").json()
    assert issued["forecasts"] == []  # only one as_of exists; latest is skipped
    assert issued["hit_rates"] == []  # nothing settled yet
