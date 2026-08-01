"""Round-trip + settle semantics for spx_density_forecast."""

from datetime import date

from uw_scan.storage.spx_density_repository import SpxDensityRepository


def _row(h: int, as_of: date = date(2026, 7, 30)) -> dict:
    # values from the committed 2026-08-01 forward run, h=1 (repeated per h for simplicity)
    return {
        "as_of": as_of,
        "h": h,
        "target_date": date(2026, 7, 30 + h) if 30 + h <= 31 else date(2026, 8, h - 1),
        "scored_horizon": h in (1, 2, 3, 5),
        "q05": -0.01633321359465356,
        "q10": -0.011705426306386713,
        "q25": -0.004442375363439999,
        "q50": 0.0010092081497704575,
        "q75": 0.0069347905721822145,
        "q90": 0.01231707317456232,
        "q95": 0.015371712986999712,
        "baseline_q05": -0.014103,
        "baseline_q10": -0.011005,
        "baseline_q25": -0.005807,
        "baseline_q50": 0.0,
        "baseline_q75": 0.005841,
        "baseline_q90": 0.011127,
        "baseline_q95": 0.014304,
        "band80_width": 0.024022499480949033,
        "baseline_band80_width": 0.022131559863228463,
        "width_ratio": 1.085440864964171,
        "anchor_close": 7437.63,
        "params_jsonb": {
            "omega": 0.0394,
            "alpha": 0.0141,
            "gamma": 0.2364,
            "beta": 0.8339,
        },
        "fallback_used": False,
        "origin": "prospective",
        "provenance_jsonb": {"panel_sha256": "bd95c2ab", "series_index": 4239},
    }


def test_upsert_settle_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)

    assert sdr.upsert_rows([_row(h) for h in range(1, 6)]) == 5
    assert sdr.upsert_rows([_row(h) for h in range(1, 6)]) == 5  # idempotent re-run
    assert sdr.latest_as_of() == date(2026, 7, 30)
    assert sdr.fetch_recent_as_ofs(10) == [date(2026, 7, 30)]

    got = sdr.fetch_forecast(date(2026, 7, 30))
    assert [r["h"] for r in got] == [1, 2, 3, 4, 5]
    assert got[0]["realised_return"] is None
    assert len(sdr.fetch_unsettled()) == 5

    sdr.settle(date(2026, 7, 30), 1, date(2026, 7, 31), 0.0123, True)
    got = sdr.fetch_forecast(date(2026, 7, 30))
    assert got[0]["inside_band80"] is True
    assert float(got[0]["realised_return"]) == 0.0123
    assert len(sdr.fetch_unsettled()) == 4


def test_hit_rate_tally_splits_origin_and_scored(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    rows = [_row(h) for h in range(1, 6)]
    recon = [
        {**_row(h, as_of=date(2026, 7, 29)), "origin": "reconstructed"}
        for h in range(1, 6)
    ]
    sdr.upsert_rows(rows + recon)
    for h in range(1, 6):
        sdr.settle(date(2026, 7, 30), h, date(2026, 8, 6), 0.001, True)
        sdr.settle(date(2026, 7, 29), h, date(2026, 8, 5), 0.05, False)
    tally = {t["origin"]: t for t in sdr.hit_rate_tally()}
    # h=4 is unscored -> only 4 of 5 rows count per origin
    assert tally["prospective"] == {"origin": "prospective", "inside": 4, "total": 4}
    assert tally["reconstructed"] == {
        "origin": "reconstructed",
        "inside": 0,
        "total": 4,
    }
