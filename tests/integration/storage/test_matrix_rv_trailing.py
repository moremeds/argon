"""fetch_matrix_realized_vol_history returns TRAILING RV, never UW's forward value.

The SQL window over daily_ohlc must agree with cards.vol_series.trailing_rv (its
pandas twin), must warm up from closes BEFORE the requested range, and must use
the adjusted close rather than UW's raw price across a split.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.unit.cards.test_vol_series_trailing_rv import AAPL_ROWS, KLAC_ROWS
from uw_scan.cards.vol_series import trailing_rv


def _seed(repo, ticker: str, rows: list[tuple[str, float, float]]) -> None:
    """rows: (market_date, UW price, massive close)."""
    with repo.conn.cursor() as cur:
        for d, price, close in rows:
            day = date.fromisoformat(d)
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility) VALUES (%s, %s, %s, 0.3)",
                (ticker, day, price),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.daily_ohlc (ticker, date, close, source) "
                "VALUES (%s, %s, %s, 'massive.com')",
                (ticker, day, close),
            )
    repo.conn.commit()


@pytest.mark.parametrize(
    ("ticker", "rows", "days"),
    [
        # AAPL: UW price column unused (None); close = massive.
        ("AAPL", [(d, None, c) for d, c, _rv in AAPL_ROWS], 10),
        ("KLAC", KLAC_ROWS, 30),
    ],
)
def test_matrix_rv_matches_pandas_twin(seeded_db_empty_cards, ticker, rows, days):
    repo = seeded_db_empty_cards
    _seed(repo, ticker, rows)
    last = date.fromisoformat(rows[-1][0])
    got = repo.fetch_matrix_realized_vol_history(
        ticker=ticker, market_date=last, days=days
    )
    expected = {
        r["market_date"]: r["realized_volatility"]
        for r in trailing_rv(
            [{"market_date": date.fromisoformat(d)} for d, _p, _c in rows],
            [(date.fromisoformat(d), c) for d, _p, c in rows],
        )
    }
    assert got
    for r in got:
        assert r["realized_volatility"] is not None  # warmed up from pre-range closes
        assert float(r["realized_volatility"]) == pytest.approx(
            expected[r["market_date"]], abs=1e-9
        )
        assert float(r["realized_volatility"]) < 1.5


# SPX: real UW `price` (realized_volatility_history), as of 2026-09-18. massive
# serves no index bars, so SPX has no daily_ohlc rows at all.
SPX_ROWS = [
    ("2026-07-30", 7437.63),
    ("2026-07-31", 7489.72),
    ("2026-08-03", 7600.5),
    ("2026-08-04", 7736.52),
    ("2026-08-05", 7723.55),
    ("2026-08-06", 7709.96),
    ("2026-08-07", 7757.64),
    ("2026-08-10", 7753.11),
    ("2026-08-11", 7728.2),
    ("2026-08-12", 7748.5),
    ("2026-08-13", 7798.99),
    ("2026-08-14", 7785.76),
    ("2026-08-17", 7745.06),
    ("2026-08-18", 7691.76),
    ("2026-08-19", 7707.98),
    ("2026-08-20", 7641.16),
    ("2026-08-21", 7674.37),
    ("2026-08-24", 7652.86),
    ("2026-08-25", 7677.28),
    ("2026-08-26", 7675.7),
    ("2026-08-27", 7730.99),
    ("2026-08-28", 7711.76),
    ("2026-08-31", 7686.14),
    ("2026-09-01", 7631.47),
    ("2026-09-02", 7666.6),
    ("2026-09-03", 7747.71),
    ("2026-09-04", 7718.6),
    ("2026-09-08", 7673.52),
    ("2026-09-09", 7636.36),
    ("2026-09-10", 7591.7),
    ("2026-09-11", 7656.98),
    ("2026-09-14", 7619.98),
    ("2026-09-15", 7585.73),
    ("2026-09-16", 7551.81),
    ("2026-09-17", 7637.76),
    ("2026-09-18", 7650.5),
]


def test_matrix_rv_falls_back_to_uw_price_without_daily_ohlc(seeded_db_empty_cards):
    """No daily_ohlc for the ticker → trailing RV from UW price, same as the twin."""
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        for d, price in SPX_ROWS:
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility) VALUES ('SPX', %s, %s, 0.15)",
                (date.fromisoformat(d), price),
            )
    repo.conn.commit()
    got = repo.fetch_matrix_realized_vol_history(
        ticker="SPX", market_date=date(2026, 9, 18), days=10
    )
    rows = [{"market_date": date.fromisoformat(d), "price": p} for d, p in SPX_ROWS]
    expected = {
        r["market_date"]: r["realized_volatility"] for r in trailing_rv(rows, [])
    }
    assert got
    for r in got:
        assert r["realized_volatility"] is not None
        assert float(r["realized_volatility"]) == pytest.approx(
            expected[r["market_date"]], abs=1e-9
        )
