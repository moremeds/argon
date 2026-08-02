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


def _seed_cone(sdr, *, as_of: date, anchor_close: float, density=None) -> None:
    base = {
        "as_of": as_of,
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
        "anchor_close": anchor_close,
        "params_jsonb": None,
        "fallback_used": False,
        "origin": "prospective",
        "provenance_jsonb": {"series_index": 4239},
        "density_bins_jsonb": density,
    }
    sdr.upsert_rows(
        [{**base, "h": h, "scored_horizon": h in (1, 2, 3, 5)} for h in range(1, 6)]
    )


def test_degenerate_call_wall_never_reaches_the_chart(client, seeded_db_empty_cards):
    """End-to-end proof of the side-guard. The snapshot below is a REAL observation:
    SPX 2026-07-28 in the local dev DB had call_wall == put_wall == 7000 against a
    7383 spot. Drawing 'resistance 7,000' under spot would be a false statement, so the
    API must omit it and say so in `dropped`."""
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    _seed_cone(sdr, as_of=date(2026, 7, 28), anchor_close=7383.0)
    with repo.conn.cursor() as cur:
        cur.execute(
            """INSERT INTO uw_scan.gex_snapshots (ticker, data_date, payload)
               VALUES ('SPX', %s, %s)""",
            (
                date(2026, 7, 28),
                '{"spot": 7383.0, "net_gex": -34803.27, "levels": '
                '{"call_wall": {"strike": 7000.0}, "put_wall": {"strike": 7000.0}, '
                '"gex_flip": {"strike": 7525.0}}}',
            ),
        )
    repo.conn.commit()

    levels = client.get("/api/regime/spx-density").json()["gamma_levels"]
    assert levels["source"] == "gex_snapshots"
    assert levels["call_wall"] is None
    assert levels["dropped"] == ["call_wall"]
    # a put wall below spot is structurally valid, and the flip is exempt entirely
    assert levels["put_wall"] == 7000.0
    assert levels["gamma_flip"] == 7525.0


def test_uw_levels_win_and_density_bins_round_trip(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    density = {
        "lo": -0.02,
        "hi": 0.02,
        "n_bins": 4,
        "counts": [1000, 4000, 4000, 1000],
        "total": 10000,
        "clipped": 0,
    }
    _seed_cone(sdr, as_of=date(2026, 7, 28), anchor_close=7383.0, density=density)
    with repo.conn.cursor() as cur:
        cur.execute(
            """INSERT INTO uw_scan.uw_gex_levels_daily
               (ticker, market_date, call_wall, put_wall, gamma_flip, spot)
               VALUES ('SPX', %s, 7500, 7300, 7450, 7383)""",
            (date(2026, 7, 28),),
        )
        # a same-day snapshot with the degenerate values must lose to the UW row
        cur.execute(
            """INSERT INTO uw_scan.gex_snapshots (ticker, data_date, payload)
               VALUES ('SPX', %s, %s)""",
            (
                date(2026, 7, 28),
                '{"spot": 7383.0, "levels": {"call_wall": {"strike": 7000.0}}}',
            ),
        )
    repo.conn.commit()

    body = client.get("/api/regime/spx-density").json()
    levels = body["gamma_levels"]
    assert levels["source"] == "uw_gex_levels_daily"
    assert (levels["call_wall"], levels["put_wall"], levels["gamma_flip"]) == (
        7500.0,
        7300.0,
        7450.0,
    )
    assert levels["dropped"] == []
    assert body["forecast"]["rows"][0]["density"] == density


def test_a_stale_level_capture_is_not_drawn_at_all(client, seeded_db_empty_cards):
    """If the levels capture stops, the chart must lose its dealer lines rather than
    keep the last ones it saw. The row below is internally consistent (call wall above
    ITS spot), so the side-guard alone would pass it through — only the bounded lookback
    stops walls from a session seven weeks gone being drawn against today's price."""
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    _seed_cone(sdr, as_of=date(2026, 7, 28), anchor_close=7383.0)
    with repo.conn.cursor() as cur:
        cur.execute(
            """INSERT INTO uw_scan.uw_gex_levels_daily
               (ticker, market_date, call_wall, put_wall, gamma_flip, spot)
               VALUES ('SPX', %s, 6200, 6000, 6100, 6150)""",
            (date(2026, 6, 5),),
        )
    repo.conn.commit()

    levels = client.get("/api/regime/spx-density").json()["gamma_levels"]
    assert levels["source"] is None
    assert (levels["call_wall"], levels["put_wall"], levels["gamma_flip"]) == (
        None,
        None,
        None,
    )


def test_missing_density_bins_stay_null(client, seeded_db_empty_cards):
    """Cones issued before migration 112 must still render — bands only, no crash."""
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    _seed_cone(sdr, as_of=date(2026, 7, 30), anchor_close=7437.63, density=None)
    body = client.get("/api/regime/spx-density").json()
    assert all(r["density"] is None for r in body["forecast"]["rows"])
    assert body["gamma_levels"]["source"] is None
