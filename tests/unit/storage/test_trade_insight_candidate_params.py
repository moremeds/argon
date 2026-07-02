from __future__ import annotations

from uw_scan.storage.trade_insights_ai import (
    _trade_insight_candidate_params,
    _TradeInsightsAiMixin,
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


class _FakeRepository(_TradeInsightsAiMixin):
    def __init__(self) -> None:
        self._conn = _FakeConnection()
        self._schema = "uw_scan"

    @property
    def fake_cursor(self) -> _FakeCursor:
        return self._conn.cursor_obj


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


def test_trade_batch_writer_uses_executemany() -> None:
    repo = _FakeRepository()
    assert (
        repo.replace_trade_insight_candidates(
            snapshot_id=33,
            run_id=34,
            ticker="tsla",
            candidates=_sample_candidates(),
        )
        == 2
    )

    assert len(repo.fake_cursor.executemany_calls) == 1
    assert [len(call[1]) for call in repo.fake_cursor.executemany_calls] == [2]
    assert len(repo.fake_cursor.execute_calls) == 1
