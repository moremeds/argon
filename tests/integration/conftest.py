"""Shared fixtures for tests/integration/{api,worker,...}.

Requires UW_SCAN_TEST_DB_NAME to point at a dedicated test DB. Fixtures
refuse to run otherwise — never touches the developer's working DB.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[2]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME not set; refusing to point integration tests "
            "at the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _reset_and_migrate(settings: Settings) -> None:
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )


@pytest.fixture
def seeded_db_empty_cards() -> Repository:
    """Freshly-migrated test DB + 54-ticker watchlist seed; zero card rows."""
    settings = _test_settings()
    _reset_and_migrate(settings)
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


@pytest.fixture
def seeded_db_with_cards(seeded_db_empty_cards) -> Repository:
    """seeded_db_empty_cards + one scan_run + one watchlist_card for TSLA.

    finished_at = now (fresh) so /api/health reports ok=True.
    """
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run(ticker="TSLA")
    repo.finish_scan_run(run_id, status="ok")
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=run_id,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("445.12"),
        iv_atm=Decimal("0.691"),
        iv_rank=Decimal("39.0"),
    )
    return repo


@pytest.fixture
def latest_tsla_run_id(seeded_db_with_cards) -> int:
    return seeded_db_with_cards.latest_run_id("TSLA")


@pytest.fixture
def seeded_db_with_stale_run(seeded_db_empty_cards) -> Repository:
    """A scan_runs row with finished_at = now - 30 hours.

    Health threshold is 2× the LARGEST expected gap between cron fires (the
    overnight 16:30→04:00 gap, ~11.5h). 30h lag clears that threshold and
    represents a scheduler genuinely down through 2+ expected windows.
    """
    repo = seeded_db_empty_cards
    stale = datetime.now(timezone.utc) - timedelta(hours=30)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.scan_runs (ticker, started_at, finished_at, status)
            VALUES (%s, %s, %s, 'ok')
            """,
            ("TSLA", stale, stale),
        )
    repo.conn.commit()
    return repo


@pytest.fixture
def seed_cri_backtest_run(seeded_db_empty_cards) -> int:
    """Insert one completed CRI run + minimal daily row into the test DB.

    Function-scoped, matching `seeded_db_empty_cards` which drops+migrates
    the schema per test. AUC numbers come from cri_scorers.py constants so a
    calibration PR's diff exposes any staleness. Lives at integration scope
    so both api/ and regime/ tests can depend on it.
    """
    from datetime import date as _date

    from uw_scan.cards.cri_scorers import (
        COMPOSITE_VERSION,
        LAST_KNOWN_AUC_DD5,
        LAST_KNOWN_AUC_DD10,
    )
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    existing = rb.find_latest_run("cri", composite_version=str(COMPOSITE_VERSION))
    if existing is not None:
        return int(existing["id"])

    run_id = rb.insert_run(
        indicator="cri",
        composite_version=str(COMPOSITE_VERSION),
        start_date=_date(2007, 1, 3),
        end_date=_date(2026, 5, 15),
        window_days=150,
        n_days=4873,
        params={"rolling_window": 150, "source": "seed_cri_backtest_run"},
        summary={
            "oos": {
                "as_of": "2026-05-25",
                "notebook": "scripts/backtest_cri.py",
                "method": (
                    "Forward-drawdown labels: dd5 = SPX -5% within 20 sessions; "
                    "dd10 = SPX -10% within 60 sessions."
                ),
                "labels": [
                    {
                        "name": "label_dd5",
                        "definition": "SPX -5% drawdown within 20 trading days",
                    },
                    {
                        "name": "label_dd10",
                        "definition": "SPX -10% drawdown within 60 trading days",
                    },
                ],
                "scores": [
                    {
                        "model": "CRI v1 (frozen baseline)",
                        "auc_dd5": 0.620,
                        "auc_vix30": None,
                        "auc_dd10": 0.647,
                    },
                    {
                        "model": f"CRI v{COMPOSITE_VERSION} (this run)",
                        "auc_dd5": LAST_KNOWN_AUC_DD5,
                        "auc_vix30": None,
                        "auc_dd10": LAST_KNOWN_AUC_DD10,
                    },
                ],
                "versions": [
                    {
                        "label": "CRI v1",
                        "version": 1,
                        "auc_dd5": 0.620,
                        "auc_dd10": 0.647,
                        "n_observations": 4873,
                        "notes": "Frozen baseline.",
                    },
                    {
                        "label": f"CRI v{COMPOSITE_VERSION}",
                        "version": COMPOSITE_VERSION,
                        "auc_dd5": LAST_KNOWN_AUC_DD5,
                        "auc_dd10": LAST_KNOWN_AUC_DD10,
                        "n_observations": 4873,
                        "notes": (
                            "Recorded by scripts/backtest_cri.py against the 20y "
                            "vol_index_daily history. Bumping COMPOSITE_VERSION "
                            "in cri_scorers.py requires updating LAST_KNOWN_AUC_* "
                            "in the same diff."
                        ),
                    },
                ],
                "interpretation": (
                    "Seed reads LAST_KNOWN_AUC_* from cri_scorers.py — "
                    "calibration-provenance contract enforced in PR review."
                ),
            },
            "extras": {"named_crash_hits": {}, "fired_count": 0},
        },
        note="seed_cri_backtest_run fixture",
    )
    rb.bulk_insert_daily(
        run_id,
        [
            {
                "trade_date": _date(2026, 5, 15),
                "score": 12.0,
                "level": "LOW",
                "payload": {},
            }
        ],
    )
    rb.mark_run_completed(run_id)
    return run_id


