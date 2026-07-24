import json
from datetime import date
from pathlib import Path

from uw_scan import normalize

FIX = Path("tests/fixtures/uw")


def _load(name):
    return json.loads((FIX / name).read_text())


def test_normalize_gex_levels_single_object():
    row = normalize.normalize_gex_levels(
        _load("gex_levels_aapl.json"), "AAPL", date(2026, 6, 30)
    )
    assert row is not None
    assert row.ticker == "AAPL"
    assert row.market_date == date(2026, 6, 30)
    assert row.call_wall is not None


def test_normalize_gex_levels_empty_returns_none():
    assert (
        normalize.normalize_gex_levels({"data": None}, "AAPL", date(2026, 6, 30))
        is None
    )


def test_normalize_gex_levels_all_none_levels_returns_none():
    # a dataless session (e.g. a date with no gex snapshot) returns all-None levels
    payload = {
        "data": {
            "call_wall": None,
            "put_wall": None,
            "gamma_flip": None,
            "gamma_magnet": None,
        }
    }
    assert normalize.normalize_gex_levels(payload, "AAPL", date(2026, 6, 20)) is None


def test_normalize_vol_anomaly_history_wrapper():
    rows = normalize.normalize_vol_anomaly(_load("volatility_anomaly_aapl.json"))
    assert rows
    assert all(r.date is not None for r in rows)


def test_normalize_vol_character_history_wrapper():
    rows = normalize.normalize_vol_character(_load("volatility_character_aapl.json"))
    assert rows
    assert all(r.date is not None for r in rows)


def test_normalize_vol_vrp_is_plain_list_not_empty():
    # regression guard: VRP is a plain data:[...] list, not {history,latest}.
    # _history_rows would return [] for this shape and silently drop everything.
    rows = normalize.normalize_vol_vrp(_load("volatility_vrp_aapl.json"))
    assert len(rows) > 100
    assert all(r.date is not None for r in rows)


def test_normalize_net_prem_ticks_maps_tape_time():
    rows = normalize.normalize_net_prem_ticks(_load("net_prem_ticks_aapl.json"))
    assert rows
    assert all(r.ts is not None for r in rows)


def test_normalize_greek_flow_maps_timestamp():
    rows = normalize.normalize_greek_flow(_load("greek_flow_aapl.json"))
    assert rows
    assert all(r.ts is not None for r in rows)


def test_normalize_dark_lit_serves_darkpool_and_lit():
    dp = normalize.normalize_dark_lit(_load("darkpool_aapl.json"))
    lit = normalize.normalize_dark_lit(_load("lit_flow_aapl.json"))
    assert dp and lit
    assert all(r.tracking_id for r in dp)
    # sale_cond_codes stays a list when present (TEXT[] column)
    assert all(
        r.sale_cond_codes is None or isinstance(r.sale_cond_codes, list) for r in lit
    )


def test_normalize_ftds_and_volumes():
    ftds = normalize.normalize_ftds(_load("ftds_aapl.json"))
    vols = normalize.normalize_volumes_by_exchange(
        _load("volumes_by_exchange_aapl.json")
    )
    assert ftds and all(r.date is not None for r in ftds)
    assert vols and all(r.date is not None for r in vols)
