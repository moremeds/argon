"""sector_rs_daily job: membership, sources, refusals. All I/O is stubbed.

Closes come from Task 2's frozen REAL fixture (apex adjusted, as-of
2026-09-18). The S&P list (monkeypatched `sp500_members`), the sector map and
the chain map are stubs. GE's missing sector is a labelled test double for an
unclassified member.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import uw_scan.worker.jobs.sector_rs_daily as job

from uw_scan.reports import sector_rs
from uw_scan.sources.sp500_members import Sp500ListInvalid
from uw_scan.storage.rows import DailyOhlcRow

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "fixtures"
    / "sector_rs_closes_2026-09-18.json"
)
FRI = date(2026, 9, 18)


def _fixture() -> dict[str, dict[date, float]]:
    raw = json.loads(_FIXTURE.read_text())
    return {
        s: {date.fromisoformat(d): float(c) for d, c in rows}
        for s, rows in raw["closes"].items()
    }


def _fetch_closes(omit: tuple[str, ...] = ()):
    data = _fixture()

    def fetch(symbols, *, start, end):
        return {
            s: {d: c for d, c in data[s].items() if start <= d <= end}
            for s in symbols
            if s in data and s not in omit
        }

    return fetch


class _Store:
    rows: list = []

    def __init__(self, conn, *, schema="uw_scan"):
        pass

    def upsert_rows(self, rows):
        _Store.rows.extend(rows)
        return len(rows)


class _Sectors:
    def __init__(self, conn, *, schema="uw_scan"):
        pass

    def sectors_for(self, tickers):
        known = {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "NVDA": "Technology",
            "GE": None,
        }
        return {t: known[t] for t in tickers if t in known}


def _chains(mapping: dict[str, list[str]]):
    class _Chains:
        def __init__(self, conn, schema="uw_scan"):
            pass

        def counts_by_chain(self):
            return {k: len(v) for k, v in mapping.items()}

        def tickers_in_chain(self, chain):
            return mapping[chain]

    return _Chains


class _Repo:
    conn = None

    def __init__(self, ohlc: dict[str, dict[date, float]] | None = None):
        self._ohlc = ohlc or {}

    def list_daily_ohlc(self, ticker, *, limit=30):
        series = self._ohlc.get(ticker, {})
        stamp = datetime(2026, 9, 26, tzinfo=timezone.utc)
        return [
            DailyOhlcRow(
                ticker, d, None, None, None, Decimal(str(c)), None, "massive.com", stamp
            )
            for d, c in sorted(series.items(), reverse=True)[:limit]
        ]


@pytest.fixture
def wired(monkeypatch):
    _Store.rows = []
    # One session per run keeps the per-test counts readable; the trailing-week
    # recompute has its own test below.
    monkeypatch.setattr(job, "NIGHTLY_RECOMPUTE_DAYS", 1)
    monkeypatch.setattr(job, "SectorRsRepository", _Store)
    monkeypatch.setattr(job, "CompanySectorRepository", _Sectors)
    monkeypatch.setattr(job, "WatchlistChainRepository", _chains({}))
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL", "MSFT", "NVDA"))
    calls: list[str] = []
    real = sector_rs.compute_group_rows

    def spy_compute(as_of, groups, closes, **kw):
        calls.append(groups[0].kind)
        return real(as_of, groups, closes, **kw)

    monkeypatch.setattr(job, "compute_group_rows", spy_compute)
    return calls


def _run(as_of=FRI, **kw):
    kw.setdefault("repo", _Repo())
    kw.setdefault("fetch_closes", _fetch_closes())
    return job.sector_rs_daily(schema="uw_scan", as_of=as_of, **kw)


def test_writes_11_gics_rows_and_zero_chain_rows_on_empty_watchlist_chain(
    wired, monkeypatch
):
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL", "GE", "MSFT", "NVDA"))
    c = _run()
    assert c["gics_rows"] == 11 and c["chain_rows"] == 0 and c["rows"] == 11
    assert c["unclassified"] == 1  # GE: asked, no sector
    assert wired == [
        "gics"
    ]  # compute once for gics; the empty chain kind is not computed
    tech = next(r for r in _Store.rows if r.group_key == "Technology")
    assert (tech.rs_symbol, tech.n_members, tech.degraded, tech.source) == (
        "XLK",
        3,
        False,
        "apex",
    )


def test_other_ten_sectors_write_null_rs_rows_when_their_etf_is_absent(wired):
    _run()
    others = [r for r in _Store.rows if r.group_key != "Technology"]
    assert len(others) == 10
    assert all(r.degraded and r.n_members == 0 for r in others)
    assert all(v is None for r in others for v in r.rs.values())


def test_compute_runs_once_per_group_kind(wired, monkeypatch):
    monkeypatch.setattr(
        job, "WatchlistChainRepository", _chains({"Semi-Logic": ["NVDA"]})
    )
    c = _run()
    assert wired == ["gics", "chain"]
    assert c["chain_rows"] == 1
    (chain,) = [r for r in _Store.rows if r.group_kind == "chain"]
    assert (chain.weighting, chain.rs_symbol, chain.n_priced) == ("equal", None, 1)


def test_saturday_as_of_writes_friday_rows(wired):
    _run(as_of=date(2026, 9, 19))
    assert {r.as_of for r in _Store.rows} == {FRI}


def test_spy_missing_everywhere_aborts_without_writing(wired):
    with pytest.raises(RuntimeError, match="SPY"):
        _run(fetch_closes=_fetch_closes(omit=("SPY",)))
    assert _Store.rows == []


def test_spy_too_short_for_earliest_session_aborts_without_writing(wired):
    with pytest.raises(ValueError, match="12m"):
        job.run_sector_rs(
            repo=_Repo(),
            schema="uw_scan",
            dates=[date(2025, 10, 1), FRI],
            fetch_closes=_fetch_closes(),
        )
    assert _Store.rows == []


def test_spy_from_daily_ohlc_tags_every_row(wired):
    c = _run(
        repo=_Repo(ohlc={"SPY": _fixture()["SPY"]}),
        fetch_closes=_fetch_closes(omit=("SPY",)),
    )
    assert c["daily_ohlc_rows"] == 11
    assert {r.source for r in _Store.rows} == {"daily_ohlc"}


def test_invalid_vendored_list_aborts_gics_with_error_and_chain_still_writes(
    wired, monkeypatch, caplog
):
    def invalid():
        raise Sp500ListInvalid("449 tickers < 450")

    monkeypatch.setattr(job, "sp500_members", invalid)
    monkeypatch.setattr(
        job, "WatchlistChainRepository", _chains({"Semi-Logic": ["NVDA"]})
    )
    with caplog.at_level(logging.ERROR, logger=job.__name__):
        c = _run()
    assert c["membership_invalid"] == 1
    assert c["gics_rows"] == 0 and c["chain_rows"] == 1
    assert {r.group_kind for r in _Store.rows} == {"chain"}
    assert "vendored sp500 list invalid" in caplog.text


def test_counters_are_logged(wired, monkeypatch, caplog):
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL",))
    with caplog.at_level(logging.INFO, logger=job.__name__):
        _run()
    assert "sector_rs {" in caplog.text and "'gics_rows': 11" in caplog.text
    assert "n_priced 1 / n_members 1" in caplog.text
    assert "survivorship" in caplog.text


def test_build_gics_groups_keeps_the_eleven_and_counts_the_rest():
    groups, unclassified = job.build_gics_groups(
        ["aapl", "GE", "PKG"], {"AAPL": "Technology", "GE": None}
    )
    assert [g.key for g in groups] == list(job.SPDR_SECTOR_ETFS)
    assert next(g for g in groups if g.key == "Technology").members == ("AAPL",)
    assert unclassified == 2  # GE NULL sector, PKG never asked


def test_nightly_recomputes_the_trailing_week_so_a_missed_session_heals(
    wired, monkeypatch
):
    monkeypatch.setattr(job, "NIGHTLY_RECOMPUTE_DAYS", 7)
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL", "MSFT", "NVDA"))
    c = _run()  # Fri 2026-09-18 back to Sat 09-12, which snaps to Fri 09-11
    assert c["sessions"] == 6
    assert c["gics_rows"] == 6 * 11
    assert {r.as_of for r in _Store.rows} == {
        date(2026, 9, 11), *(date(2026, 9, d) for d in range(14, 19))
    }
