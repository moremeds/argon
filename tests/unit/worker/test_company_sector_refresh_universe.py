"""company_sector_refresh unions the vendored S&P 500 list into its universe only when asked."""

from __future__ import annotations

import logging

import uw_scan.worker.jobs.company_sector_refresh as job
from uw_scan.sources.sp500_members import Sp500ListInvalid


class _FakeRepo:
    last: "_FakeRepo | None" = None

    def __init__(self, conn, *, schema: str = "uw_scan") -> None:
        self.extra_seen: tuple[str, ...] | None = None
        _FakeRepo.last = self

    def tickers_needing_fetch(self, limit: int, extra=()) -> list[str]:
        self.extra_seen = tuple(extra)
        return []

    def coverage(self) -> dict[str, int]:
        return {"universe": 0, "fetched": 0, "classified": 0}


def test_sp500_members_are_unioned_when_asked(monkeypatch):
    monkeypatch.setattr(job, "CompanySectorRepository", _FakeRepo)
    monkeypatch.setattr(job, "sp500_members", lambda: ("GE", "GOOGL", "PKG"))
    job.company_sector_refresh(conn=None, client=None, include_sp500=True)
    assert _FakeRepo.last.extra_seen == ("GE", "GOOGL", "PKG")


def test_invalid_vendored_list_falls_back_to_the_universe_and_says_so(
    monkeypatch, caplog
):
    def invalid():
        raise Sp500ListInvalid("449 tickers < 450")

    monkeypatch.setattr(job, "CompanySectorRepository", _FakeRepo)
    monkeypatch.setattr(job, "sp500_members", invalid)
    with caplog.at_level(logging.ERROR):
        job.company_sector_refresh(conn=None, client=None, include_sp500=True)
    assert _FakeRepo.last.extra_seen == ()
    assert "vendored sp500 list invalid" in caplog.text


def test_default_does_not_widen(monkeypatch):
    def must_not_read():
        raise AssertionError("the list must not be read when include_sp500 is False")

    monkeypatch.setattr(job, "CompanySectorRepository", _FakeRepo)
    monkeypatch.setattr(job, "sp500_members", must_not_read)
    job.company_sector_refresh(conn=None, client=None)
    assert _FakeRepo.last.extra_seen == ()
