"""Real-data checks for the $50k ledger. Reads option_wizard_local + the lake.
Run: UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
     UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x uv run pytest \
     tests/integration/reports/test_vrp_capital_account_db.py -v
"""

from __future__ import annotations

import os
from datetime import date

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER, backtest_laddered
from uw_scan.storage.repository import Repository

pytestmark = pytest.mark.integration

_HAVE_DB = os.environ.get("UW_SCAN_DB_HOST") and os.environ.get("UW_SCAN_DB_NAME")


@pytest.fixture
def repo_settings():
    if not _HAVE_DB:
        pytest.skip("needs UW_SCAN_DB_HOST/NAME pointing at a vol_index_daily DB")
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='uw_scan' AND table_name='vol_index_daily'"
        )
        if not cur.fetchone():
            conn.close()
            pytest.skip("vol_index_daily not available — run on a DB with real data")
    try:
        yield Repository(conn, schema=settings.db_schema), settings
    finally:
        conn.close()


def test_spy_loads_from_real_data(repo_settings):
    repo, _ = repo_settings
    loaded = load_index_vol(repo, "SPY")
    assert len(loaded.adj) > 2000  # ~2006→ daily bars
    assert any(r["vrp_z_20"] is not None for r in loaded.rows)


def test_dollar_ledger_reconciles_with_backtest_laddered(repo_settings):
    repo, settings = repo_settings
    loaded = load_index_vol(repo, "SPX")
    engine = backtest_laddered(loaded, settings, WINNER, min_date=date(2009, 1, 1))
    # TRULY uncapped: base_risk_pct=0.05 × ~6 overlapping rungs = ~30% peak ≪ 100%, so
    # NOTHING is ever skipped or partial-filled (the constant-multiple proof needs the
    # identical rung set the engine uses). Capital=1e9 makes w=1 floor to ~10^5 contracts
    # → integer-floor noise ≪ the 0.15 tolerance. overlay off, rich_threshold unreachable.
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
        min_date=date(2009, 1, 1),
    )
    res = simulate_account({"SPX": loaded}, settings, cfg)
    m = account_metrics(res, cfg, settings.vrp_risk_free_rate)
    assert res.n_skipped_rungs == 0  # genuinely uncapped → no skips
    assert m["util_peak"] < 0.90  # confirms capital never bound
    assert abs(m["sharpe"] - engine["sharpe"]) < 0.15
