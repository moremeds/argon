"""The monthly sweep's scheduler closure must actually call `persist_unknown_statements`.

Review fix (round 1): `fundamental_ingest_daily.py`'s own `targets` can only ever be
tickers the classified calendar just listed — a ticker UW never lists in either
`premarket`/`afterhours` slot (the ~2% `report_time: "unknown"` population spec §5-i
exists for) can never reach `fundamental_ingest` through the DAILY job, so it can
never appear in that job's `new_filings`. The monthly sweep (`scheduler.py`'s
`_fundamental_ingest`, which ingests the whole tier unfiltered by calendar) is the
ONLY caller that can ever hand `persist_unknown_statements` such a ticker — this test
proves the scheduler closure actually wires that call, not just that
`persist_unknown_statements` works in isolation (already covered by
`test_fundamental_ingest_daily.py`).

`_repo`/`_external_api_recorder`/`_uw_client` are monkeypatched to fakes so this stays
a pure-mock unit test — no DB, no network, matching `test_scheduler_registration.py`'s
existing style for this module.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest

import uw_scan.storage.earnings_calendar as calendar_storage
import uw_scan.worker.jobs.fundamental_ingest as ingest_mod
import uw_scan.worker.scheduler as scheduler

# Real-shaped fixture ticker, absent from both classified calendar slots — the exact
# population documented in `sources/earnings_calendar.py` and verified in
# docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md F4.
ISRG_FILING_DATE = date(2026, 7, 16)


class _FakeCalendarRepo:
    """No pre-existing calendar row for ISRG at any date — it is absent from both
    slots, by construction of this test. Records every `upsert_rows` call."""

    def __init__(self, conn, schema):
        self.schema = schema
        self.upserts: list[dict] = []

    def next_prints(self, *, on_or_after, tickers=None):
        return []

    def upsert_rows(self, rows):
        rows = list(rows)
        self.upserts.extend(rows)
        return len(rows)


def _capture_fundamental_ingest_func(monkeypatch, **env) -> object:
    """Registers the real `scheduler.main()` wiring against a fake APScheduler that
    records the `func` passed to `add_job` for `id="fundamental_ingest"`, then aborts
    before `start()` — mirrors `test_scheduler_registration.py`'s harness, extended to
    also capture `func` (that file only ever needed `id`)."""
    captured: dict[str, object] = {}

    class _StopStart(Exception):
        pass

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            if kwargs.get("id") == "fundamental_ingest" and args:
                captured["func"] = args[0]

        def start(self) -> None:
            raise _StopStart

        def shutdown(self, *_a, **_k) -> None:
            pass

    class _FakeSignal:
        SIGTERM = 15
        SIGINT = 2

        def signal(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(_StopStart):
        scheduler.main()

    assert "func" in captured, "fundamental_ingest was not registered under this env"
    return captured["func"]


def test_the_monthly_sweep_lands_statement_obs_for_a_calendar_invisible_name(
    monkeypatch,
):
    def fake_fundamental_ingest(*, conn, client, schema):
        return {
            "tickers": 1,
            "inserted": 1,
            "touched": 0,
            "violations": 0,
            "failed": 0,
            "filing_date_tolerance": 0,
            "availability_claims": 1,
            # ISRG landed a new statement this run; it is absent from both calendar
            # slots (see _FakeCalendarRepo.next_prints returning nothing for it).
            "new_filings": [
                {"ticker": "ISRG", "filing_published_at": ISRG_FILING_DATE}
            ],
        }

    created_repos: list[_FakeCalendarRepo] = []

    def fake_calendar_repo_factory(conn, schema):
        repo = _FakeCalendarRepo(conn, schema)
        created_repos.append(repo)
        return repo

    monkeypatch.setattr(ingest_mod, "fundamental_ingest", fake_fundamental_ingest)
    monkeypatch.setattr(
        calendar_storage, "EarningsCalendarRepository", fake_calendar_repo_factory
    )

    @contextmanager
    def fake_repo(settings):
        class _Repo:
            conn = object()

        yield _Repo()

    @contextmanager
    def fake_recorder(settings):
        yield object()

    class _FakeUwClient:
        """`_uw_client(...)` is used as `with _uw_client(...) as uw:` directly
        (the real `UwClient` is its own context manager) — not `@contextmanager`."""

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(scheduler, "_repo", fake_repo)
    monkeypatch.setattr(scheduler, "_external_api_recorder", fake_recorder)
    monkeypatch.setattr(scheduler, "_uw_client", lambda *a, **k: _FakeUwClient())

    func = _capture_fundamental_ingest_func(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_INGEST_ENABLED="true",
    )

    func()  # invoke the registered closure exactly as APScheduler would

    assert len(created_repos) == 1, (
        "the closure must construct exactly one calendar repo"
    )
    statement_obs_rows = [
        row for row in created_repos[0].upserts if row["source"] == "statement_obs"
    ]
    assert statement_obs_rows == [
        {
            "ticker": "ISRG",
            "report_date": ISRG_FILING_DATE,
            "session": None,
            "source": "statement_obs",
        }
    ]
