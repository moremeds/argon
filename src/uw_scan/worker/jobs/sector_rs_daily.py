"""Nightly sector RS + breadth (`sector_rs_daily`, migration 152).

Spec: docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md §2–§5.
Zero UW spend: apex adjusted daily bars (listing=any), with a daily_ohlc
fallback for SPY and the 11 SPDR ETFs only. `run_sector_rs` is the ONE core.
The nightly wrapper below and scripts/backfill/sector_rs_backfill.py both call
it, so a backfilled row and a nightly row for one session are the same row.

Membership:
- gics  — the vendored CURRENT S&P 500 list (sources/sp500_members.py,
          copied from livewire presets/sp500.json; apex's membership route is
          not used, see that module), applied to every session, nightly and
          backfill alike. Mapped ticker → vendor sector through
          company_sector. A member with no row, a NULL sector, or a label
          outside the 11 belongs to no group and is counted as `unclassified`.
          Classification is also current over the whole window (spec §4).
          SURVIVORSHIP: former members are absent from n_members, and a
          delisted name has no adjusted bars (apex files it under `missing`),
          so it is unpriced. Breadth history describes today's index, and the
          run's log line says so.
- chain — watchlist_chain as it is TODAY. argon keeps no chain-membership
          history, so backfilled chain rows carry today's membership. That
          look-ahead is one reason the §6 probe reads gics rows only.

Refusals (never write a misleading row):
- SPY unavailable from apex and daily_ohlc → RuntimeError, nothing written.
- SPY too short for the 12m window on the earliest session → ValueError,
  nothing written (checked before the first upsert).
- the vendored sp500 list fails validation → the run's gics rows are
  skipped with a logged error (`membership_invalid` = 1); chain rows still write.

A requested date that is not a session snaps to the last SPY session on or
before it, so a Saturday run rewrites Friday's rows instead of adding a
duplicate row labelled Saturday.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import date, timedelta

import psycopg

from uw_scan.reports.sector_rs import (
    WINDOWS,
    GroupSpec,
    SectorRsRow,
    compute_group_rows,
)
from uw_scan.sources.sp500_members import Sp500ListInvalid, sp500_members
from uw_scan.storage.company_sector import CompanySectorRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.sector_rs import SectorRsRepository
from uw_scan.storage.watchlist_chain import WatchlistChainRepository

log = logging.getLogger(__name__)

BENCHMARK = "SPY"
#: Vendor sector label (company_sector.sector; all 11 present in
#: option_wizard_local on 2026-09-26) → SPDR sector ETF. Fixed, spec §2.
SPDR_SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}
#: First trustworthy session of an ETF's adjusted history (spec §4). Empty
#: since Silver rev 88 fixed XLF's XLRE spin-off seam (the false +31% jump on
#: 2016-09-19); add an entry if a fund's served history is again wrong.
ETF_RS_VALID_FROM: dict[str, date] = {}
#: The only symbols allowed to fall back to daily_ohlc (spec §4).
FALLBACK_SYMBOLS: frozenset[str] = frozenset({BENCHMARK, *SPDR_SECTOR_ETFS.values()})
GROUP_KINDS: tuple[str, ...] = ("gics", "chain")
#: 253 sessions is about 367 calendar days; 400 clears the holidays with margin.
LOOKBACK_CALENDAR_DAYS = 400
#: Calendar days the nightly recomputes (≈5 sessions); see sector_rs_daily.
NIGHTLY_RECOMPUTE_DAYS = 7
_MIN_BENCH_CLOSES = max(WINDOWS.values()) + 1

Closes = dict[str, list[tuple[date, float]]]
ClosesFetcher = Callable[..., dict[str, dict[date, float]]]


def build_gics_groups(
    members: Iterable[str], sector_of: dict[str, str | None]
) -> tuple[list[GroupSpec], int]:
    """The 11 etf-weighted groups, plus the count of members in none of them."""
    by_sector: dict[str, list[str]] = {s: [] for s in SPDR_SECTOR_ETFS}
    unclassified = 0
    for m in sorted({t.upper() for t in members}):
        sector = sector_of.get(m)
        if sector is not None and sector in by_sector:
            by_sector[sector].append(m)
        else:
            unclassified += 1
    groups = [
        GroupSpec(
            "gics",
            sector,
            "etf",
            etf,
            tuple(by_sector[sector]),
            rs_valid_from=ETF_RS_VALID_FROM.get(etf),
        )
        for sector, etf in SPDR_SECTOR_ETFS.items()
    ]
    return groups, unclassified


def chain_groups(conn: psycopg.Connection, schema: str) -> list[GroupSpec]:
    """Every chain with an active member, equal-weighted (no chain ETF exists)."""
    repo = WatchlistChainRepository(conn, schema=schema)
    return [
        GroupSpec("chain", chain, "equal", None, tuple(repo.tickers_in_chain(chain)))
        for chain in sorted(repo.counts_by_chain())
    ]


def load_closes(
    repo: Repository,
    symbols: Iterable[str],
    *,
    start: date,
    end: date,
    fetch_closes: ClosesFetcher,
    today: date | None = None,
) -> tuple[Closes, set[str]]:
    """Ascending closes per symbol, plus the set that came from daily_ohlc.

    apex first. daily_ohlc only for FALLBACK_SYMBOLS that apex did not serve.
    `list_daily_ohlc` returns the newest `limit` rows, so the limit is the
    calendar-day distance from today back to `start`, which always reaches it.
    """
    wanted = sorted({s.upper() for s in symbols})
    got = dict(fetch_closes(wanted, start=start, end=end))
    fell_back: set[str] = set()
    limit = max(1, ((today or date.today()) - start).days + 1)
    for sym in sorted(FALLBACK_SYMBOLS.intersection(wanted) - set(got)):
        rows = repo.list_daily_ohlc(sym, limit=limit)
        series = {r.date: float(r.close) for r in rows if start <= r.date <= end}
        if series:
            got[sym] = series
            fell_back.add(sym)
    return {s: sorted(v.items()) for s, v in got.items()}, fell_back


def snap_sessions(spy: list[tuple[date, float]], dates: Iterable[date]) -> list[date]:
    """Each requested date → the last SPY session ≤ it; deduped, ascending."""
    out: set[date] = set()
    for d in dates:
        i = bisect_right(spy, (d, float("inf")))
        if i:
            out.add(spy[i - 1][0])
    return sorted(out)


def _tag_source(row: SectorRsRow, fell_back: set[str]) -> SectorRsRow:
    """'daily_ohlc' when the row's benchmark or RS numerator came from the fallback."""
    if BENCHMARK in fell_back or (
        row.rs_symbol is not None and row.rs_symbol in fell_back
    ):
        return replace(row, source="daily_ohlc")
    return row


