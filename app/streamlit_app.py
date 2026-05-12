"""Streamlit entrypoint for the UW scanner.

Sidebar exposes a page selector — "Single Stock" (S1) or "Full Scan" (S2).
The pipelines are gated behind explicit button presses so Streamlit's
re-execution model never triggers live runs on stray interactions.
"""

from __future__ import annotations

import logging

# Ensure src/ is importable when run directly
import sys
from pathlib import Path

import psycopg
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from uw_scan.api.client import LiveDataUnavailable, UwClient  # noqa: E402
from uw_scan.config import Settings  # noqa: E402
from uw_scan.pipeline import run_full_scan, run_single_stock  # noqa: E402
from uw_scan.reports.scan import assemble_scan_report  # noqa: E402
from uw_scan.reports.single_stock import assemble_single_stock_report  # noqa: E402
from uw_scan.storage.repository import Repository  # noqa: E402

# Make the views package importable
APP_ROOT = REPO_ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from views.scan_view import render as render_scan  # noqa: E402
from views.single_stock_view import render as render_single_stock  # noqa: E402

logging.basicConfig(level=logging.INFO)


@st.cache_resource
def _settings() -> Settings | None:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        logging.exception("Settings.from_env failed: %s", repr(exc))
        st.error(f"Config error: {exc}")
        return None


def _open_conn(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(settings.db_dsn())


def _run_single_stock_page(settings: Settings) -> None:
    st.title("UW Scanner — Single-Stock Card (S1)")

    with st.sidebar:
        st.header("Run settings")
        api_key_present = bool(settings.api_key.get_secret_value())
        st.markdown(f"**API key**: {'present' if api_key_present else 'missing'}")
        st.markdown(f"**DB**: {settings.db_host}:{settings.db_port}/{settings.db_name}")
        ticker = st.text_input("Ticker", value="TSLA").strip().upper()
        run_clicked = st.button("Run live pipeline", type="primary")
        load_clicked = st.button("Load latest snapshot")
        manual_run_id = st.number_input(
            "Or load specific run_id", min_value=0, value=0, step=1
        )

    if not ticker:
        st.warning("Enter a ticker in the sidebar.")
        return

    if run_clicked:
        with st.spinner(f"Running live pipeline for {ticker}…"):
            conn = _open_conn(settings)
            try:
                repo = Repository(conn, schema=settings.db_schema)
                with UwClient(
                    api_key=settings.api_key.get_secret_value(),
                    base_url=settings.base_url,
                    timeout=settings.request_timeout_seconds,
                ) as client:
                    report = run_single_stock(ticker, client, repo)
                st.success(f"Run {report.run_id} complete for {ticker}.")
                render_single_stock(report)
            except LiveDataUnavailable as exc:
                logging.exception("live data unavailable: %s", repr(exc))
                st.error(f"Live data unavailable: {exc}")
            except Exception as exc:  # noqa: BLE001
                logging.exception("pipeline failed: %s", repr(exc))
                st.error(f"Pipeline failed: {exc!r}")
            finally:
                conn.close()
        return

    if load_clicked or manual_run_id:
        conn = _open_conn(settings)
        try:
            repo = Repository(conn, schema=settings.db_schema)
            run_id = int(manual_run_id) if manual_run_id else repo.latest_run_id(ticker)
            if run_id == 0:
                st.warning(f"No prior runs found for {ticker}.")
            else:
                report = assemble_single_stock_report(ticker, run_id, repo)
                st.info(f"Loaded snapshot run_id={run_id}.")
                render_single_stock(report)
        finally:
            conn.close()


def _run_deep_dive(settings: Settings, ticker: str) -> None:
    """Invoked by scan_view when the user clicks 'deep-dive'. Runs S1 pipeline."""
    st.session_state["__deep_dive_ticker__"] = ticker
    with st.spinner(f"Running S1 deep-dive on {ticker}…"):
        conn = _open_conn(settings)
        try:
            repo = Repository(conn, schema=settings.db_schema)
            with UwClient(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                timeout=settings.request_timeout_seconds,
            ) as client:
                report = run_single_stock(ticker, client, repo)
            st.success(f"Deep-dive complete: run {report.run_id} for {ticker}.")
            render_single_stock(report)
        except LiveDataUnavailable as exc:
            logging.exception("deep-dive live data unavailable: %s", repr(exc))
            st.error(f"Live data unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001
            logging.exception("deep-dive failed: %s", repr(exc))
            st.error(f"Deep-dive failed: {exc!r}")
        finally:
            conn.close()


def _run_full_scan_page(settings: Settings) -> None:
    st.title("UW Scanner — Full Scan Report (S2)")

    with st.sidebar:
        st.header("Run settings")
        api_key_present = bool(settings.api_key.get_secret_value())
        st.markdown(f"**API key**: {'present' if api_key_present else 'missing'}")
        st.markdown(f"**DB**: {settings.db_host}:{settings.db_port}/{settings.db_name}")
        run_clicked = st.button("Run full scan (live)", type="primary")
        load_clicked = st.button("Load latest scan")
        manual_run_id = st.number_input(
            "Or load specific scan run_id", min_value=0, value=0, step=1
        )

    if run_clicked:
        with st.spinner("Running full scan against UW…"):
            conn = _open_conn(settings)
            try:
                repo = Repository(conn, schema=settings.db_schema)
                with UwClient(
                    api_key=settings.api_key.get_secret_value(),
                    base_url=settings.base_url,
                    timeout=settings.request_timeout_seconds,
                ) as client:
                    report = run_full_scan(client, repo)
                st.success(f"Scan run {report.run_id} complete.")
                render_scan(
                    report,
                    on_deep_dive=lambda t: _run_deep_dive(settings, t),
                )
            except LiveDataUnavailable as exc:
                logging.exception("scan live data unavailable: %s", repr(exc))
                st.error(f"Live data unavailable: {exc}")
            except Exception as exc:  # noqa: BLE001
                logging.exception("scan failed: %s", repr(exc))
                st.error(f"Scan failed: {exc!r}")
            finally:
                conn.close()
        return

    if load_clicked or manual_run_id:
        conn = _open_conn(settings)
        try:
            repo = Repository(conn, schema=settings.db_schema)
            run_id = int(manual_run_id) if manual_run_id else repo.latest_scan_run_id()
            if run_id == 0:
                st.warning("No prior full-scan runs found.")
            else:
                report = assemble_scan_report(run_id, repo)
                st.info(f"Loaded scan run_id={run_id}.")
                render_scan(
                    report,
                    on_deep_dive=lambda t: _run_deep_dive(settings, t),
                )
        finally:
            conn.close()


def main() -> None:
    st.set_page_config(page_title="UW Scanner", layout="wide")
    settings = _settings()

    with st.sidebar:
        page = st.radio("Page", ["Single Stock", "Full Scan"], index=0)

    if settings is None:
        st.error("Settings not loaded. Check .env for UW_SCAN_API_KEY.")
        return

    if page == "Single Stock":
        _run_single_stock_page(settings)
    else:
        _run_full_scan_page(settings)


if __name__ == "__main__":
    main()
else:
    # Streamlit calls the script as a module — invoke main() at import time.
    main()
