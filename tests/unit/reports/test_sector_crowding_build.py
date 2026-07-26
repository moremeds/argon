"""Assembly of crowding rows from repo reads, with a fake repo.

Shapes mirror Repository.fetch_etf_flows_daily (storage/gold_etf.py:80),
Repository.get_recent_etf_aum (storage/market_data.py:202) and the
fetch_iv_ranks method added in this task.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.reports.sector_crowding import RETURN_WINDOW, build_sector_crowding


def _flows(
    *,
    n: int,
    start_close: float,
    end_close: float,
    flow_per_day: float,
    late_boost: float = 1.0,
):
    """n sessions of geometric drift with a constant daily flow.

    `late_boost` adds an extra multiplier spread across the final 63 sessions.
    Without it the drift is perfectly constant, so EVERY trailing 63-session
    return is identical and pct_rank collapses to 0 -- the percentile leg needs
    today to actually stand out from its own history to be exercised.
    """
    rows = []
    day = date(2025, 7, 1)
    step = (end_close / start_close) ** (1.0 / max(n - 1, 1))
    boost = late_boost ** (1.0 / 63)
    close = start_close
    for i in range(n):
        rows.append(
            {
                "obs_date": day + timedelta(days=i),
                "share_change": Decimal("0"),
                "premium_change_usd": Decimal(str(flow_per_day)),
                "close": Decimal(str(round(close, 4))),
                "volume": Decimal("1000"),
            }
        )
        close *= step * (boost if i >= n - 63 else 1.0)
    return rows


class FakeRepo:
    def __init__(self, flows, aums, iv_ranks):
        self._flows = flows
        self._aums = aums
        self._iv_ranks = iv_ranks

    def fetch_etf_flows_daily(self, ticker, **kwargs):
        return self._flows.get(ticker.upper(), [])

    def get_recent_etf_aum(self, ticker, *, max_age):
        return self._aums.get(ticker.upper())

    def fetch_iv_ranks(self, tickers, *, max_age=None):
        return {t: self._iv_ranks[t] for t in tickers if t in self._iv_ranks}


def test_builds_a_row_per_ticker_with_all_three_legs():
    n = 200
    repo = FakeRepo(
        flows={
            "SOXX": _flows(
                n=n,
                start_close=300.0,
                end_close=527.0,
                flow_per_day=1e9,
                late_boost=1.4,
            ),
            "SPY": _flows(n=n, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"SOXX": Decimal("45064294868"), "SPY": Decimal("743252024000")},
        iv_ranks={"SOXX": 93.93, "SPY": 29.70},
    )
    as_of, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))

    assert as_of == date(2025, 7, 1) + timedelta(days=n - 1)
    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "SOXX"
    # Steady outperformance + steady inflow + a 64pt iv_rank spread.
    assert row.price.score is not None and row.price.score > 50.0
    assert row.flow.score == 100.0
    assert row.premium.score == pytest.approx(100.0)
    assert row.state == "CROWDED"


def test_short_history_yields_no_price_leg_but_keeps_flow():
    repo = FakeRepo(
        flows={
            "XLE": _flows(n=90, start_close=90.0, end_close=95.0, flow_per_day=1e6),
            "SPY": _flows(n=90, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"XLE": Decimal("59.4"), "SPY": Decimal("743.252024")},
        iv_ranks={"XLE": 65.16, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("XLE",))
    row = rows[0]
    # 90 sessions clears MIN_SESSIONS (84) but not the percentile floor.
    assert row.price.raw is not None
    assert row.price.score is None
    assert row.flow.score is not None
    assert row.premium.score is not None
    assert row.state is not None  # two legs is still a verdict


def test_aum_in_billions_is_normalized_before_dividing():
    """XLE's AUM arrives as 59.4 (billions). Without normalization the flow
    ratio is off by 1e9 and every SPDR sector ETF pins at 100."""
    repo = FakeRepo(
        flows={
            "XLE": _flows(n=200, start_close=90.0, end_close=95.0, flow_per_day=1e6),
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"XLE": Decimal("59.4"), "SPY": Decimal("743.252024")},
        iv_ranks={"XLE": 65.16, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("XLE",))
    # 21 sessions x $1M = $21M against $59.4B -> ~0.035%, nowhere near a band.
    assert rows[0].flow.raw == pytest.approx(0.035, abs=0.005)


def test_missing_flow_data_drops_the_ticker():
    repo = FakeRepo(
        flows={
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9, flow_per_day=1e7)
        },
        aums={"SPY": Decimal("743252024000")},
        iv_ranks={"SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("ARKK",))
    assert rows == []


def test_no_benchmark_data_yields_no_rows():
    repo = FakeRepo(flows={}, aums={}, iv_ranks={})
    as_of, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))
    assert as_of is None
    assert rows == []


def test_series_is_rebased_to_zero_at_the_window_start():
    repo = FakeRepo(
        flows={
            "SOXX": _flows(
                n=200,
                start_close=300.0,
                end_close=527.0,
                flow_per_day=1e9,
                late_boost=1.4,
            ),
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"SOXX": Decimal("45064294868"), "SPY": Decimal("743252024000")},
        iv_ranks={"SOXX": 93.93, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))
    row = rows[0]
    series = row.series
    # RETURN_WINDOW intervals == RETURN_WINDOW + 1 observations.
    assert len(series) == RETURN_WINDOW + 1
    assert series[0].etf_cum_return == pytest.approx(0.0, abs=1e-9)
    assert series[0].bench_cum_return == pytest.approx(0.0, abs=1e-9)
    assert series[-1].etf_cum_return > series[-1].bench_cum_return


def test_chart_endpoint_equals_the_scored_price_leg():
    """The drill-down must visualize the number in the price cell.

    Rebasing the chart one session later than _window_return scores is
    invisible by eye -- it shifts the endpoint by a fraction of a percent --
    so pin it.
    """
    repo = FakeRepo(
        flows={
            "SOXX": _flows(
                n=200,
                start_close=300.0,
                end_close=527.0,
                flow_per_day=1e9,
                late_boost=1.4,
            ),
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"SOXX": Decimal("45064294868"), "SPY": Decimal("743252024000")},
        iv_ranks={"SOXX": 93.93, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))
    row = rows[0]
    last = row.series[-1]
    assert last.etf_cum_return - last.bench_cum_return == pytest.approx(
        row.price.raw, abs=1e-9
    )
