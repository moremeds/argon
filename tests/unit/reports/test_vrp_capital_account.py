from datetime import date

from uw_scan.reports.vrp_macro_drawdown import INDEX_SPECS


def test_spy_in_index_specs():
    spec = INDEX_SPECS["SPY"]
    assert spec["vol"] == "VIX"
    assert spec["spot_source"] == "lake"
    assert spec["spot_symbol"] == "SPY"
    assert spec["start"] == date(2006, 1, 1)
