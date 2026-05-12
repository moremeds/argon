"""Tests for `reports.scan.assemble_scan_report` using a fake repository.

The fake holds in-memory scan_universe + scan_results rows so we exercise the
ranking / top-pick logic without touching Postgres.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.reports.scan import assemble_scan_report


class _FakeRepo:
    def __init__(self, universe: list[dict], results: list[dict]) -> None:
        self._universe = universe
        self._results = results

    def fetch_scan_universe(self, run_id: int) -> list[dict]:
        assert run_id == 42
        return list(self._universe)

    def fetch_scan_results(self, run_id: int) -> list[dict]:
        assert run_id == 42
        # Repository implementation orders by score DESC, ticker ASC — replicate.
        return sorted(
            self._results,
            key=lambda r: (-r.get("score", Decimal("0")), r["ticker"]),
        )


def _result_row(
    ticker: str,
    score: Decimal,
    *,
    setup: str | None = "F",
    direction: str = "bull",
    iv_rank: Decimal | None = Decimal("75"),
    net_premium: Decimal | None = Decimal("100000000"),
) -> dict:
    return {
        "run_id": 42,
        "ticker": ticker,
        "market_date": date(2026, 5, 11),
        "setup_type": setup,
        "direction": direction,
        "score": score,
        "net_call_premium": Decimal("100000000"),
        "net_put_premium": Decimal("0"),
        "net_premium": net_premium,
        "bullish_premium": None,
        "bearish_premium": None,
        "call_premium": None,
        "put_premium": None,
        "put_call_ratio": None,
        "iv_rank": iv_rank,
        "volatility": None,
        "iv30d": None,
        "implied_move": None,
        "implied_move_perc": None,
        "gex_net_change": None,
        "gex_ratio": None,
        "variance_risk_premium": None,
        "total_open_interest": 1_000_000,
        "relative_volume": None,
        "next_earnings_date": None,
        "sector": "Technology",
        "marketcap": None,
        "signals_present": ["gex_oi_shift=0.05", "flow_polarization=$100M"],
        "confirmations": ["net premium = $100M (bull)", "iv_rank = 75"],
        "warnings": [],
        "notes": "Type F: multi-signal confluence",
    }


def test_assemble_scan_report_ranks_by_score_desc():
    """Three results, scores 4.5 / 2.1 / 3.7 → ordering AAA-3.7 then HHH-4.5? No.
    Repository orders DESC: HHH (4.5), AAA (3.7), BBB (2.1)."""
    universe = [
        {"ticker": "AAA", "source": "test"},
        {"ticker": "BBB", "source": "test"},
        {"ticker": "HHH", "source": "test"},
        {"ticker": "ZZZ", "source": "test"},  # in universe but no result
    ]
    results = [
        _result_row("AAA", Decimal("3.7")),
        _result_row("BBB", Decimal("2.1"), setup="C"),
        _result_row("HHH", Decimal("4.5")),
    ]
    repo = _FakeRepo(universe, results)

    report = assemble_scan_report(42, repo)

    assert report.run_id == 42
    assert report.universe_size == 4
    assert report.universe_returned == 3
    assert [r.ticker for r in report.results] == ["HHH", "AAA", "BBB"]
    assert report.top_pick == "HHH"
    assert report.dropped_tickers == ["ZZZ"]
    assert report.scan_date == date(2026, 5, 11)


def test_assemble_scan_report_top_pick_is_first():
    universe = [{"ticker": "AAA", "source": "test"}]
    results = [_result_row("AAA", Decimal("4.0"))]
    report = assemble_scan_report(42, _FakeRepo(universe, results))
    assert report.top_pick == "AAA"
    assert len(report.results) == 1
    assert report.results[0].score == Decimal("4.0")
    assert report.results[0].setup_type == "F"
    assert report.results[0].confirmations == [
        "net premium = $100M (bull)",
        "iv_rank = 75",
    ]


def test_assemble_scan_report_empty_results():
    universe = [{"ticker": "AAA", "source": "test"}]
    report = assemble_scan_report(42, _FakeRepo(universe, []))
    assert report.top_pick is None
    assert report.results == []
    assert report.universe_size == 1
    assert report.universe_returned == 0
    assert report.dropped_tickers == ["AAA"]


def test_assemble_scan_report_signals_present_passthrough():
    universe = [{"ticker": "AAA", "source": "test"}]
    results = [_result_row("AAA", Decimal("3.0"))]
    report = assemble_scan_report(42, _FakeRepo(universe, results))
    assert report.results[0].signals_present == [
        "gex_oi_shift=0.05",
        "flow_polarization=$100M",
    ]
