"""capture_dark_lit_for pages a ticker-day back to its first print.

The stub serves a synthetic print log with UW's measured semantics (2026-10-05
probe, NVDA 2026-09-15): newest first, ``limit`` per page, ``older_than``
strictly older, whole-second timestamps shared by several prints, and a
``date`` window that also carries the prior session's after-hours prints.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from uw_scan.models.uw_alpha import DarkLitPrint
from uw_scan.worker.jobs import uw_alpha_capture as cap

MD = date(2026, 9, 15)


def _log(n_seconds: int, per_second: int, *, start: datetime) -> list[DarkLitPrint]:
    out = []
    for s in range(n_seconds):
        ts = start - timedelta(seconds=s)
        for k in range(per_second):
            out.append(
                DarkLitPrint(
                    tracking_id=f"{ts.timestamp():.0f}-{k}",
                    ticker="XYZ",
                    executed_at=ts,
                    volume=k,
                )
            )
    return out


# 19:59:59 ET on MD back 40 s, 3 prints per second (120 prints), plus 10 s of
# the prior session's 19:00 ET after-hours tail that UW's date window includes.
_DAY = _log(40, 3, start=datetime(2026, 9, 15, 23, 59, 59, tzinfo=UTC))
_PRIOR = _log(10, 3, start=datetime(2026, 9, 14, 23, 0, 0, tzinfo=UTC))


class _Uw:
    def __init__(self, prints: list[DarkLitPrint]) -> None:
        self.prints = sorted(prints, key=lambda r: r.executed_at, reverse=True)
        self.calls: list[str | None] = []

    def __call__(self, client, repo, run_id, ticker, market_date, *, limit, older_than):
        self.calls.append(older_than)
        rows = self.prints
        if older_than is not None:
            bound = datetime.fromisoformat(older_than.replace("Z", "+00:00"))
            rows = [r for r in rows if r.executed_at < bound]
        return rows[:limit]


class _Alpha:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def insert_dark_lit_prints(self, rows):
        self.rows.extend(rows)
        return len(rows)


def _run(monkeypatch, dark: _Uw, lit: _Uw, *, limit: int = 7, cap_pages: int = 60):
    monkeypatch.setattr(cap, "fetch_darkpool_prints", dark)
    monkeypatch.setattr(cap, "fetch_lit_flow", lit)
    monkeypatch.setattr(cap, "_PRINT_LIMIT", limit)
    monkeypatch.setattr(cap, "_MAX_PRINT_PAGES", cap_pages)
    alpha, stats = _Alpha(), {}
    cap.capture_dark_lit_for(None, None, alpha, 1, "XYZ", MD, stats=stats)
    return alpha.rows, stats


def _keys(rows, source):
    return {(r["tracking_id"], r["executed_at"]) for r in rows if r["source"] == source}


def test_pages_stitch_every_print_of_the_day(monkeypatch):
    # limit=7 with 3 prints/second: every page boundary splits a second, so a
    # strict older_than cursor would drop prints there.
    rows, stats = _run(monkeypatch, _Uw(_DAY + _PRIOR), _Uw(_DAY[:5]))
    assert _keys(rows, "darkpool") == {(p.tracking_id, p.executed_at) for p in _DAY}
    assert _keys(rows, "lit_flow") == {(p.tracking_id, p.executed_at) for p in _DAY[:5]}
    assert stats["pages"] > 2 and "page_cap_hits" not in stats


def test_prior_session_tail_is_dropped(monkeypatch):
    rows, _ = _run(monkeypatch, _Uw(_DAY + _PRIOR), _Uw([]))
    prior = {p.tracking_id for p in _PRIOR}
    assert rows and not any(r["tracking_id"] in prior for r in rows)
    assert all(r["market_date"] == MD for r in rows)


def test_short_first_page_is_one_call(monkeypatch):
    dark, lit = _Uw(_DAY[:3]), _Uw([])
    _, stats = _run(monkeypatch, dark, lit)
    assert dark.calls == [None] and lit.calls == [None]
    assert stats == {"pages": 2}


def test_overlap_cursor_rereads_the_boundary_second(monkeypatch):
    dark = _Uw(_DAY)
    _run(monkeypatch, dark, _Uw([]))
    # Page 1 (limit 7) ends at the 3rd second; the next cursor is that second + 1 s.
    third = _DAY[6].executed_at
    assert dark.calls[1] == (third + timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def test_page_cap_stops_and_counts(monkeypatch):
    dark, lit = _Uw(_DAY), _Uw(_DAY)
    rows, stats = _run(monkeypatch, dark, lit, cap_pages=3)
    assert len(dark.calls) == 3 and len(lit.calls) == 3
    assert stats == {"pages": 6, "page_cap_hits": 2}
    assert len(_keys(rows, "darkpool")) < len(_DAY)
