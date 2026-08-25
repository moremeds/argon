"""Phase A1 (Gold) — APScheduler job functions.

9 jobs total:

- Daily (Tasks 23):
    gold_fred_ingest_job          — FRED CSV refresh, daily + monthly series
    gold_gpr_ingest_job           — Caldara-Iacoviello GPRD daily
    gold_etf_holdings_ingest_job  — GLD / IAU / GLDM / PHYS daily holdings
    gold_comex_vault_ingest_job   — COMEX gold-stocks daily
    gold_uw_options_ingest_job    — GLD / GDX / IAU snapshot (Task 9)

- Weekly + monthly (Task 24):
    gold_cftc_cot_ingest_job      — CFTC COT disaggregated weekly
    gold_lbma_vault_ingest_job    — LBMA monthly vault total
    gold_wgc_cb_ingest_job        — WGC monthly CB reserves

- Orchestrator (Task 25):
    gold_posture_compute_job      — daily posture row writer

Each job opens its own connection, swallows per-source exceptions so a
partial outage doesn't break the rest of the day's ingest, and commits at
end of work. Functions are testable directly: pass `dsn=...` and the job
runs against that database, no scheduler required.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.sources import uw as uw_sources
from uw_scan.sources.cftc_cot import CftcCotProvider
from uw_scan.sources.comex import ComexProvider
from uw_scan.sources.etf_holdings import EtfHoldingsProvider
from uw_scan.sources.fred import FredProvider
from uw_scan.sources.gpr import GprProvider
from uw_scan.sources.lbma import LbmaProvider
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.sources.uw_gold_options import (
    GOLD_OPTIONS_TICKERS,
    fetch_gold_options_snapshot,
)
from uw_scan.sources.wgc_cb import WgcCbProvider
from uw_scan.sources.wgc_etf import TROY_OZ_PER_TONNE, WgcEtfProvider
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


GOLD_ETF_FLOW_TICKERS = ("GLD", "IAU", "GLDM")

FRED_SERIES_DAILY = [
    "DFII10",
    "DGS10",
    "T10YIE",
    "T5YIFR",
    "DTWEXBGS",
    "BAMLH0A0HYM2",
    "VIXCLS",
    "GVZCLS",
    "DEXCHUS",
    "DEXINUS",
    "DEXJPUS",
    "CBBTCUSD",
]
FRED_SERIES_MONTHLY = ["CPIAUCSL", "M2SL"]

# Series we want stored under a canonical name different from FRED's ID.
# (Currently empty — the LBMA AM/PM gold fix series GOLDAMGBD228NLBM /
# GOLDPMGBD228NLBM both 404 from FRED as of 2026-05-17; gold spot is now
# sourced from massive OHLC via gold_spot_ingest_job.)
FRED_SERIES_ALIASES: dict[str, str] = {}

GOLD_SPOT_TICKER = "GLD"
GOLD_SPOT_SERIES_ID = "GLD_CLOSE"


# --- Daily jobs ---------------------------------------------------------------


def gold_fred_ingest_job(
    *,
    dsn: str,
    series_ids: list[str] | None = None,
    lookback_days: int = 45,
    monthly_lookback_days: int = 400,
) -> None:
    """FRED refresh. Schedule: 17:00 ET daily with the default 45-day window.

    The correlation gauge needs ~5y of overlap with GLD_CLOSE — the warmup CLI
    overrides lookback_days=1825 for the initial backfill. ON CONFLICT keeps
    the daily job idempotent regardless of window."""
    ids = series_ids or FRED_SERIES_DAILY
    monthly_ids = FRED_SERIES_MONTHLY
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, FredProvider() as fred:
        repo = Repository(conn, schema="uw_scan")
        for sid in ids:
            stored_sid = FRED_SERIES_ALIASES.get(sid, sid)
            try:
                rows = [
                    {
                        "series_id": stored_sid,
                        "obs_date": obs.obs_date,
                        "value": obs.value,
                        "release_date": None,
                        "source_url": None,
                    }
                    for obs in fred.fetch_series(
                        sid, start=date.today() - timedelta(days=lookback_days)
                    )
                ]
                repo.insert_macro_series_daily_rows(rows, as_of=now, source="FRED")
            except Exception as exc:
                logger.exception("gold_fred_ingest: series=%s failed: %r", sid, exc)
        for sid in monthly_ids:
            try:
                rows = [
                    {
                        "series_id": obs.series_id,
                        "obs_month": date(obs.obs_date.year, obs.obs_date.month, 1),
                        "value": obs.value,
                        "release_date": None,
                        "source_url": None,
                    }
                    for obs in fred.fetch_series(
                        sid, start=date.today() - timedelta(days=monthly_lookback_days)
                    )
                ]
                repo.insert_macro_series_monthly_rows(rows, as_of=now, source="FRED")
            except Exception as exc:
                logger.exception(
                    "gold_fred_ingest: monthly series=%s failed: %r", sid, exc
                )
        conn.commit()


def gold_gpr_ingest_job(*, dsn: str, lookback_days: int = 45) -> None:
    """GPR refresh. Schedule: 18:35 ET Mon-Fri with the default 45-day window.

    Warmup CLI overrides lookback_days for the initial backfill. Idempotent
    via ON CONFLICT."""
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, GprProvider() as gpr:
        repo = Repository(conn, schema="uw_scan")
        try:
            rows = [
                {
                    "series_id": "GPRD",
                    "obs_date": obs.obs_date,
                    "value": obs.value,
                    "release_date": None,
                    "source_url": "https://www.matteoiacoviello.com/gpr.htm",
                }
                for obs in gpr.fetch_daily(
                    start=date.today() - timedelta(days=lookback_days)
                )
            ]
            repo.insert_macro_series_daily_rows(rows, as_of=now, source="GPR")
        except Exception as exc:
            logger.exception("gold_gpr_ingest failed: %r", exc)
        conn.commit()


def gold_etf_holdings_ingest_job(
    *,
    dsn: str,
    uw_api_key: str | None = None,
    wgc_goldhub_cookie: str | None = None,
    wgc_workbook_path: str | None = None,
    lookback_days: int = 45,
    holdings_lookback_days: int = 400,
    rth_tz: str = "America/New_York",
) -> None:
    """Daily ETF refresh (GLD/IAU/GLDM/PHYS). Schedule: 18:30 ET.

    GLD uses SPDR's daily historical archive workbook. WGC Goldhub monthly
    files backfill GLD/IAU/GLDM/PHYS when an authenticated cookie or exported
    workbook path is provided. UW ETF in/outflow stays on a shorter lookback
    because current entitlement only exposes recent history.
    """
    now = datetime.now(UTC)
    today_et = datetime.now(ZoneInfo(rth_tz)).date()
    holdings_start = today_et - timedelta(days=holdings_lookback_days)
    with psycopg.connect(dsn) as conn, EtfHoldingsProvider() as etf:
        repo = Repository(conn, schema="uw_scan")
        for ticker, fetch_fn, source in [
            ("GLD", etf.fetch_gld, "SPDR"),
            ("IAU", etf.fetch_iau, "iShares"),
            ("GLDM", etf.fetch_gldm, "SPDR"),
            ("PHYS", etf.fetch_phys, "Sprott"),
        ]:
            try:
                rows = [
                    {
                        "ticker": row.ticker,
                        "obs_date": row.obs_date,
                        "holdings_oz": row.holdings_oz,
                        "shares_out": row.shares_out,
                        "nav_per_share": row.nav_per_share,
                        "premium_pct": row.premium_pct,
                    }
                    for row in fetch_fn(start=holdings_start)
                ]
                repo.insert_etf_holdings_daily_rows(rows, as_of=now, source=source)
            except Exception as exc:
                logger.warning(
                    "gold_etf_holdings_ingest: %s skipped (%s)",
                    ticker,
                    repr(exc)[:200],
                )
        if wgc_goldhub_cookie or wgc_workbook_path:
            try:
                with WgcEtfProvider(cookie_header=wgc_goldhub_cookie) as wgc:
                    if wgc_workbook_path:
                        monthly_rows = []
                        for workbook_path in _wgc_workbook_paths(wgc_workbook_path):
                            monthly_rows.extend(
                                wgc.parse_monthly_rows(
                                    workbook_path.read_bytes(),
                                    source_url=workbook_path.resolve().as_uri(),
                                    source_label=workbook_path.name,
                                    start=holdings_start,
                                )
                            )
                    else:
                        monthly_rows = wgc.fetch_monthly_rows(start=holdings_start)
                    corpus_rows = 0
                    for chunk in _chunks([asdict(row) for row in monthly_rows], 5000):
                        corpus_rows += repo.insert_wgc_etf_monthly_rows(
                            chunk, as_of=now, source="WGC"
                        )
                    holdings_rows = 0
                    holdings_values = []
                    for row in monthly_rows:
                        if (
                            row.ticker in {"GLD", "IAU", "GLDM", "PHYS"}
                            and row.holdings_tonnes is not None
                        ):
                            holdings_values.append(
                                {
                                    "ticker": row.ticker,
                                    "obs_date": row.obs_date,
                                    "holdings_oz": row.holdings_tonnes
                                    * TROY_OZ_PER_TONNE,
                                    "shares_out": None,
                                    "nav_per_share": None,
                                    "premium_pct": None,
                                }
                            )
                            holdings_rows += 1
                    repo.insert_etf_holdings_daily_rows(
                        holdings_values, as_of=now, source="WGC"
                    )
                    logger.info(
                        "gold_etf_holdings_ingest: %s WGC monthly rows, %s holdings rows",
                        corpus_rows,
                        holdings_rows,
                    )
            except Exception as exc:
                logger.warning("gold_etf_holdings_ingest: WGC skipped (%s)", repr(exc))
        else:
            logger.info("WGC Goldhub auth/export not provided; skipping WGC ETF ingest")
        if uw_api_key:
            start = (today_et - timedelta(days=lookback_days)).isoformat()
            end = today_et.isoformat()
            with UwClient(
                api_key=uw_api_key,
                timeout=30.0,
                job_name="gold_etf_in_outflow_ingest",
            ) as client:
                run_id = repo.insert_scan_run(
                    ticker="GOLD",
                    notes=f"gold_etf_in_outflow:{end}",
                )
                for ticker in GOLD_ETF_FLOW_TICKERS:
                    try:
                        rows = [
                            {
                                "ticker": row.ticker,
                                "obs_date": row.date,
                                "share_change": row.change,
                                "premium_change_usd": row.change_prem,
                                "close": row.close,
                                "volume": row.volume,
                            }
                            for row in uw_sources.fetch_etf_in_outflow(
                                client=client,
                                repo=repo,
                                run_id=run_id,
                                ticker=ticker,
                                start_date=start,
                                end_date=end,
                            )
                        ]
                        repo.insert_etf_flows_daily_rows(rows, as_of=now, source="UW")
                    except Exception as exc:
                        logger.warning(
                            "gold_etf_in_outflow_ingest: %s skipped (%s)",
                            ticker,
                            repr(exc)[:200],
                        )
        else:
            logger.info("UW API key not provided; skipping gold ETF in/outflow ingest")
        conn.commit()


def _wgc_workbook_paths(raw_path: str) -> list[Path]:
    path = Path(raw_path)
    if path.is_dir():
        return sorted(path.glob("*.xlsx"))
    return [path]


def _chunks(items: list[dict[str, object]], size: int) -> list[list[dict[str, object]]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def gold_spot_ingest_job(
    *,
    dsn: str,
    api_key: str,
    base_url: str = "https://api.massive.com",
    ticker: str = GOLD_SPOT_TICKER,
    series_id: str = GOLD_SPOT_SERIES_ID,
    lookback_days: int = 400,
) -> None:
    """Daily gold-spot ingest via massive OHLC. Schedule: 17:05 ET.

    Pulls GLD daily bars from api.massive.com and persists `close` to
    macro_series_daily under series_id='GLD_CLOSE' — the canonical name
    the gold-posture orchestrator reads for the spot tile, valuation
    percentiles, and correlation-history series. Replaces the retired
    FRED LBMA gold-fix series.
    """
    now = datetime.now(UTC)
    end = date.today()
    start = end - timedelta(days=lookback_days)
    with (
        psycopg.connect(dsn) as conn,
        MassiveOhlcProvider(api_key=api_key, base_url=base_url, timeout=60.0) as ohlc,
    ):
        repo = Repository(conn, schema="uw_scan")
        try:
            bars = ohlc.fetch_daily(ticker, start, end)
            repo.insert_macro_series_daily_rows(
                [
                    {
                        "series_id": series_id,
                        "obs_date": bar.date,
                        "value": bar.close,
                        "release_date": None,
                        "source_url": None,
                    }
                    for bar in bars
                ],
                as_of=now,
                source="MASSIVE",
            )
            logger.info(
                "gold_spot_ingest: %s bars persisted under series_id=%s",
                len(bars),
                series_id,
            )
        except Exception as exc:
            logger.exception("gold_spot_ingest failed: %r", exc)
        conn.commit()


def gold_comex_vault_ingest_job(*, dsn: str) -> None:
    """Daily COMEX vault. Schedule: 17:30 ET.

    Best-effort: CME blocks anonymous scraping of
    cmegroup.com/markets/metals/precious/gold-stocks.html (returns 403
    as of 2026-05-17). Job runs with browser headers but falls through
    if blocked. Re-wire via CME DataMine or another aggregator when one
    is licensed — structural lens's comex_registered_oz stays null
    until then.
    """
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, ComexProvider() as comex:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in comex.fetch_vault(start=date.today() - timedelta(days=45)):
                repo.insert_exchange_inventory_daily(
                    exchange="COMEX",
                    obs_date=row.obs_date,
                    registered_oz=row.registered_oz,
                    eligible_oz=row.eligible_oz,
                    vault_oz=None,
                    as_of=now,
                    source_url=ComexProvider.URL,
                )
        except Exception as exc:
            logger.warning(
                "gold_comex_vault_ingest skipped (CME blocks scraping): %s",
                repr(exc)[:200],
            )
        conn.commit()


def gold_uw_options_ingest_job(
    *,
    dsn: str,
    api_key: str,
    base_url: str = "https://api.unusualwhales.com",
    request_timeout: float = 30.0,
    tickers: tuple[str, ...] = GOLD_OPTIONS_TICKERS,
) -> None:
    """Daily UW gold-options snapshot for GLD/GDX/IAU. Schedule: 17:15 ET.

    Composes existing UW fetchers (interpolated_iv, oi_per_strike,
    option_contracts, skew). One scan_run row groups the per-snapshot
    audit rows; per-ticker exceptions are caught so a single failure
    doesn't kill the batch.
    """
    now = datetime.now(UTC)
    obs_date = date.today()
    with (
        psycopg.connect(dsn) as conn,
        UwClient(
            api_key=api_key,
            base_url=base_url,
            timeout=request_timeout,
            job_name="gold_uw_options_ingest",
        ) as client,
    ):
        repo = Repository(conn, schema="uw_scan")
        run_id = repo.insert_scan_run(
            ticker="GOLD",
            notes=f"gold_options_snapshot:{obs_date.isoformat()}",
        )
        for ticker in tickers:
            try:
                snap = fetch_gold_options_snapshot(
                    client=client,
                    repo=repo,
                    run_id=run_id,
                    ticker=ticker,
                    obs_date=obs_date,
                )
                repo.insert_uw_gold_options_daily(
                    ticker=snap.ticker,
                    obs_date=snap.obs_date,
                    atm_iv_30d=snap.atm_iv_30d,
                    atm_iv_60d=snap.atm_iv_60d,
                    put_25d_iv_30d=snap.put_25d_iv_30d,
                    call_25d_iv_30d=snap.call_25d_iv_30d,
                    skew_25d_30d=snap.skew_25d_30d,
                    put_call_oi_ratio=snap.put_call_oi_ratio,
                    dealer_gamma_est=snap.dealer_gamma_est,
                    as_of=now,
                )
            except Exception as exc:
                logger.exception(
                    "gold_uw_options_ingest: ticker=%s failed: %r", ticker, exc
                )
        repo.finish_scan_run(run_id, status="ok")
        conn.commit()


# --- Weekly + monthly jobs ----------------------------------------------------


def gold_cftc_cot_ingest_job(*, dsn: str) -> None:
    """Weekly CFTC COT (Friday after release)."""
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, CftcCotProvider() as cot:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in cot.fetch_weekly(start=date.today() - timedelta(days=400)):
                repo.insert_cot_gold_weekly(
                    obs_date=row.obs_date,
                    release_date=row.release_date,
                    mm_long=row.mm_long,
                    mm_short=row.mm_short,
                    mm_net=row.mm_net,
                    comm_long=row.comm_long,
                    comm_short=row.comm_short,
                    comm_net=row.comm_net,
                    open_interest=row.open_interest,
                    as_of=now,
                    source_url=CftcCotProvider.URL,
                )
        except Exception as exc:
            logger.exception("gold_cftc_cot_ingest failed: %r", exc)
        conn.commit()


def gold_lbma_vault_ingest_job(*, dsn: str) -> None:
    """Monthly LBMA vault (6th business day of month)."""
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, LbmaProvider() as lbma:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in lbma.fetch_monthly(start=date.today() - timedelta(days=400)):
                repo.insert_exchange_inventory_daily(
                    exchange="LBMA",
                    obs_date=row.obs_date,
                    registered_oz=None,
                    eligible_oz=None,
                    vault_oz=row.vault_oz,
                    as_of=now,
                    source_url=LbmaProvider.URL,
                )
        except Exception as exc:
            logger.exception("gold_lbma_vault_ingest failed: %r", exc)
        conn.commit()


def gold_wgc_cb_ingest_job(
    *,
    dsn: str,
    wgc_goldhub_cookie: str | None = None,
    wgc_workbook_path: str | None = None,
    lookback_days: int | None = 400,
) -> None:
    """Monthly WGC CB reserves (8th business day of month).

    WGC retired the anonymous CSV endpoint (2026-05-17). Use either
    WGC_CB_RESERVES_WORKBOOK_PATH for a local authenticated export or
    WGC_GOLDHUB_COOKIE for an authenticated Goldhub download.
    """
    if not wgc_goldhub_cookie and not wgc_workbook_path:
        logger.info(
            "gold_wgc_cb_ingest: skipped — set WGC_CB_RESERVES_WORKBOOK_PATH "
            "or WGC_GOLDHUB_COOKIE"
        )
        return

    now = datetime.now(UTC)
    with (
        psycopg.connect(dsn) as conn,
        WgcCbProvider(
            cookie_header=wgc_goldhub_cookie,
            workbook_path=wgc_workbook_path,
        ) as wgc,
    ):
        repo = Repository(conn, schema="uw_scan")
        try:
            start = (
                date.today() - timedelta(days=lookback_days) if lookback_days else None
            )
            for row in wgc.fetch_monthly(start=start):
                repo.insert_cb_gold_reserves_monthly(
                    country_iso3=row.country_iso3,
                    obs_month=row.obs_month,
                    reserves_t=row.reserves_t,
                    bucket=row.bucket,
                    is_reported=row.is_reported,
                    is_estimated=row.is_estimated,
                    as_of=now,
                    release_date=now.date(),
                    source=(
                        f"file:{wgc_workbook_path}"
                        if wgc_workbook_path
                        else WgcCbProvider.RESERVES_PAGE_URL
                    ),
                )
        except Exception as exc:
            logger.exception("gold_wgc_cb_ingest failed: %r", exc)
        conn.commit()


# --- Orchestrator job ---------------------------------------------------------


def gold_posture_compute_job(*, dsn: str, as_of: date | None = None) -> None:
    """Compute and persist today's gold_posture_daily row. Schedule: 19:10 ET Mon-Fri.

    After every daily ingest it reads (the last is etf_holdings at 18:30) and BEFORE the
    19:40 macro state compute, which reads the row this writes. The ordering is the
    contract, not the clock -- see tests/unit/worker/test_gold_state_reads_todays_gauge.py.
    """
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        target = as_of or _latest_gold_market_date(repo)
        try:
            compute_and_persist_gold_posture(repo, as_of=target)
            conn.commit()
        except Exception as exc:
            logger.exception("gold_posture_compute failed: %r", exc)
            conn.rollback()


def _latest_gold_market_date(repo: Repository) -> date:
    rows = repo.fetch_macro_series_daily("GLD_CLOSE", to_date=date.today())
    if not rows:
        return date.today()
    return rows[-1]["obs_date"]
