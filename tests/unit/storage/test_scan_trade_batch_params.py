from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan import models
from uw_scan.storage.scan_results import (
    _ScanResultsMixin,
    _scan_result_params,
    _scan_universe_params,
)
from uw_scan.storage.trade_insights_ai import (
    _TradeInsightsAiMixin,
    _trade_insight_candidate_params,
)


class _FakeCursor:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, object | None]] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql: str, params: object | None = None) -> None:
        self.execute_calls.append((sql, params))

    def executemany(self, sql: str, params: list[tuple[object, ...]]) -> None:
        self.executemany_calls.append((sql, params))


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


class _FakeRepository(_ScanResultsMixin, _TradeInsightsAiMixin):
    def __init__(self) -> None:
        self._conn = _FakeConnection()
        self._schema = "uw_scan"

    @property
    def fake_cursor(self) -> _FakeCursor:
        return self._conn.cursor_obj


def _sample_scan_results() -> list[models.ScanTickerResult]:
    return [
        models.ScanTickerResult(
            ticker="TSLA",
            setup_type="F",
            direction="bullish",
            score=Decimal("8.5"),
            net_premium=Decimal("100000"),
            signals_present=["deep_conviction_flow"],
            confirmations=["regime"],
            warnings=[],
            screener_row=models.BulkScreenerRow(
                ticker="TSLA",
                date=date(2026, 5, 18),
                volatility=Decimal("0.42"),
                bullish_premium=Decimal("120000"),
                marketcap=Decimal("750000000000"),
            ),
        ),
        models.ScanTickerResult(ticker="NVDA", score=Decimal("7.0")),
    ]


def _sample_candidates() -> list[dict[str, object]]:
    return [
        {
            "idea_id": "bull_call_spread",
            "structure": "CALL_DEBIT_SPREAD",
            "expression_type": "defined_risk",
            "rank": 1,
            "status": "preferred",
            "risk_flags": ["defined_risk"],
            "legs": [{"right": "call", "strike": 450}],
        },
        {
            "idea_id": "put_credit_spread",
            "structure": "PUT_CREDIT_SPREAD",
            "rank": 2,
            "status": "candidate",
        },
    ]


def test_scan_result_param_builders_preserve_shape() -> None:
    assert _scan_universe_params(11, ["tsla", "NVDA"], "watchlist") == [
        (11, "TSLA", "watchlist"),
        (11, "NVDA", "watchlist"),
    ]

    params = _scan_result_params(12, _sample_scan_results())
    assert len(params) == 2
    first = params[0]
    assert first[0] == 12
    assert first[1] == "TSLA"
    assert first[2] == date(2026, 5, 18)
    assert first[5] == Decimal("8.5")
    assert first[9] == Decimal("120000")
    assert first[27] == ["deep_conviction_flow"]
    assert first[28] == ["regime"]


def test_trade_insight_candidate_params_preserve_shape() -> None:
    params = _trade_insight_candidate_params(
        snapshot_id=21,
        run_id=22,
        ticker="tsla",
        candidates=_sample_candidates(),
    )
    assert len(params) == 2
    first = params[0]
    assert first[:8] == (
        21,
        "bull_call_spread",
        "TSLA",
        22,
        "CALL_DEBIT_SPREAD",
        "defined_risk",
        1,
        "preferred",
    )
    assert first[12] == ["defined_risk"]


def test_scan_and_trade_batch_writers_use_executemany() -> None:
    repo = _FakeRepository()
    assert repo.insert_scan_universe(31, ["tsla", "nvda"], source="watchlist") == 2
    assert repo.insert_scan_results(32, _sample_scan_results()) == 2
    assert (
        repo.replace_trade_insight_candidates(
            snapshot_id=33,
            run_id=34,
            ticker="tsla",
            candidates=_sample_candidates(),
        )
        == 2
    )

    assert len(repo.fake_cursor.executemany_calls) == 3
    assert [len(call[1]) for call in repo.fake_cursor.executemany_calls] == [2, 2, 2]
    assert len(repo.fake_cursor.execute_calls) == 1
