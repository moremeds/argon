from uw_scan.models import TechnicalsSeriesRow


def test_series_row_accepts_dual_macd_fields():
    row = TechnicalsSeriesRow(
        as_of="2026-07-09",
        close=100.0,
        fast_macd_hist_atr=-0.4,
        slow_macd_hist_atr=0.8,
    )
    assert row.fast_macd_hist_atr == -0.4
    assert row.slow_macd_hist_atr == 0.8
