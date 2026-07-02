"""Per-table data-DATE freshness audit (prevention layer for silent freezes).

Complements storage.health.list_record_health: that check discovers tables by a
WRITE-timestamp column (updated_at/inserted_at) and measures rows-written-lately
vs the watchlist. It is structurally blind to (a) tables with no write-timestamp
column (greek_exposure_daily) and (b) a frozen DATA date behind fresh writes.
This module measures the newest DATA date and scope-aware coverage instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection
from psycopg import sql as psql

# Preference order for the data-date column, most specific first. The monitor
# auto-detects which one a table actually has (avoids hardcoding a wrong name).
_DATE_COL_PREFERENCE = (
    "market_date",
    "trade_date",
    "session_date",
    "curr_date",
    "as_of_date",
    "obs_date",
    "obs_month",
    "date",
)


@dataclass(frozen=True)
class MonitoredTable:
    name: str
    scope: str  # 'watchlist' (denominator = active watchlist) | 'subset' (named set)
    expected_tickers: frozenset[str] | None  # required when scope == 'subset'
    grace_days: int | None = None  # None -> inherit compute_freshness's grace_days


@dataclass(frozen=True)
class FreshnessRow:
    table_name: str
    date_col: str
    scope: str
    expected_count: int
    covered_count: int
    coverage_pct: float | None
    max_data_date: date | None
    days_stale: int | None
    frozen: bool


# Curated allow-list. Scope marks by-design-partial tables so they don't cry
# wolf (the false-positive the original audit itself tripped over). Extend as
# new per-ticker tables ship; unknown date columns are skipped with a row.
MONITORED_TABLES: list[MonitoredTable] = [
    MonitoredTable("options_volume_daily", "watchlist", None),
    MonitoredTable("daily_ohlc", "watchlist", None),
    MonitoredTable("vrp_daily", "watchlist", None),
    MonitoredTable("exposures_by_expiry_strike", "watchlist", None),
    MonitoredTable("oi_by_strike", "watchlist", None),
    # Ticker-less (keyed by option_symbol) -> freshness-only; per-ticker
    # coverage for this table is guarded by the intraday job's counters (#180).
    MonitoredTable("option_intraday_buckets", "watchlist", None),
    MonitoredTable(
        "greek_exposure_daily", "watchlist", None
    ),  # watchlist-wide post-#179
    MonitoredTable(
        "iv_rank_history",
        "subset",
        frozenset({"SPX", "SPY", "QQQ", "IWM"}),  # cockpit-only by design
    ),
    # --- gold_rates_macro: known-stale-since-2026-06/07 tables from the
    # etf_flows_daily timezone-bug investigation. Only etf_flows_daily has a
    # confirmed fix (gold_etf_holdings_ingest_job now uses ET, not host-local,
    # dates) -- daily cadence, default grace_days is fine. The other three
    # remain genuinely blocked (WGC Goldhub login wall / CME anonymous-scrape
    # 403) and WILL show frozen until someone provisions a credential or a
    # paid data license -- that is a real, standing alert, not noise.
    MonitoredTable(
        "etf_flows_daily",
        "subset",
        frozenset({"GLD", "IAU", "GLDM"}),  # gold_jobs.GOLD_ETF_FLOW_TICKERS
    ),
    MonitoredTable(
        "wgc_etf_monthly",
        "subset",
        frozenset({"GLD", "IAU", "GLDM", "PHYS"}),
        grace_days=45,  # monthly WGC release cadence
    ),
    MonitoredTable(
        "cb_gold_reserves_monthly",
        "watchlist",  # ticker-less (keyed by country_iso3) -> freshness-only
        None,
        grace_days=45,  # monthly WGC CB-reserves cadence
    ),
    MonitoredTable(
        "exchange_inventory_daily",
        "watchlist",  # ticker-less (keyed by exchange) -> freshness-only
        None,
        grace_days=45,  # LBMA leg is monthly; COMEX leg is blocked
    ),
]


def _detect_date_col(conn: Connection, schema: str, table: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        cols = {r[0] for r in cur.fetchall()}
    if not cols:
        return None
    for pref in _DATE_COL_PREFERENCE:
        if pref in cols:
            return pref
    return None


def _ticker_col(conn: Connection, schema: str, table: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
               AND column_name IN ('ticker', 'symbol', 'underlying')
             ORDER BY array_position(ARRAY['ticker','symbol','underlying'], column_name)
             LIMIT 1
            """,
            (schema, table),
        )
        row = cur.fetchone()
    return row[0] if row else None


