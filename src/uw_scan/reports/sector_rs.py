"""Sector relative strength + breadth — pure compute.

Spec: docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md §2–§3.
No I/O and no DB. The nightly job (worker/jobs/sector_rs_daily.py) and the
backfill (scripts/backfill/sector_rs_backfill.py) both call
`compute_group_rows`, so every number has one definition.

Windows are anchored on the BENCHMARK's sessions, not on each series' own bar
count. A member's window-w return is close(end)/close(start) − 1, where `end`
is SPY's last session ≤ as_of and `start` is SPY's session w bars earlier. A
member missing either anchor is unpriced for w. Counting a member's own last
w+1 closes instead would price a name delisted mid-window over a stale window
that ended weeks before as_of, and report it as current.

RS is in percentage points (group return − SPY return, not a ratio). Breadth is
the fraction of members priced for w whose return beats SPY's.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date
from statistics import fmean

WINDOWS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
_LONGEST = "12m"
#: Below this share of members priced over 12m the row is `degraded` (spec §3).
COVERAGE_FLOOR = 0.8

Series = list[tuple[date, float]]


@dataclass(frozen=True)
class GroupSpec:
    kind: str  # 'gics' | 'chain'
    key: str  # 'Technology' | 'Semi-Logic' ...
    weighting: str  # 'etf' | 'equal'
    rs_symbol: str | None  # 'XLK' for etf rows; None for equal
    members: tuple[str, ...]
    #: First session the rs_symbol's adjusted history is trustworthy. An RS
    #: window whose start anchor is earlier is NULL (spec §4: XLF's seam).
    rs_valid_from: date | None = None


@dataclass(frozen=True)
class SectorRsRow:
    as_of: date
    group_kind: str
    group_key: str
    weighting: str
    rs_symbol: str | None
    n_members: int
    n_classified: int
    n_priced: int
    rs: dict[str, float | None]  # percentage points, keyed by WINDOWS label
    breadth: dict[str, float | None]  # fraction in [0, 1], keyed by WINDOWS label
    degraded: bool
    source: str  # 'apex' | 'daily_ohlc'


def window_return(closes: list[float], n: int) -> float | None:
    """Plain price return over the last `n` bars: closes[-1] / closes[-1-n] − 1.

    `closes` ascending, last element = the as_of session. None when fewer than
    n+1 closes exist, n is not positive, or the base close is not positive.
    """
    if n <= 0 or len(closes) < n + 1:
        return None
    base = closes[-1 - n]
    if base <= 0:
        return None
    return closes[-1] / base - 1.0


def _close_on(series: Series | None, day: date) -> float | None:
    """The close dated exactly `day`. Bisect on (date,) — series ascending."""
    if not series:
        return None
    i = bisect_left(series, (day,))
    if i < len(series) and series[i][0] == day:
        return series[i][1]
    return None


def _anchored_return(series: Series | None, start: date, end: date) -> float | None:
    base = _close_on(series, start)
    last = _close_on(series, end)
    if base is None or last is None or base <= 0:
        return None
    return last / base - 1.0


def compute_group_rows(
    as_of: date,
    groups: list[GroupSpec],
    closes: dict[str, Series],
    benchmark: str = "SPY",
    source: str = "apex",
) -> list[SectorRsRow]:
    """One SectorRsRow per group, for the session ending at the last close ≤ as_of.

    `closes[symbol]` is ascending (date, adjusted close). Bars after `as_of`
    are ignored. Raises ValueError when the benchmark cannot cover every window:
    a row without a benchmark is not a row with zero RS, and the caller must not
    write anything.
    """
    bench_all = closes.get(benchmark) or []
    bench = bench_all[: bisect_right(bench_all, (as_of, float("inf")))]
    bench_closes = [c for _, c in bench]
    bench_ret: dict[str, float] = {}
    anchors: dict[str, tuple[date, date]] = {}
    for label, n in reversed(WINDOWS.items()):
        r = window_return(bench_closes, n)
        if r is None:
            raise ValueError(
                f"{benchmark} has {len(bench_closes)} closes <= {as_of}; "
                f"window {label} needs {n + 1}"
            )
        bench_ret[label] = r
        anchors[label] = (bench[-1 - n][0], bench[-1][0])

    rows: list[SectorRsRow] = []
    for g in groups:
        member_ret: dict[str, dict[str, float]] = {}
        for label in WINDOWS:
            start, end = anchors[label]
            priced: dict[str, float] = {}
            for m in g.members:
                r = _anchored_return(closes.get(m), start, end)
                if r is not None:
                    priced[m] = r
            member_ret[label] = priced
        breadth: dict[str, float | None] = {
            label: (
                sum(1 for r in rets.values() if r > bench_ret[label]) / len(rets)
                if rets
                else None
            )
            for label, rets in member_ret.items()
        }
        if g.weighting == "etf":
            group_ret: dict[str, float | None] = {
                label: (
                    None
                    if g.rs_valid_from is not None
                    and anchors[label][0] < g.rs_valid_from
                    else _anchored_return(
                        closes.get(g.rs_symbol or ""), *anchors[label]
                    )
                )
                for label in WINDOWS
            }
        elif g.weighting == "equal":
            group_ret = {
                label: fmean(rets.values()) if rets else None
                for label, rets in member_ret.items()
            }
        else:
            raise ValueError(f"unknown weighting {g.weighting!r} for {g.kind}/{g.key}")
        rs: dict[str, float | None] = {}
        for label in WINDOWS:
            gr = group_ret[label]
            rs[label] = None if gr is None else (gr - bench_ret[label]) * 100.0
        n_members = len(g.members)
        n_priced = len(member_ret[_LONGEST])
        degraded = (
            n_members == 0
            or n_priced < COVERAGE_FLOOR * n_members
            or rs[_LONGEST] is None
        )
        rows.append(
            SectorRsRow(
                as_of=as_of,
                group_kind=g.kind,
                group_key=g.key,
                weighting=g.weighting,
                rs_symbol=g.rs_symbol,
                n_members=n_members,
                n_classified=n_members,
                n_priced=n_priced,
                rs=rs,
                breadth=breadth,
                degraded=degraded,
                source=source,
            )
        )
    return rows
