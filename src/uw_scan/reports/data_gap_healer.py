"""Exact per-ticker/date gap audit + heal specs (strict cousin of data_freshness).

`data_freshness` answers "is this table fresh enough?" with a grace window and a
curated allow-list. This module answers the stricter question "exactly which
(ticker, date) rows are missing?" with no grace, and classifies EVERY recorded
dataset through a registry so nothing is silently uncovered.

Each dataset declares an ``audit_mode`` (how to measure coverage) and, when
healable, a ``provider`` + ``granularity`` + ``healer_adapter`` naming an EXISTING
job to re-run. The healer never invents a second write path; it orchestrates the
production writers Argon already uses.

Plan: docs/superpowers/plans/2026-06-30-data-gap-healer.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from psycopg import Connection
from psycopg import sql as psql

from uw_scan.reports.data_gap_registry import REGISTRY
from uw_scan.reports.data_gap_types import (
    _DATE_COL_PREFERENCE,
    _TICKER_COL_PREFERENCE,
    Caveat,
    CoverageSummary,
    DatasetRegistryEntry,
    GapItem,
)

logger = logging.getLogger(__name__)


def registered_table_names(registry: list[DatasetRegistryEntry]) -> set[str]:
    return {e.table_name for e in registry}


def eligible_tickers_for_date(
    active_tickers: list[str],
    data_date: date,
    caveats: tuple[Caveat, ...] | list[Caveat],
) -> set[str]:
    """Active watchlist minus any ticker caveated out on ``data_date``.

    A caveat applies when its ticker matches and ``data_date`` falls within
    [start_date, end_date] (open bounds = None). This is how SPCX is kept out of
    the denominator before it listed, without hardcoding the symbol or date here.
    """
    active = {t.upper() for t in active_tickers}
    for cav in caveats:
        if cav.ticker is None:
            continue
        if cav.start_date is not None and data_date < cav.start_date:
            continue
        if cav.end_date is not None and data_date > cav.end_date:
            continue
        active.discard(cav.ticker.upper())
    return active


def temporal_tables(conn: Connection, schema: str) -> set[str]:
    """Every table in ``schema`` that has any date/time/_at-ish column.

    Mirrors the registry-acceptance SQL in the plan: a table is "recorded data"
    if it has a temporal column. Pure set-difference against the registry lives
    in ``unregistered`` so it can be unit-tested without a DB.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
              FROM information_schema.columns
             WHERE table_schema = %s
             GROUP BY table_name
            HAVING bool_or(
                data_type IN (
                    'date',
                    'timestamp with time zone',
                    'timestamp without time zone'
                )
                OR lower(column_name) LIKE '%%date%%'
                OR lower(column_name) LIKE '%%time%%'
                OR lower(column_name) LIKE '%%\\_at'
            )
            """,
            (schema,),
        )
        return {r[0] for r in cur.fetchall()}


def unregistered(temporal: set[str], registry: list[DatasetRegistryEntry]) -> list[str]:
    """Temporal tables with no registry row -> the 'did we forget one?' list."""
    return sorted(temporal - registered_table_names(registry))


def discover_unregistered_tables(
    conn: Connection,
    schema: str,
    registry: list[DatasetRegistryEntry] | None = None,
) -> list[str]:
    reg = REGISTRY if registry is None else registry
    return unregistered(temporal_tables(conn, schema), reg)


# --- read-only coverage scanner --------------------------------------------

# The canonical equity-session calendar. We use ONLY this clean trading-day
# reference (market_tide_sentiment_daily: weekday-only, holiday-excluded — UW
# emits no sentiment on closed-market days). Earlier we also self-unioned the
# dataset's own dates, but a stray weekend/holiday price-bar in the dataset then
# leaked that non-trading day into its own expected calendar, manufacturing a
# full-watchlist phantom gap for every ticker missing that bar. Limitation: the
# window cannot extend before the reference table's earliest date (YTD scope).
REFERENCE_CALENDAR = ("market_tide_sentiment_daily", "data_date")
# Second, independently-sourced witness. massive publishes SPY bars only on
# real sessions, so unioning it cannot manufacture a weekend/holiday entry —
# and because it is a DIFFERENT provider from UW, a UW outage cannot blind it.
_SPINE_WITNESS = ("daily_ohlc", "date", "ticker", "SPY")


@dataclass(frozen=True)
class SpineHealth:
    """How much of the expected-session spine the reference table is missing."""

    ref_sessions: int
    witness_sessions: int
    missing_from_ref: tuple[date, ...]


def detect_col(
    conn: Connection, schema: str, table: str, preference: tuple[str, ...]
) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        cols = {r[0] for r in cur.fetchall()}
    for pref in preference:
        if pref in cols:
            return pref
    return None


def calendar_dates(
    conn: Connection,
    schema: str,
    start: date,
    end: date,
) -> list[date]:
    """Trading-day calendar in [start, end] from two independent witnesses.

    The reference (market_tide_sentiment_daily) is itself CAPTURED, so an
    outage that stops capture also erases the evidence of the outage and every
    dataset then audits as 100% covered for exactly the days that were lost
    (measured 2026-08-16: 1,276 gaps reported vs 8,080 real). SPY's massive
    OHLC is the second witness: different provider, session-only bars, and
    already healable via the `daily_ohlc` adapter.

    A phantom session (a witness bar on a non-trading day) is handled by a
    Caveat row, not by code — see SEED_CAVEATS.
    """
    ref_tbl, ref_col = REFERENCE_CALENDAR
    wit_tbl, wit_col, wit_tcol, wit_ticker = _SPINE_WITNESS
    query = psql.SQL(
        """
        SELECT d FROM (
            SELECT DISTINCT {rcol} AS d FROM {rtbl}
             WHERE {rcol} BETWEEN %s AND %s AND {rcol} IS NOT NULL
            UNION
            SELECT DISTINCT {wcol} AS d FROM {wtbl}
             WHERE {wcol} BETWEEN %s AND %s AND UPPER({wtcol}) = %s
        ) spine ORDER BY d
        """
    ).format(
        rcol=psql.Identifier(ref_col),
        rtbl=psql.Identifier(schema, ref_tbl),
        wcol=psql.Identifier(wit_col),
        wtbl=psql.Identifier(schema, wit_tbl),
        wtcol=psql.Identifier(wit_tcol),
    )
    with conn.cursor() as cur:
        cur.execute(query, (start, end, start, end, wit_ticker))
        return [r[0] for r in cur.fetchall()]


def spine_health(conn: Connection, schema: str, start: date, end: date) -> SpineHealth:
    """Sessions the witness has that the reference lost — the outage signature."""
    ref_tbl, ref_col = REFERENCE_CALENDAR
    wit_tbl, wit_col, wit_tcol, wit_ticker = _SPINE_WITNESS
    with conn.cursor() as cur:
        cur.execute(
            psql.SQL(
                "SELECT DISTINCT {rcol} FROM {rtbl} "
                "WHERE {rcol} BETWEEN %s AND %s AND {rcol} IS NOT NULL"
            ).format(
                rcol=psql.Identifier(ref_col), rtbl=psql.Identifier(schema, ref_tbl)
            ),
            (start, end),
        )
        ref = {r[0] for r in cur.fetchall()}
        cur.execute(
            psql.SQL(
                "SELECT DISTINCT {wcol} FROM {wtbl} "
                "WHERE {wcol} BETWEEN %s AND %s AND UPPER({wtcol}) = %s"
            ).format(
                wcol=psql.Identifier(wit_col),
                wtbl=psql.Identifier(schema, wit_tbl),
                wtcol=psql.Identifier(wit_tcol),
            ),
            (start, end, wit_ticker),
        )
        wit = {r[0] for r in cur.fetchall()}
    return SpineHealth(len(ref), len(wit), tuple(sorted(wit - ref)))


def missing_ticker_date_pairs(
    conn: Connection,
    schema: str,
    table: str,
    date_col: str,
    ticker_col: str,
    calendar: list[date],
    tickers: list[str],
) -> list[tuple[date, str]]:
    if not calendar or not tickers:
        return []
    query = psql.SQL(
        """
        SELECT cal.d, tk.t
          FROM unnest(%s::date[]) AS cal(d)
          CROSS JOIN unnest(%s::text[]) AS tk(t)
          LEFT JOIN {tbl} a
                 ON a.{dcol} = cal.d AND UPPER(a.{tcol}) = tk.t
         WHERE a.{tcol} IS NULL
         ORDER BY cal.d, tk.t
        """
    ).format(
        tbl=psql.Identifier(schema, table),
        dcol=psql.Identifier(date_col),
        tcol=psql.Identifier(ticker_col),
    )
    with conn.cursor() as cur:
        cur.execute(query, (calendar, tickers))
        return [(r[0], r[1]) for r in cur.fetchall()]


def _present_session_dates(
    conn: Connection, schema: str, table: str, date_col: str, start: date, end: date
) -> set[date]:
    query = psql.SQL(
        "SELECT DISTINCT {dcol} FROM {tbl} WHERE {dcol} BETWEEN %s AND %s"
    ).format(dcol=psql.Identifier(date_col), tbl=psql.Identifier(schema, table))
    with conn.cursor() as cur:
        cur.execute(query, (start, end))
        return {r[0] for r in cur.fetchall() if r[0] is not None}


def _scan_strict_ticker_date(
    conn: Connection,
    schema: str,
    entry: DatasetRegistryEntry,
    active: list[str],
    caveats: tuple[Caveat, ...] | list[Caveat],
    start: date,
    end: date,
) -> tuple[CoverageSummary, list[GapItem]]:
    table = entry.table_name
    date_col = entry.date_col or detect_col(conn, schema, table, _DATE_COL_PREFERENCE)
    tcol = entry.ticker_col or detect_col(conn, schema, table, _TICKER_COL_PREFERENCE)
    if not date_col or not tcol:
        # A strict dataset whose columns cannot be resolved reports zero gaps,
        # which is indistinguishable from "fully covered" -- exactly the silent
        # no-op this healer exists to surface. Never let it pass quietly.
        # (pcr_history and option_chain_per_strike hit this on 2026-08-16: both
        # key on snapshot_date, which is absent from _DATE_COL_PREFERENCE.)
        logger.error(
            "gap_audit: %s is %s but its columns did not resolve "
            "(date_col=%r ticker_col=%r) — reporting ZERO gaps for it. Set "
            "date_col/ticker_col explicitly on its DatasetRegistryEntry.",
            table,
            entry.audit_mode,
            date_col,
            tcol,
        )
        return CoverageSummary(table, "strict_ticker_date", 0, 0, 0, ()), []

    calendar = calendar_dates(conn, schema, start, end)
    eligible_by_date = {
        d: eligible_tickers_for_date(active, d, caveats) for d in calendar
    }
    tickers = sorted({t.upper() for t in active})
    raw = missing_ticker_date_pairs(
        conn, schema, table, date_col, tcol, calendar, tickers
    )

    items: list[GapItem] = []
    gap_dates: set[date] = set()
    for d, tk in raw:
        if tk not in eligible_by_date.get(d, set()):
            continue  # caveated out (e.g. SPCX pre-listing)
        items.append(
            GapItem(table, f"{d.isoformat()}|{tk}", d, tk, None, None, "planned")
        )
        gap_dates.add(d)

    expected = sum(len(v) for v in eligible_by_date.values())
    missing = len(items)
    summary = CoverageSummary(
        table,
        "strict_ticker_date",
        expected,
        expected - missing,
        missing,
        tuple(sorted(gap_dates)),
    )
    return summary, items


def _scan_strict_session(
    conn: Connection,
    schema: str,
    entry: DatasetRegistryEntry,
    start: date,
    end: date,
) -> tuple[CoverageSummary, list[GapItem]]:
    table = entry.table_name
    date_col = entry.date_col or detect_col(conn, schema, table, _DATE_COL_PREFERENCE)
    if not date_col:
        return CoverageSummary(table, "strict_session", 0, 0, 0, ()), []
    calendar = calendar_dates(conn, schema, start, end)
    present = _present_session_dates(conn, schema, table, date_col, start, end)
    missing_dates = [d for d in calendar if d not in present]
    items = [
        GapItem(table, d.isoformat(), d, None, None, None, "planned")
        for d in missing_dates
    ]
    summary = CoverageSummary(
        table,
        "strict_session",
        len(calendar),
        len(calendar) - len(missing_dates),
        len(missing_dates),
        tuple(missing_dates),
    )
    return summary, items


def scan_dataset(
    conn: Connection,
    schema: str,
    entry: DatasetRegistryEntry,
    active: list[str],
    caveats: tuple[Caveat, ...] | list[Caveat],
    start: date,
    end: date,
) -> tuple[CoverageSummary, list[GapItem]]:
    """Coverage + gap items for one dataset, branching on audit_mode.

    Only ``strict_*`` modes produce gap items. freshness/operational/provenance/
    research/excluded datasets are accounted for (a summary row) but never get
    gap items here — they are not strict-coverage problems.
    """
    if entry.audit_mode == "strict_ticker_date":
        return _scan_strict_ticker_date(
            conn, schema, entry, active, caveats, start, end
        )
    if entry.audit_mode == "strict_session":
        return _scan_strict_session(conn, schema, entry, start, end)
    return CoverageSummary(entry.table_name, entry.audit_mode, 0, 0, 0, ()), []


def audit(
    conn: Connection,
    schema: str,
    registry: list[DatasetRegistryEntry],
    active: list[str],
    caveats: tuple[Caveat, ...] | list[Caveat],
    start: date,
    end: date,
    datasets: list[str] | None = None,
) -> tuple[list[CoverageSummary], list[GapItem]]:
    """Read-only exact-coverage audit. Makes ZERO provider calls."""
    wanted = set(datasets) if datasets else None
    summaries: list[CoverageSummary] = []
    items: list[GapItem] = []
    for entry in registry:
        if not entry.enabled:
            continue
        if wanted is not None and entry.table_name not in wanted:
            continue
        summary, dataset_items = scan_dataset(
            conn, schema, entry, active, caveats, start, end
        )
        summaries.append(summary)
        items.extend(dataset_items)
    return summaries, items


def render_dataset_policy_markdown(
    registry: list[DatasetRegistryEntry] | None = None,
) -> str:
    """Generate the dataset-policy runbook table from the registry (one source
    of truth). Re-run after registry changes; committed to docs/runbooks/."""
    reg = REGISTRY if registry is None else registry
    by_group: dict[str, list[DatasetRegistryEntry]] = {}
    for e in reg:
        by_group.setdefault(e.dataset_group, []).append(e)

    lines = [
        "# Data gap dataset policy",
        "",
        "Generated from `REGISTRY` in `src/uw_scan/reports/data_gap_registry/` "
        "(one source of truth). Regenerate with:",
        "",
        "```bash",
        'uv run python -c "from uw_scan.reports.data_gap_healer import '
        "render_dataset_policy_markdown as r; "
        "open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())\"",
        "```",
        "",
        f"**{len(reg)} datasets** across {len(by_group)} groups.",
        "",
    ]
    for group in sorted(by_group):
        lines.append(f"## {group}")
        lines.append("")
        lines.append(
            "| table | audit_mode | provider | granularity | adapter | freq | "
            "reason | verified |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for e in sorted(by_group[group], key=lambda x: x.table_name):
            lines.append(
                f"| {e.table_name} | {e.audit_mode} | {e.provider} | "
                f"{e.granularity} | {e.healer_adapter or ''} | "
                f"{e.expected_frequency} | {e.reason or ''} | "
                f"{e.reason_verified_on or ''} |"
            )
        lines.append("")
    return "\n".join(lines)
