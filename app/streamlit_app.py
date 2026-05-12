"""Streamlit entrypoint for the UW Single-Stock Card (S1).

Sidebar exposes the ticker + run/reload controls. The pipeline is gated behind an
explicit button press to keep Streamlit's re-execution model from triggering
expensive live runs on every interaction.
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
from uw_scan.pipeline import run_single_stock  # noqa: E402
from uw_scan.reports.single_stock import assemble_single_stock_report  # noqa: E402
from uw_scan.storage.repository import Repository  # noqa: E402

# Make the views package importable
APP_ROOT = REPO_ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from views.single_stock_view import render as render_single_stock  # noqa: E402

logging.basicConfig(level=logging.INFO)


@st.cache_resource
def _settings() -> Settings | None:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        st.error(f"Config error: {exc}")
        return None


def _open_conn(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(settings.db_dsn())


def main() -> None:
    st.set_page_config(page_title="UW Single-Stock Card", layout="wide")
    st.title("UW Scanner — Single-Stock Card (S1)")

    settings = _settings()

    with st.sidebar:
        st.header("Run settings")
        if settings is None:
            st.error("Settings not loaded. Check .env for UW_SCAN_API_KEY.")
            return

        api_key_present = bool(settings.api_key.get_secret_value())
        st.markdown(f"**API key**: {'✓ present' if api_key_present else '✗ missing'}")
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
            try:
                conn = _open_conn(settings)
                repo = Repository(conn, schema=settings.db_schema)
                with UwClient(
                    api_key=settings.api_key.get_secret_value(),
                    base_url=settings.base_url,
                    timeout=settings.request_timeout_seconds,
                ) as client:
                    report = run_single_stock(ticker, client, repo)
                conn.close()
                st.success(f"Run {report.run_id} complete for {ticker}.")
                render_single_stock(report)
            except LiveDataUnavailable as exc:
                logging.exception("live data unavailable: %s", repr(exc))
                st.error(f"Live data unavailable: {exc}")
            except Exception as exc:  # noqa: BLE001
                logging.exception("pipeline failed: %s", repr(exc))
                st.error(f"Pipeline failed: {exc!r}")
        return

    if load_clicked or manual_run_id:
        conn = _open_conn(settings)
        repo = Repository(conn, schema=settings.db_schema)
        try:
            run_id = (
                int(manual_run_id) if manual_run_id else _latest_run_id(repo, ticker)
            )
            if run_id == 0:
                st.warning(f"No prior runs found for {ticker}.")
            else:
                report = assemble_single_stock_report(ticker, run_id, repo)
                st.info(f"Loaded snapshot run_id={run_id}.")
                render_single_stock(report)
        finally:
            conn.close()


def _latest_run_id(repo: Repository, ticker: str) -> int:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT run_id FROM {repo._schema}.scan_runs "  # noqa: SLF001
            "WHERE ticker = %s ORDER BY run_id DESC LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


if __name__ == "__main__":
    main()
else:
    # Streamlit calls the script as a module — invoke main() at import time.
    main()
