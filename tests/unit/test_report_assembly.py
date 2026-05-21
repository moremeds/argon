"""Report assembly unit test using an in-memory stand-in repo.

The repo is a deliberately-minimal fake (NOT a fake-cursor — this is at the higher
Repository abstraction level, which the integration test covers with a real DB).
We test that assemble_single_stock_report wires sections together correctly.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from uw_scan.reports.single_stock import assemble_single_stock_report


class _StubCursor:
    """No-op cursor: SET search_path becomes a no-op; option_intraday_buckets
    fetches return nothing so the assembler emits zero-volume profiles."""

    description: list = []

    def execute(self, *args, **kwargs) -> None:
        return None

    def fetchall(self) -> list:
        return []

    def __enter__(self) -> _StubCursor:
        return self

    def __exit__(self, *args) -> bool:
        return False


class _StubConn:
    def cursor(self) -> _StubCursor:
        return _StubCursor()


class _StubRepo:
    """Minimal stand-in implementing the Repository methods used by report assembly."""

    # Surface used by the new OptionIntradayBucketRepository code path in
    # the assembler. We don't exercise intraday content here — the cards/
    # unit suite already covers the deriver against fixture buckets.
    conn: _StubConn
    _schema: str

    def __init__(self) -> None:
        self.fetched: list[str] = []
        self.conn = _StubConn()
        self._schema = "uw_scan"

    def fetch_flow_alerts_for_ticker(self, run_id: int, ticker: str) -> list[dict]:
        self.fetched.append("flow")
        return [
            {
                "alert_id": "abc-1",
                "ticker": ticker,
                "option_chain": "TSLA260515C00440000",
                "expiry": _date(2026, 5, 15),
                "strike": Decimal("440"),
                "option_type": "call",
                "price": Decimal("2.21"),
                "underlying_price": Decimal("440.05"),
                "total_size": 100,
                "total_premium": Decimal("22000"),
                "total_ask_side_prem": Decimal("15000"),
                "total_bid_side_prem": Decimal("7000"),
                "volume": 200,
                "open_interest": 5000,
                "volume_oi_ratio": Decimal("0.04"),
                "has_sweep": True,
                "has_floor": False,
                "has_multileg": False,
                "all_opening_trades": False,
                "iv_start": Decimal("0.5"),
                "iv_end": Decimal("0.6"),
                "alert_rule": "RepeatedHits",
                "rule_id": "r-1",
                "sector": "Technology",
                "issue_type": "Common Stock",
                "next_earnings_date": _date(2026, 7, 1),
                "created_at": datetime(2026, 5, 11, 17, 0, 0),
            },
        ]

    def fetch_flow_alerts_daily_baseline(
        self, run_id: int, ticker: str, lookback_days: int = 30
    ) -> dict:
        self.fetched.append("flow_baseline")
        return {
            "alert_count": 100,
            "alert_count_is_limited": True,
            "top_alert_rule": "RepeatedHits",
            "avg_30d_alert_count": Decimal("35.50"),
            "flow_count_vs_30d_avg": Decimal("2.8169"),
            "baseline_days": 20,
        }

    def fetch_max_pain_rows(self, run_id: int, ticker: str) -> list[dict]:
        self.fetched.append("max_pain")
        return [
            {
                "expiry": _date(2026, 5, 15),
                "max_pain": Decimal("440"),
                "close": Decimal("440.05"),
                "open": Decimal("438.00"),
                "next_upper_strike": Decimal("445"),
                "next_lower_strike": Decimal("435"),
            },
        ]

    def fetch_exposures_aggregate(self, run_id: int, ticker: str) -> dict:
        return {
            "total_call_gex": Decimal("1000000"),
            "total_put_gex": Decimal("-500000"),
            "total_call_dex": Decimal("50000"),
            "total_put_dex": Decimal("-30000"),
        }

    def fetch_strike_exposures(self, run_id: int, ticker: str) -> list[dict]:
        return []

    def fetch_exposures_summary(self, run_id: int, ticker: str) -> list[dict]:
        return []

    def fetch_top_oi_strikes(self, ticker: str, limit: int = 5):
        return [Decimal("440"), Decimal("450")], [Decimal("430"), Decimal("420")]

    def fetch_iv_rank_latest(self, ticker: str) -> dict:
        return {
            "market_date": _date(2026, 5, 11),
            "close": Decimal("440"),
            "volatility": Decimal("0.5"),
            "iv_rank_1y": Decimal("75"),
            "updated_at_src": datetime(2026, 5, 11, 22, 0, 0),
        }

    def fetch_volatility_stats_latest(self, ticker: str) -> dict:
        return {
            "market_date": _date(2026, 5, 11),
            "iv": Decimal("0.5"),
            "iv_low": Decimal("0.3"),
            "iv_high": Decimal("0.8"),
            "iv_rank": Decimal("75"),
            "rv": Decimal("0.4"),
            "rv_low": Decimal("0.2"),
            "rv_high": Decimal("0.7"),
        }

    def fetch_realized_vol_latest(self, ticker: str) -> dict:
        return {
            "market_date": _date(2026, 5, 11),
            "price": Decimal("440.05"),
            "implied_volatility": Decimal("0.5"),
            "realized_volatility": Decimal("0.4"),
        }

    def fetch_iv_term_rows(self, run_id: int, ticker: str) -> list[dict]:
        return [
            {
                "expiry": _date(2026, 5, 15),
                "dte": 4,
                "volatility": Decimal("0.6"),
                "implied_move": Decimal("4"),
                "implied_move_perc": Decimal("0.01"),
            },
            {
                "expiry": _date(2026, 6, 19),
                "dte": 39,
                "volatility": Decimal("0.45"),
                "implied_move": Decimal("10"),
                "implied_move_perc": Decimal("0.02"),
            },
        ]

    def fetch_interpolated_iv_30d(self, run_id: int, ticker: str) -> dict:
        return {
            "days": 30,
            "percentile": Decimal("0.7"),
            "volatility": Decimal("0.48"),
            "implied_move_perc": Decimal("0.05"),
        }

    def fetch_skew_latest(self, ticker: str) -> dict:
        return {
            "market_date": _date(2026, 5, 11),
            "delta": 25,
            "expiry": _date(2026, 5, 15),
            "risk_reversal": Decimal("-0.05"),
        }

    def fetch_oi_change_top(self, run_id: int, limit: int = 10) -> list[dict]:
        return [
            {
                "underlying_symbol": "TSLA",
                "option_symbol": "TSLA260515C00440000",
                "curr_date": _date(2026, 5, 11),
                "last_date": _date(2026, 5, 8),
                "curr_oi": 5000,
                "last_oi": 1000,
                "oi_diff_plain": 4000,
                "oi_change": Decimal("4.0"),
                "volume": 6000,
                "trades": 50,
                "avg_price": Decimal("2.0"),
                "last_fill": Decimal("2.1"),
                "days_of_oi_increases": 3,
                "days_of_vol_greater_than_oi": 1,
                "percentage_of_total": Decimal("0.05"),
                "rnk": 1,
            },
        ]

    def fetch_dark_pool_summary(self, run_id: int) -> tuple[int, Decimal]:
        return 100, Decimal("100000000")

    def fetch_short_interest_snapshot(self, run_id: int) -> dict:
        return {
            "ticker": "TSLA",
            "name": "TESLA INC",
            "snapshot_at": datetime(2026, 5, 11, 12, 0, 0),
            "short_shares_available": 10_000_000,
            "fee_rate": Decimal("0.25"),
            "rebate_rate": Decimal("3.38"),
        }

    def fetch_option_contracts(self, run_id: int, ticker: str) -> list[dict]:
        return []

    def get_strike_gex_curve(self, run_id: int) -> list[dict]:
        return []

    def get_aggregates(self, run_id: int):
        return None

    def get_options_timeline(self, ticker: str, lookback_days: int = 180):
        from uw_scan.models import OptionsDailyRow

        return [
            OptionsDailyRow(
                date=_date(2026, 5, 11),
                call_volume=900,
                put_volume=300,
                avg_30_day_call_volume=Decimal("950.5"),
            ),
            OptionsDailyRow(
                date=_date(2026, 5, 12),
                call_volume=1_000,
                put_volume=400,
                avg_30_day_call_volume=Decimal("960.0"),
            ),
        ]

    def get_option_chain_per_strike(self, ticker: str):
        from uw_scan.models import OptionChainPerStrikeRow

        return [
            OptionChainPerStrikeRow(
                expiry=_date(2026, 6, 19),
                strike=Decimal("440"),
                call_volume=500,
                put_volume=300,
                call_oi=10_000,
                put_oi=8_000,
            )
        ]


def test_assemble_single_stock_report_populates_sections():
    repo = _StubRepo()
    report = assemble_single_stock_report("TSLA", run_id=42, repo=repo)  # type: ignore[arg-type]

    assert report.ticker == "TSLA"
    assert report.run_id == 42

    # Flow section
    assert report.flow.flow_count == 1
    assert report.flow.flow_count_is_limited is True
    assert report.flow.flow_count_30d_avg == Decimal("35.50")
    assert report.flow.flow_count_vs_30d_avg == Decimal("2.8169")
    assert report.flow.flow_count_30d_days == 20
    assert report.flow.top_alert_rule == "RepeatedHits"
    assert report.flow.bull_premium == Decimal("22000")
    assert report.flow.bear_premium == Decimal("0")
    assert report.flow.net_premium == Decimal("22000")

    # Market structure
    assert report.market_structure.spot == Decimal("440.05")
    assert report.market_structure.max_pain == Decimal("440")
    assert report.market_structure.total_call_gex == Decimal("1000000")
    assert report.market_structure.top_call_oi_strikes == [
        Decimal("440"),
        Decimal("450"),
    ]

    # Volatility
    assert report.volatility.iv == Decimal("0.5")
    assert report.volatility.iv_rank == Decimal("75")
    assert report.volatility.iv_rank_1y == Decimal("75")
    assert report.volatility.iv_percentile_30d == Decimal("0.7")
    assert report.volatility.skew_25d == Decimal("-0.05")
    assert len(report.volatility.term_dte_to_iv) == 2

    # VRP — IV 0.5 vs RV 0.4 → vrp 0.1 → rich
    assert report.vrp.vrp == Decimal("0.1")
    assert report.vrp.signal == "rich"

    # Dark pool + short data
    assert report.dark_pool_print_count == 100
    assert report.dark_pool_notional == Decimal("100000000")
    assert report.short_data is not None
    assert report.short_data.short_shares_available == 10_000_000

    # OI change
    assert len(report.oi_change_top) == 1
    assert report.oi_change_top[0].option_symbol == "TSLA260515C00440000"

    # Setup not yet classified at assembly time
    assert report.setup is None
    assert report.trade_plan is None

    # Short-Int field note from spec
    assert "n/a" in report.short_int_note

    # Flow tab merge — new sections from the assembler
    assert len(report.options_timeline) == 2
    assert report.options_timeline[-1].call_volume == 1_000
    assert report.options_timeline[-1].avg_30_day_call_volume == Decimal("960.0")
    assert len(report.option_chain_per_strike) == 1
    assert report.option_chain_per_strike[0].call_oi == 10_000
    # next_earnings_date promoted from the flow alert
    assert report.next_earnings_date == _date(2026, 7, 1)
