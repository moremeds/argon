"""The pipeline-replay adapter heals ~11 tables per call, so it must fan in.

The healer dispatches per (dataset, ticker, date). Registering the replay under
every table it writes would call run_single_stock once per dataset — 11x the UW
spend for identical rows. The adapter therefore deduplicates per (ticker, date)
within a single heal run.
"""

from datetime import date

from uw_scan.worker.jobs import data_gap_adapters as A


class _Repo:
    def __init__(self):
        self.commits = 0

    def conn(self):  # pragma: no cover - not used
        raise AssertionError


def _ctx(monkeypatch, calls):
    def fake_run_single_stock(ticker, client, repo, market_date=None):
        calls.append((ticker, market_date))

    monkeypatch.setattr(A, "_replay_run_single_stock", fake_run_single_stock)
    ctx = A.HealContext(
        repo=_Repo(),
        gap=object(),
        schema="uw_scan",
        today=date(2026, 8, 16),
        budget=A.RequestBudget(uw_cap=None),
        settings=object(),
    )
    monkeypatch.setattr(A.HealContext, "uw_client", lambda self: object())
    return ctx


def test_replay_runs_once_per_ticker_date_across_datasets(monkeypatch):
    calls: list = []
    ctx = _ctx(monkeypatch, calls)

    # same (ticker, date) requested by three different datasets
    n1 = A._run_pipeline_replay(ctx, "AAPL", date(2026, 8, 12))
    n2 = A._run_pipeline_replay(ctx, "AAPL", date(2026, 8, 12))
    n3 = A._run_pipeline_replay(ctx, "AAPL", date(2026, 8, 12))

    assert calls == [("AAPL", date(2026, 8, 12))], "must fan in to ONE UW replay"
    assert n1 == 1 and n2 == 1 and n3 == 1, "each dataset still reports covered"


def test_replay_reruns_for_a_different_ticker_or_date(monkeypatch):
    calls: list = []
    ctx = _ctx(monkeypatch, calls)

    A._run_pipeline_replay(ctx, "AAPL", date(2026, 8, 12))
    A._run_pipeline_replay(ctx, "AAPL", date(2026, 8, 13))
    A._run_pipeline_replay(ctx, "MSFT", date(2026, 8, 12))

    assert len(calls) == 3


def test_every_replay_dataset_is_declared_replay_safe():
    """A dataset wired to the replay adapter but listed in REPLAY_REFUSED would
    silently fabricate. Keep the two lists in agreement."""
    from uw_scan.pipeline_replay_policy import REPLAY_REFUSED

    from uw_scan.reports.data_gap_healer import REGISTRY

    replay_tables = [
        e.table_name for e in REGISTRY if e.healer_adapter == "pipeline_replay"
    ]
    assert replay_tables, "the replay adapter must be registered for something"
    for t in replay_tables:
        assert t not in REPLAY_REFUSED, f"{t} is refused but wired to the replay"