@pytest.fixture
def seed_vcg_backtest_run(seeded_db_empty_cards) -> int:
    """Insert one completed VCG run + minimal daily row into the test DB.

    Function-scoped, matching seeded_db_empty_cards. Mirrors the shape that
    scripts/backtest_vcg.py persists — named_crash_window is
    dict[iso_str, list[dict]] with offset_d (not offset_days) keys.
    """
    from datetime import date as _date

    from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION as VCG_COMPOSITE_VERSION
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    existing = rb.find_latest_run("vcg", composite_version=str(VCG_COMPOSITE_VERSION))
    if existing is not None:
        return int(existing["id"])

    def _row(off: int, interp: str, vcg: float) -> dict:
        return {
            "offset_d": off,
            "vcg": vcg,
            "vcg_adj": vcg,
            "beta1": -0.02,
            "beta2": -0.04,
            "sign_ok": True,
            "interpretation": interp,
            "vix": 25.0,
        }

    run_id = rb.insert_run(
        indicator="vcg",
        composite_version=str(VCG_COMPOSITE_VERSION),
        start_date=_date(2007, 1, 3),
        end_date=_date(2026, 5, 15),
        window_days=21,
        n_days=4708,
        params={"window": 21, "proxy": "HYG", "source": "seed_vcg_backtest_run"},
        summary={
            "oos": None,
            "extras": {
                "credit_proxy": "HYG",
                "use_adj_close": True,
                "named_crash_window": {
                    "2008-09-15": [
                        _row(-5, "NORMAL", -0.50),
                        _row(-3, "NORMAL", -0.40),
                        _row(-1, "SUPPRESSED", 0.20),
                        _row(0, "BOUNCE", 0.30),
                        _row(1, "SUPPRESSED", 0.10),
                        _row(3, "RISK_OFF", -2.10),
                        _row(5, "NORMAL", -0.30),
                    ],
                },
                "interpretation_distribution": {
                    "NORMAL": 2160,
                    "SUPPRESSED": 2450,
                    "EDR": 50,
                    "RISK_OFF": 30,
                    "PANIC": 18,
                },
                "ro_count": 30,
                "edr_count": 50,
                "bounce_count": 0,
            },
        },
        note="seed_vcg_backtest_run fixture",
    )
    # Daily rows include three stress-level entries so /vcg-validation can
    # exercise the stress_history filter. Dates ascending in storage; the
    # endpoint reverses to most-recent-first.
    rb.bulk_insert_daily(
        run_id,
        [
            {
                "trade_date": _date(2024, 1, 15),
                "score": -2.40,
                "level": "PANIC",
                "payload": {
                    "vcg_adj": -2.40,
                    "pi_panic": 1.20,
                    "sign_ok": True,
                    "vix": 80.86,
                    "vvix": 110.15,
                    "vix_percentile_rank": 0.992,
                    "vvix_percentile_rank": 0.985,
                },
            },
            {
                "trade_date": _date(2024, 3, 1),
                "score": -1.85,
                "level": "RISK_OFF",
                "payload": {
                    "vcg_adj": -1.85,
                    "pi_panic": 0.50,
                    "sign_ok": True,
                    "vix": 28.4,
                    "vvix": 105.2,
                    "vix_percentile_rank": 0.71,
                    "vvix_percentile_rank": 0.65,
                },
            },
            {
                "trade_date": _date(2024, 6, 10),
                "score": -1.20,
                "level": "EDR",
                "payload": {
                    "vcg_adj": -1.20,
                    "pi_panic": 0.0,
                    "sign_ok": True,
                    "vix": 18.5,
                    "vvix": 95.0,
                    "vix_percentile_rank": 0.42,
                    "vvix_percentile_rank": 0.38,
                },
            },
            {
                "trade_date": _date(2026, 5, 15),
                "score": -0.5,
                "level": "NORMAL",
                "payload": {},
            },
        ],
    )
    rb.mark_run_completed(run_id)
    return run_id


@pytest.fixture
def seeded_db_with_ohlc(seeded_db_empty_cards) -> Repository:
    repo = seeded_db_empty_cards
    today = datetime.now(timezone.utc).date()
    for i in range(30):
        repo.upsert_daily_ohlc(
            ticker="AAPL",
            date=today - timedelta(days=29 - i),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal(str(100 + i)),
            volume=10_000_000,
            source="massive.com",
        )
    return repo
