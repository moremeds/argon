"""trailing_rv: RV at t must be the window ENDING at t, never UW's forward value.

UW's realized_volatility at market_date t is the 21-return window over returns
t..t+20 (verified 2026-09-24, MAE 0.0000). Fixtures are real rows frozen as of
2026-09-24: UW realized_volatility_history + massive daily_ohlc closes.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.cards.vol_series import trailing_rv

# AAPL (market_date, massive daily_ohlc close, UW realized_volatility).
AAPL_ROWS = [
    ("2026-06-01", 306.3100, 0.353004),
    ("2026-06-02", 315.2000, 0.355608),
    ("2026-06-03", 310.2600, 0.380763),
    ("2026-06-04", 311.2300, 0.379720),
    ("2026-06-05", 307.3400, 0.380286),
    ("2026-06-08", 301.5400, 0.378633),
    ("2026-06-09", 290.5500, 0.372397),
    ("2026-06-10", 291.5800, 0.344607),
    ("2026-06-11", 295.6300, 0.344703),
    ("2026-06-12", 291.1300, 0.345090),
    ("2026-06-15", 296.4200, 0.360154),
    ("2026-06-16", 299.2400, 0.359911),
    ("2026-06-17", 295.9500, 0.359892),
    ("2026-06-18", 298.0100, 0.367713),
    ("2026-06-22", 297.0100, 0.367641),
    ("2026-06-23", 294.3000, 0.368348),
    ("2026-06-24", 293.0800, 0.370402),
    ("2026-06-25", 275.1500, 0.383544),
    ("2026-06-26", 283.7800, 0.289449),
    ("2026-06-29", 281.7400, 0.278961),
    ("2026-06-30", 289.3600, 0.277843),
    ("2026-07-01", 294.3800, 0.280549),
    ("2026-07-02", 308.6300, 0.398946),
    ("2026-07-06", 312.6600, 0.369151),
    ("2026-07-07", 310.6600, 0.372863),
    ("2026-07-08", 313.3900, 0.372716),
    ("2026-07-09", 316.2200, 0.371760),
    ("2026-07-10", 315.3200, 0.370475),
    ("2026-07-13", 317.3100, 0.374493),
    ("2026-07-14", 314.8600, 0.374974),
    ("2026-07-15", 327.5000, 0.375189),
    ("2026-07-16", 333.2600, 0.347159),
    ("2026-07-17", 333.7400, 0.339594),
    ("2026-07-20", 326.5900, 0.339186),
    ("2026-07-21", 327.7400, 0.338812),
    ("2026-07-22", 325.8900, 0.348577),
    ("2026-07-23", 321.6600, 0.352758),
    ("2026-07-24", 333.0200, 0.350899),
    ("2026-07-27", 336.9100, 0.325591),
    ("2026-07-28", 340.0800, 0.321139),
    ("2026-07-29", 338.1900, 0.322274),
    ("2026-07-30", 333.4300, 0.323233),
    ("2026-07-31", 308.9100, 0.327587),
    ("2026-08-03", 303.4200, 0.188375),
    ("2026-08-04", 309.3800, 0.193234),
    ("2026-08-05", 311.0000, 0.184370),
]

# KLAC across its 10:1 split (2026-06-12): (market_date, UW price, massive close).
# UW's price is raw before the split; massive's close is adjusted.
KLAC_ROWS = [
    ("2026-05-11", 1845.19, 184.5190),
    ("2026-05-12", 1811.35, 181.1350),
    ("2026-05-13", 1849.71, 184.9710),
    ("2026-05-14", 1892.94, 189.2940),
    ("2026-05-15", 1804.32, 180.4320),
    ("2026-05-18", 1756.45, 175.6450),
    ("2026-05-19", 1740.58, 174.0580),
    ("2026-05-20", 1829.47, 182.9470),
    ("2026-05-21", 1842.18, 184.2180),
    ("2026-05-22", 1888.38, 188.8380),
    ("2026-05-26", 2011.39, 201.1390),
    ("2026-05-27", 1957.19, 195.7190),
    ("2026-05-28", 1927.63, 192.7630),
    ("2026-05-29", 1921.71, 192.1710),
    ("2026-06-01", 1940.04, 194.0040),
    ("2026-06-02", 2045.2, 204.5200),
    ("2026-06-03", 2125.11, 212.5110),
    ("2026-06-04", 2131.1, 213.1100),
    ("2026-06-05", 1929.2, 192.9200),
    ("2026-06-08", 2108.06, 210.8060),
    ("2026-06-09", 2139.37, 213.9370),
    ("2026-06-10", 2135.64, 213.5640),
    ("2026-06-11", 2411.64, 241.1640),
    ("2026-06-12", 254.54, 254.5400),
    ("2026-06-15", 256.42, 256.4200),
    ("2026-06-16", 237.33, 237.3300),
    ("2026-06-17", 238.73, 238.7300),
    ("2026-06-18", 259.56, 259.5600),
    ("2026-06-22", 269.16, 269.1600),
    ("2026-06-23", 244.49, 244.4900),
    ("2026-06-24", 240.48, 240.4800),
    ("2026-06-25", 258.8, 258.8000),
    ("2026-06-26", 248.64, 248.6400),
    ("2026-06-29", 278.39, 278.3900),
    ("2026-06-30", 301.71, 301.7100),
    ("2026-07-01", 266.19, 266.1900),
    ("2026-07-02", 235.55, 235.5500),
    ("2026-07-06", 233.31, 233.3100),
    ("2026-07-07", 216.47, 216.4700),
    ("2026-07-08", 221.18, 221.1800),
    ("2026-07-09", 229.52, 229.5200),
    ("2026-07-10", 231.52, 231.5200),
]


def _aapl() -> tuple[list[dict], list[tuple[date, float]]]:
    rows = [
        {"market_date": date.fromisoformat(d), "price": None, "realized_volatility": rv}
        for d, _c, rv in AAPL_ROWS
    ]
    return rows, [(date.fromisoformat(d), c) for d, c, _rv in AAPL_ROWS]


def test_trailing_rv_is_uw_value_shifted_back_20_rows():
    rows, closes = _aapl()
    out = trailing_rv(rows, closes)
    # Rows 0..20 have < 21 returns behind them: no trailing RV, even though
    # UW's (forward) value is present — it must not leak through.
    assert all(r["realized_volatility"] is None for r in out[:21])
    for i in range(21, len(out)):
        assert out[i]["realized_volatility"] == pytest.approx(
            AAPL_ROWS[i - 20][2], abs=1e-3
        )


def test_trailing_rv_ignores_uw_value_at_same_date():
    rows, closes = _aapl()
    out = trailing_rv(rows, closes)
    # Same-date equality would mean the lookahead value survived.
    assert out[30]["realized_volatility"] != pytest.approx(AAPL_ROWS[30][2], abs=1e-3)
    assert rows[30]["realized_volatility"] == AAPL_ROWS[30][2]  # input not mutated


def test_uses_adjusted_closes_not_raw_uw_price_across_a_split():
    rows = [
        {"market_date": date.fromisoformat(d), "price": p} for d, p, _c in KLAC_ROWS
    ]
    closes = [(date.fromisoformat(d), c) for d, _p, c in KLAC_ROWS]
    rvs = [r["realized_volatility"] for r in trailing_rv(rows, closes)]
    assert max(v for v in rvs if v is not None) < 1.5  # raw price would give > 5


def test_dates_without_a_close_get_none():
    rows, closes = _aapl()
    assert trailing_rv(rows, closes[:-1])[-1]["realized_volatility"] is None
    assert trailing_rv([], closes) == []
