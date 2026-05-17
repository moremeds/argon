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
from datetime import UTC, date, datetime, timedelta

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.sources.cftc_cot import CftcCotProvider
from uw_scan.sources.comex import ComexProvider
from uw_scan.sources.etf_holdings import EtfHoldingsProvider
from uw_scan.sources.fred import FredProvider
from uw_scan.sources.gpr import GprProvider
from uw_scan.sources.lbma import LbmaProvider
from uw_scan.sources.uw_gold_options import (
    GOLD_OPTIONS_TICKERS,
    fetch_gold_options_snapshot,
)
from uw_scan.sources.wgc_cb import WgcCbProvider
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


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


# --- Daily jobs ---------------------------------------------------------------


def gold_fred_ingest_job(*, dsn: str, series_ids: list[str] | None = None) -> None:
    """Daily FRED refresh. Schedule: 17:00 ET."""
    ids = series_ids or FRED_SERIES_DAILY
    monthly_ids = FRED_SERIES_MONTHLY
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, FredProvider() as fred:
        repo = Repository(conn, schema="uw_scan")
        for sid in ids:
            try:
                for obs in fred.fetch_series(
                    sid, start=date.today() - timedelta(days=45)
                ):
                    repo.insert_macro_series_daily(
                        series_id=obs.series_id,
                        obs_date=obs.obs_date,
                        value=obs.value,
                        as_of=now,
                        release_date=None,
                        source="FRED",
                        source_url=None,
                    )
            except Exception as exc:
                logger.exception("gold_fred_ingest: series=%s failed: %r", sid, exc)
        for sid in monthly_ids:
            try:
                for obs in fred.fetch_series(
                    sid, start=date.today() - timedelta(days=400)
                ):
                    repo.insert_macro_series_monthly(
                        series_id=obs.series_id,
                        obs_month=date(obs.obs_date.year, obs.obs_date.month, 1),
                        value=obs.value,
                        as_of=now,
                        release_date=None,
                        source="FRED",
                        source_url=None,
                    )
            except Exception as exc:
                logger.exception(
                    "gold_fred_ingest: monthly series=%s failed: %r", sid, exc
                )
        conn.commit()


def gold_gpr_ingest_job(*, dsn: str) -> None:
    """Daily GPR refresh. Schedule: 20:00 ET."""
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, GprProvider() as gpr:
        repo = Repository(conn, schema="uw_scan")
        try:
            for obs in gpr.fetch_daily(start=date.today() - timedelta(days=45)):
                repo.insert_macro_series_daily(
                    series_id="GPRD",
                    obs_date=obs.obs_date,
                    value=obs.value,
                    as_of=now,
                    release_date=None,
                    source="GPR",
                    source_url="https://www.matteoiacoviello.com/gpr.htm",
                )
        except Exception as exc:
            logger.exception("gold_gpr_ingest failed: %r", exc)
        conn.commit()


def gold_etf_holdings_ingest_job(*, dsn: str) -> None:
    """Daily ETF refresh (GLD/IAU/GLDM/PHYS). Schedule: 18:30 ET."""
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, EtfHoldingsProvider() as etf:
        repo = Repository(conn, schema="uw_scan")
        for ticker, fetch_fn, source in [
            ("GLD", etf.fetch_gld, "SPDR"),
            ("IAU", etf.fetch_iau, "iShares"),
            ("GLDM", etf.fetch_gldm, "SPDR"),
            ("PHYS", etf.fetch_phys, "Sprott"),
        ]:
            try:
                for row in fetch_fn(start=date.today() - timedelta(days=45)):
                    repo.insert_etf_holdings_daily(
                        ticker=row.ticker,
                        obs_date=row.obs_date,
                        holdings_oz=row.holdings_oz,
                        shares_out=row.shares_out,
                        nav_per_share=row.nav_per_share,
                        premium_pct=row.premium_pct,
                        as_of=now,
                        source=source,
                    )
            except Exception as exc:
                logger.exception("gold_etf_holdings_ingest: %s failed: %r", ticker, exc)
        conn.commit()


def gold_comex_vault_ingest_job(*, dsn: str) -> None:
    """Daily COMEX vault. Schedule: 17:30 ET."""
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
            logger.exception("gold_comex_vault_ingest failed: %r", exc)
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


def gold_wgc_cb_ingest_job(*, dsn: str) -> None:
    """Monthly WGC CB reserves (8th business day of month)."""
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, WgcCbProvider() as wgc:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in wgc.fetch_monthly(start=date.today() - timedelta(days=400)):
                repo.insert_cb_gold_reserves_monthly(
                    country_iso3=row.country_iso3,
                    obs_month=row.obs_month,
                    reserves_t=row.reserves_t,
                    bucket=row.bucket,
                    is_reported=row.is_reported,
                    is_estimated=row.is_estimated,
                    as_of=now,
                    release_date=date.today(),
                    source="WGC",
                )
        except Exception as exc:
            logger.exception("gold_wgc_cb_ingest failed: %r", exc)
        conn.commit()


# --- Orchestrator job ---------------------------------------------------------


def gold_posture_compute_job(*, dsn: str, as_of: date | None = None) -> None:
    """Compute and persist today's gold_posture_daily row. Schedule: 21:00 ET
    (after all ingest jobs complete)."""
    target = as_of or date.today()
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        try:
            compute_and_persist_gold_posture(repo, as_of=target)
            conn.commit()
        except Exception as exc:
            logger.exception("gold_posture_compute failed: %r", exc)
            conn.rollback()
