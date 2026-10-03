"""regime_fred_ingest_job must raise when every series fails (rule 3a), so the
scheduler's job_failures streak sees a dead feed instead of a clean run."""

from __future__ import annotations

import pytest

import uw_scan.worker.jobs.regime_jobs as regime_jobs


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def commit(self) -> None:
        pass


class _Repo:
    def __init__(self, *_a, **_k) -> None:
        pass

    def insert_macro_series_daily_rows(self, rows, **_k) -> int:
        return len(rows)


def _fred(fail: set[str]):
    class _Fred:
        def __init__(self, *_a, **_k) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def fetch_series(self, sid, start):
            if sid in fail:
                raise RuntimeError("403")
            return []

    return _Fred


@pytest.fixture
def _patched(monkeypatch):
    monkeypatch.setattr(regime_jobs.psycopg, "connect", lambda *_a, **_k: _Conn())
    monkeypatch.setattr(regime_jobs, "Repository", _Repo)
    return monkeypatch


def test_raises_when_every_series_fails(_patched):
    _patched.setattr(regime_jobs, "FredProvider", _fred({"NFCI", "ANFCI", "USREC"}))
    with pytest.raises(RuntimeError, match="all 3 series failed"):
        regime_jobs.regime_fred_ingest_job(dsn="x")


def test_partial_failure_and_no_new_rows_still_succeed(_patched):
    # An unchanged week inserts 0 rows; that is success, not a dead feed.
    _patched.setattr(regime_jobs, "FredProvider", _fred({"NFCI"}))
    assert regime_jobs.regime_fred_ingest_job(dsn="x") == {
        "NFCI": 0,
        "ANFCI": 0,
        "USREC": 0,
    }