def run_sector_rs(
    *,
    repo: Repository,
    schema: str,
    dates: Sequence[date],
    group_kinds: Sequence[str] = GROUP_KINDS,
    fetch_closes: ClosesFetcher,
) -> dict[str, int]:
    """Compute and upsert sector_rs_daily for each requested date. Returns counters."""
    counters = dict.fromkeys(
        (
            "sessions",
            "rows",
            "gics_rows",
            "chain_rows",
            "degraded",
            "daily_ohlc_rows",
            "unclassified",
            "membership_invalid",
            "gics_n_members",
            "gics_n_priced",
        ),
        0,
    )
    unknown = set(group_kinds) - set(GROUP_KINDS)
    if unknown:
        raise ValueError(f"unknown group_kind {sorted(unknown)}")
    if not dates:
        return counters
    start = min(dates) - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    end = max(dates)

    spy_closes, spy_fell_back = load_closes(
        repo, [BENCHMARK], start=start, end=end, fetch_closes=fetch_closes
    )
    spy = spy_closes.get(BENCHMARK)
    if not spy:
        raise RuntimeError(
            "SPY closes unavailable from apex and daily_ohlc; refusing to write sector_rs_daily"
        )
    sessions = snap_sessions(spy, dates)
    if not sessions:
        return counters
    first_bench = bisect_right(spy, (sessions[0], float("inf")))
    if first_bench < _MIN_BENCH_CLOSES:
        raise ValueError(
            f"{BENCHMARK} has {first_bench} closes <= {sessions[0]}; window 12m needs "
            f"{_MIN_BENCH_CLOSES}; nothing written"
        )

    groups_by_kind: dict[str, dict[date, list[GroupSpec]]] = {}
    symbols: set[str] = set()
    if "chain" in group_kinds:
        chains = chain_groups(repo.conn, schema)
        groups_by_kind["chain"] = {s: chains for s in sessions}
        symbols.update(m for g in chains for m in g.members)
    if "gics" in group_kinds:
        # The vendored CURRENT list, applied to every session (spec §4 ruling).
        try:
            members = sp500_members()
        except Sp500ListInvalid as exc:
            counters["membership_invalid"] = 1
            log.error(
                "sector_rs: vendored sp500 list invalid (%s); gics rows skipped for %d sessions",
                repr(exc),
                len(sessions),
            )
        else:
            sector_of = CompanySectorRepository(repo.conn, schema=schema).sectors_for(
                list(members)
            )
            gics_groups, counters["unclassified"] = build_gics_groups(
                members, sector_of
            )
            groups_by_kind["gics"] = {s: gics_groups for s in sessions}
            symbols.update(members)
            symbols.update(SPDR_SECTOR_ETFS.values())
    symbols.discard(BENCHMARK)
    closes, fell_back = load_closes(
        repo, symbols, start=start, end=end, fetch_closes=fetch_closes
    )
    closes[BENCHMARK] = spy
    fell_back |= spy_fell_back

    store = SectorRsRepository(repo.conn, schema=schema)
    for s in sessions:
        for kind in GROUP_KINDS:
            groups = groups_by_kind.get(kind, {}).get(s)
            if not groups:
                continue
            rows = [
                _tag_source(r, fell_back)
                for r in compute_group_rows(s, groups, closes, benchmark=BENCHMARK)
            ]
            store.upsert_rows(rows)
            counters[f"{kind}_rows"] += len(rows)
            counters["rows"] += len(rows)
            counters["degraded"] += sum(r.degraded for r in rows)
            counters["daily_ohlc_rows"] += sum(r.source == "daily_ohlc" for r in rows)
            if kind == "gics":  # last session's totals, for the survivorship log line
                counters["gics_n_members"] = sum(r.n_members for r in rows)
                counters["gics_n_priced"] = sum(r.n_priced for r in rows)
        counters["sessions"] += 1
    log.info(
        "sector_rs %s | gics n_priced %d / n_members %d on the last session; "
        "membership is TODAY's sp500 applied to every session and delisted names "
        "are unpriced, so breadth is survivorship-biased",
        counters,
        counters["gics_n_priced"],
        counters["gics_n_members"],
    )
    return counters


def sector_rs_daily(
    *,
    repo: Repository,
    schema: str,
    as_of: date,
    fetch_closes: ClosesFetcher,
) -> dict[str, int]:
    """Nightly entry point: the last week's sessions, both group kinds.

    Recomputing a trailing week (not just as_of) means a night on which apex has
    not yet published today's bar, or on which apex could not answer (any failed
    chunk raises SourceUnavailable and fails the run, rather than silently
    dropping up to 200 symbols from breadth), heals on the next run; the upsert
    converges and the table is excluded from the gap healer.
    """
    return run_sector_rs(
        repo=repo,
        schema=schema,
        dates=[as_of - timedelta(days=d) for d in range(NIGHTLY_RECOMPUTE_DAYS)],
        fetch_closes=fetch_closes,
    )
