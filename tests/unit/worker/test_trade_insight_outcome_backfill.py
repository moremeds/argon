from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from uw_scan.storage.trade_insight_outcomes_repository import PendingOutcomeAnalysis
from uw_scan.worker.jobs import trade_insight_outcome_backfill as job


class _FakeOutcomeRepo:
    def __init__(self, pending: list[PendingOutcomeAnalysis]) -> None:
        self.pending = pending
        self.upserts: list[dict] = []

    def fetch_pending_with_analysis(
        self, *, limit: int = job.INCREMENTAL_BATCH
    ) -> list[PendingOutcomeAnalysis]:
        return self.pending[:limit]

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)


def _pending(
    *,
    snapshot_date: date,
    ticker: str | None = "TSLA",
    outcome: dict | None = None,
) -> PendingOutcomeAnalysis:
    return PendingOutcomeAnalysis(
        analysis_id=uuid4(),
        snapshot_date=snapshot_date,
        ticker=ticker,
        provider="codex" if ticker is not None else None,
        prompt_version="trade-insights-ai-v5.3" if ticker is not None else None,
        outcome_jsonb=outcome or {},
    )


def test_score_pending_rows_batches_analysis_and_ohlc_reads_by_ticker(monkeypatch):
    repo = _FakeOutcomeRepo(
        [
            _pending(
                snapshot_date=date(2026, 5, 1),
                outcome={
                    "headline": {"directional_bias": "LONG_DELTA"},
                    "preferred_expression": {
                        "strike_role": {"target_level": "105"}
                    },
                },
            ),
            _pending(
                snapshot_date=date(2026, 5, 2),
                outcome={"headline": {"directional_bias": "WAIT"}},
            ),
        ]
    )
    forward_calls = []
    snapshot_calls = []

    def fake_forward_closes(conn, ticker, min_snapshot_date, max_snapshot_date):
        forward_calls.append((ticker, min_snapshot_date, max_snapshot_date))
        return [
            (date(2026, 5, 2), Decimal("101")),
            (date(2026, 5, 3), Decimal("106")),
            (date(2026, 5, 4), Decimal("108")),
        ]

    def fake_snapshot_closes(conn, ticker, snapshot_dates):
        snapshot_calls.append((ticker, tuple(snapshot_dates)))
        return {
            date(2026, 5, 1): Decimal("100"),
            date(2026, 5, 2): Decimal("101"),
        }

    monkeypatch.setattr(job, "_fetch_forward_closes_for_ticker", fake_forward_closes)
    monkeypatch.setattr(job, "_fetch_snapshot_closes", fake_snapshot_closes)

    scored = job._score_pending_rows(object(), repo)

    assert scored == 2
    assert forward_calls == [("TSLA", date(2026, 5, 1), date(2026, 5, 2))]
    assert snapshot_calls == [
        ("TSLA", (date(2026, 5, 1), date(2026, 5, 2)))
    ]
    assert [row["snapshot_close"] for row in repo.upserts] == [
        Decimal("100"),
        Decimal("101"),
    ]
    assert repo.upserts[0]["resolved_outcome"] == "target_hit"
    assert repo.upserts[1]["resolved_outcome"] == "pending"


def test_score_pending_rows_keeps_missing_analysis_pending(monkeypatch, caplog):
    repo = _FakeOutcomeRepo([_pending(snapshot_date=date(2026, 5, 1), ticker=None)])

    def fail_forward(*args, **kwargs):
        raise AssertionError("missing analyses must not fetch OHLC")

    monkeypatch.setattr(job, "_fetch_forward_closes_for_ticker", fail_forward)
    monkeypatch.setattr(job, "_fetch_snapshot_closes", fail_forward)

    scored = job._score_pending_rows(object(), repo)

    assert scored == 0
    assert repo.upserts == []
    assert "references missing analysis" in caplog.text
