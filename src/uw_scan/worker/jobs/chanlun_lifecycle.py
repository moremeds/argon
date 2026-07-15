"""Nightly chanlun (缠论) daily-mark lifecycle scan.

Per watchlist ticker: fetch 1d apex bars, run the v2 compute pipeline
(`chanlun.full.compute_chanlun_full`), flatten the result into lifecycle
`Mark`s (`chanlun.lifecycle.derive_marks`), and evaluate every mark's state
(pending / confirmed_native / confirmed_sublevel / invalidated) via the pure
state machine in `chanlun.lifecycle`. Sub-level (S1) confirmation additionally
fetches a windowed 30m apex feed anchored at the mark's opposite-side daily
vertex (or a 40-session fallback). Every evaluated transition is upserted into
`chanlun_signal_events` (idempotent, ON CONFLICT DO NOTHING); any previously
non-terminal mark that the recompute no longer derives is explicitly
invalidated with reason="superseded" so the current-state view never carries
a stale pending/confirmed_sublevel row for a mark that dropped out of the
daily structure.

Data flow: apex (1d, then windowed 30m only for promotable candidates) ->
pure compute (chanlun.full, chanlun.lifecycle) -> ChanlunSignalRepository
(Postgres). No UW spend. Design: docs/superpowers/specs/
2026-07-14-chanlun-phase-b-sublevel-confirm-design.md.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from uw_scan.chanlun.full import compute_chanlun_full
from uw_scan.chanlun.lifecycle import (
    anchor_window,
    breached,
    crosses_split_boundary,
    derive_marks,
    evaluate_mark,
    find_split_boundaries,
    is_promotable,
    is_stale,
    s1_confirmed,
    session_et_date,
)
from uw_scan.chanlun.types import ChanlunBar
from uw_scan.config import Settings
from uw_scan.sources import apex
from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

# 1d fetch lookback: >=1,300 sessions of headroom for the daily compute
# pipeline (40-session anchor fallback + long-tail stroke/pivot context).
_DAILY_LOOKBACK_DAYS = 1900


def _filter_to_session_window(
    bars_30m_raw: list[dict], anchor_start: date
) -> list[dict]:
    """Drop 30m bars whose ET session date precedes `anchor_start`.

    apex's `start` param is a UTC-instant filter (date -> UTC midnight), but
    the probe (scripts/research/chanlun_sublevel_probe.py) windows by ET
    session date. In EST (UTC-5), a prior-session post-market bar (e.g.
    19:30 ET the evening before anchor_start) carries a UTC timestamp that
    already rolled onto anchor_start's UTC calendar date, so apex's raw
    filter admits it even though its ET session is one day earlier than
    intended -- it would otherwise leak into the head of the S1 compute
    window. Filtering here (not by changing what we pass to `fetch`) keeps
    the probe's exact ET-session semantics without a second apex round trip.
    """
    return [b for b in bars_30m_raw if session_et_date(b["time"]) >= anchor_start]


def chanlun_lifecycle_scan(
    repo: Repository,
    settings: Settings,
    *,
    ticker_filter: list[str] | None = None,
    fetch_bars: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo(settings.rth_tz)).date()

    tickers = (
        [t.upper() for t in ticker_filter]
        if ticker_filter
        else sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})
    )

    fetch = fetch_bars or apex.fetch_bars
    cs_repo = ChanlunSignalRepository(repo.conn, schema=settings.db_schema)
    promotable = frozenset(
        t.strip()
        for t in settings.chanlun_promotable_categories.split(",")
        if t.strip()
    )

    ok = 0
    skipped_no_bars = 0
    failed = 0
    transitions = 0

    for t in tickers:
        try:
            daily_raw = fetch(
                t, "1d", start=today_et - timedelta(days=_DAILY_LOOKBACK_DAYS), limit=0
            )
            if not daily_raw:
                skipped_no_bars += 1
                log.warning("chanlun_lifecycle_scan: no daily bars for %s, skipping", t)
                continue

            daily_bars = [
                ChanlunBar(
                    time=b["time"][:10], high=b["high"], low=b["low"], close=b["close"]
                )
                for b in daily_raw
            ]
            full = compute_chanlun_full(daily_bars)
            marks = derive_marks(full, daily_bars)

            boundaries = find_split_boundaries(daily_raw)
            session_dates = [date.fromisoformat(b.time) for b in daily_bars]
            last_session = session_dates[-1]

            for mark in marks:
                anchor_start = anchor_window(mark, full.vertices, session_dates)
                split_crossed = crosses_split_boundary(mark, anchor_start, boundaries)
                later = [
                    b
                    for b in daily_raw
                    if b["time"][:10] > mark.extreme_date.isoformat()
                ]
                breach = breached(mark, later)
                stale = is_stale(
                    mark, last_session, settings.chanlun_stale_sessions, session_dates
                )

                prom = is_promotable(mark.category, mark.kind, promotable)
                s1_ok = False
                s1_info: dict[str, Any] = {}
                if (
                    prom
                    and not mark.is_native_confirmed
                    and not split_crossed
                    and not breach
                    and not stale
                ):
                    bars_30m_raw = fetch(
                        t, "30m", start=anchor_start, end=None, limit=0
                    )
                    bars_30m_raw = _filter_to_session_window(bars_30m_raw, anchor_start)
                    bars_30m = [
                        ChanlunBar(
                            time=b["time"],
                            high=b["high"],
                            low=b["low"],
                            close=b["close"],
                        )
                        for b in bars_30m_raw
                    ]
                    s1_ok, s1_info = s1_confirmed(
                        mark, bars_30m, tol=settings.chanlun_anchor_tol
                    )

                state, reason = evaluate_mark(
                    mark=mark,
                    split_crossed=split_crossed,
                    breach=breach,
                    s1_ok=s1_ok,
                    promotable=prom,
                    stale=stale,
                )
                details = {"anchor_start": anchor_start.isoformat(), "v30": s1_info}

                if cs_repo.upsert_transition(
                    ticker=t,
                    category=mark.category,
                    kind=mark.kind,
                    extreme_date=mark.extreme_date,
                    extreme_price=mark.extreme_price,
                    state=state,
                    reason=reason,
                    as_of=today_et,
                    details=details,
                ):
                    transitions += 1

            derived_keys = {
                (m.category, m.kind, m.extreme_date, m.extreme_price) for m in marks
            }
            for nt in cs_repo.list_non_terminal(t):
                key = (
                    nt["category"],
                    nt["kind"],
                    nt["extreme_date"],
                    nt["extreme_price"],
                )
                if key in derived_keys:
                    continue
                if cs_repo.upsert_transition(
                    ticker=t,
                    category=nt["category"],
                    kind=nt["kind"],
                    extreme_date=nt["extreme_date"],
                    extreme_price=nt["extreme_price"],
                    state="invalidated",
                    reason="superseded",
                    as_of=today_et,
                    details={},
                ):
                    transitions += 1

            ok += 1
        except Exception:
            repo.conn.rollback()
            failed += 1
            log.exception("chanlun_lifecycle_scan: failed for %s", t)

    summary = {
        "ok": ok,
        "skipped_no_bars": skipped_no_bars,
        "failed": failed,
        "transitions": transitions,
        "tickers": len(tickers),
    }
    log.info("chanlun_lifecycle_scan: %s", summary)
    return summary