def compute_freshness(
    conn: Connection,
    schema: str,
    monitored: list[MonitoredTable],
    active_tickers: list[str],
    today: date,
    grace_days: int = 4,  # ponytail: covers a weekend + a holiday; raise per-table later if noisy
) -> list[FreshnessRow]:
    out: list[FreshnessRow] = []
    active = {t.upper() for t in active_tickers}
    for mt in monitored:
        table_grace = mt.grace_days if mt.grace_days is not None else grace_days
        date_col = _detect_date_col(conn, schema, mt.name)
        tcol = _ticker_col(conn, schema, mt.name)
        if date_col is None:
            # No data-date column at all -> nothing this monitor can measure.
            out.append(
                FreshnessRow(mt.name, "?", mt.scope, 0, 0, None, None, None, False)
            )
            continue

        # Data-date freshness needs only the date column — works even for
        # ticker-less tables (e.g. option_intraday_buckets, keyed by
        # option_symbol). A TOTAL freeze of such a table is still caught here;
        # per-ticker COVERAGE (the #180 class) needs a ticker column and is
        # guarded separately by the intraday job's per-outcome counters.
        with conn.cursor() as cur:
            # ponytail: plain MAX — a seq scan on tables without a lone date
            # index (e.g. exposures_by_expiry_strike). Fine for one nightly run;
            # add a date index only if this monitor ever shows up as slow.
            cur.execute(
                psql.SQL("SELECT MAX({dcol}) FROM {tbl}").format(
                    dcol=psql.Identifier(date_col),
                    tbl=psql.Identifier(schema, mt.name),
                )
            )
            max_date = cur.fetchone()[0]
        days_stale = (today - max_date).days if max_date else None
        frozen = days_stale is not None and days_stale > table_grace

        if tcol is None:
            # Freshness-only: no per-ticker coverage possible.
            out.append(
                FreshnessRow(
                    mt.name,
                    date_col,
                    mt.scope,
                    0,
                    0,
                    None,
                    max_date,
                    days_stale,
                    frozen,
                )
            )
            continue

        if mt.scope == "subset" and mt.expected_tickers:
            expected = {t.upper() for t in mt.expected_tickers}
        else:
            expected = active
        expected_count = len(expected)

        # Covered = expected-scope tickers with a row within grace_days of the
        # table's own newest date, so a table legitimately lagging one session
        # still counts those tickers covered.
        covered = 0
        if max_date is not None and expected:
            covq = psql.SQL(
                "SELECT COUNT(DISTINCT {tcol})::int FROM {tbl} "
                "WHERE {dcol} >= %s - %s::int AND UPPER({tcol}) = ANY(%s)"
            ).format(
                dcol=psql.Identifier(date_col),
                tcol=psql.Identifier(tcol),
                tbl=psql.Identifier(schema, mt.name),
            )
            with conn.cursor() as cur:
                cur.execute(covq, (max_date, table_grace, list(expected)))
                covered = cur.fetchone()[0]

        coverage_pct = (covered / expected_count) if expected_count else None
        out.append(
            FreshnessRow(
                mt.name,
                date_col,
                mt.scope,
                expected_count,
                covered,
                coverage_pct,
                max_date,
                days_stale,
                frozen,
            )
        )
    return out
