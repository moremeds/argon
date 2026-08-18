"""Full job loop: seed vol_index_daily -> issue -> re-run skips -> next close settles."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from uw_scan.config import Settings
from uw_scan.density.forecast import load_frozen_panel
from uw_scan.storage.spx_density_repository import SpxDensityRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.spx_density_forecast import spx_density_forecast_job

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (
        REPO_ROOT / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
    ).read_text()
)


def _bar(d: date, close: float) -> dict:
    return {
        "symbol": "SPX",
        "trade_date": d,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "adj_close": close,
        "volume": 0,
    }


def _seed_spx(repo) -> None:
    panel = load_frozen_panel()
    rows = [
        _bar(d.date(), float(c))
        for d, c in zip(
            pd.to_datetime(panel["trade_date"]), panel["close"], strict=True
        )
    ]
    rows += [
        _bar(date.fromisoformat(b["date"]), float(b["close"]))
        for b in GOLDEN["provenance"]["fresh_bars_appended"]
    ]
    VolIndexRepository(repo.conn, schema=repo._schema).upsert_rows(rows)


def test_issue_then_skip_then_settle(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    settings = Settings.from_env()
    _seed_spx(repo)

    out1 = spx_density_forecast_job(repo, settings)
    assert out1["issued"] == 5 and out1["as_of"] == "2026-07-30"
    assert out1["fallback_used"] is False

    out2 = spx_density_forecast_job(repo, settings)
    assert out2["issued"] == 0 and out2["skipped"] == "already_issued"

    # next session closes 1% above the anchor -> h=1 settles inside the 80% band
    anchor_close = float(GOLDEN["anchor"]["close"])
    VolIndexRepository(repo.conn, schema=repo._schema).upsert_rows(
        [_bar(date(2026, 7, 31), anchor_close * 1.01)]
    )
    out3 = spx_density_forecast_job(repo, settings)
    assert out3["settled"] == 1
    assert out3["issued"] == 5 and out3["as_of"] == "2026-07-31"

    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)
    row_h1 = sdr.fetch_forecast(date(2026, 7, 30))[0]
    assert row_h1["target_date"] == date(2026, 7, 31)
    assert abs(float(row_h1["realised_return"]) - 0.01) < 1e-12
    # the committed run's h=1 band80 is [-1.17%, +1.23%]; +1% realised lands inside
    assert row_h1["inside_band80"] is True


def test_reconstruct_fills_outage_hole_without_relabelling_prospective(
    seeded_db_empty_cards,
):
    """The 2026-08-14 failure mode: a session whose issue run never fired.

    The issue pass only ever anchors the freshest bar, so once a later cone lands the
    skipped session is unreachable forever. The reconstruct pass fills it — but a row the
    model published forward must keep origin='prospective', or an out-of-sample cone
    silently joins the in-sample tally.
    """
    repo = seeded_db_empty_cards
    settings = Settings.from_env()
    _seed_spx(repo)
    sdr = SpxDensityRepository(repo.conn, schema=repo._schema)

    out1 = spx_density_forecast_job(repo, settings)
    assert out1["as_of"] == "2026-07-30"
    # nothing to fill yet, and pre-panel history is the backfill script's job, not ours
    assert out1["reconstructed"] == 0

    # Two sessions land while the stack is down, so 07-31's anchor is never issued.
    anchor_close = float(GOLDEN["anchor"]["close"])
    VolIndexRepository(repo.conn, schema=repo._schema).upsert_rows(
        [
            _bar(date(2026, 7, 31), anchor_close * 1.01),
            _bar(date(2026, 8, 3), anchor_close * 1.02),
        ]
    )

    out2 = spx_density_forecast_job(repo, settings)
    assert out2["issued"] == 5 and out2["as_of"] == "2026-08-03"
    assert out2["reconstructed"] == 1

    filled = sdr.fetch_forecast(date(2026, 7, 31))
    assert len(filled) == 5
    assert {r["origin"] for r in filled} == {"reconstructed"}
    # the freshest anchor stays the issue pass's, prospectively
    assert {r["origin"] for r in sdr.fetch_forecast(date(2026, 8, 3))} == {
        "prospective"
    }
    # and the earlier forward-issued cone is NOT relabelled by the fill
    assert {r["origin"] for r in sdr.fetch_forecast(date(2026, 7, 30))} == {
        "prospective"
    }

    # idempotent: a second run finds no hole and rewrites nothing
    assert spx_density_forecast_job(repo, settings)["reconstructed"] == 0


def test_panel_mismatch_refuses_but_settles(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    settings = Settings.from_env()
    _seed_spx(repo)
    # corrupt one panel-window close in the DB
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.vol_index_daily SET close = close + 0.01 "
            "WHERE symbol = 'SPX' AND trade_date = '2010-06-01'"
        )
    repo.conn.commit()
    out = spx_density_forecast_job(repo, settings)
    assert out["issued"] == 0 and out["error"] == "panel_mismatch"
