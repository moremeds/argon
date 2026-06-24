"""Shared fixtures for tests/integration/{api,worker,...}.

Requires UW_SCAN_TEST_DB_NAME to point at a dedicated test DB. Fixtures
refuse to run otherwise — never touches the developer's working DB.

Performance design
------------------
Previously every test fixture re-ran ``bash scripts/migrate.sh``, which
paid ~150ms of ``uv run python`` startup + ~30ms × 82 of ``psql`` fork-
and-connect per fixture invocation. Across the integration suite this
was ~2-5s per test → many minutes of pure setup overhead per CI shard.

Now we migrate once per pytest session, snapshot the post-migration
baseline via ``COPY`` (which natively handles JSONB, TEXT[], custom
enums, etc.), and per test ``TRUNCATE ... CASCADE`` + ``COPY`` the
baseline back. Sequence positions are restored via ``setval`` so
test-issued IDs remain deterministic across resets.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.models import MarketAggregates
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config: pytest.Config) -> None:
    """Give each pytest-xdist worker its own test database.

    Workers run in parallel processes and every test resets the shared `uw_scan`
    schema, so they would clobber each other. A per-worker SCHEMA can't isolate them
    either — migrations hardcode `SET search_path TO uw_scan` — so each worker gets its
    own DATABASE. We mutate the UW_SCAN_TEST_DB_NAME env var (rather than one fixture)
    so EVERY test-DB reader inherits the gwN name: this conftest, api/conftest, and the
    ~20 recorder/job/storage tests that read os.environ['UW_SCAN_TEST_DB_NAME'] directly.
    No-op without xdist (single worker → base DB, unchanged behaviour).
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    base = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not worker or not base or base.endswith(f"_{worker}"):
        return
    per_worker = f"{base}_{worker}"
    os.environ["UW_SCAN_TEST_DB_NAME"] = per_worker
    _create_worker_db(per_worker)


def _create_worker_db(name: str) -> None:
    """CREATE DATABASE <name> if absent (no-op when it exists). Needs CREATEDB — CI's
    postgres superuser and a local superuser both have it. The identifier is
    interpolated (Postgres can't parameterise a database name) but is derived from a
    fixed env value + the xdist worker id, never user input."""
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    maint = Settings.from_env().model_copy(update={"db_name": "postgres"})
    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{name}"')


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


@pytest.fixture(scope="session")
def _migrated_settings() -> Settings:
    """Drop+migrate the test schema once per pytest session.

    This is the big perf lever: the 82-file migration runs once per
    session instead of once per test. ``seeded_db_empty_cards`` below
    delivers per-test isolation via TRUNCATE+COPY against the snapshot
    captured in ``_baseline_snapshot``.

    Under xdist each worker runs its own session against its own gwN database
    (set up by ``pytest_configure``), so this migrates once per worker.
    """
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
        apply_migrations(conn, log=lambda _msg: None)
    return settings


@pytest.fixture(scope="session")
def _baseline_snapshot(_migrated_settings: Settings) -> dict[str, Any]:
    """Capture the post-migration state once.

    ``COPY ... TO STDOUT`` is used because it round-trips every column
    type Postgres supports (JSONB, TEXT[], enums, tstzrange, ...) without
    needing per-column psycopg adapter registration. Sequence positions
    are captured separately so we can restore them with ``setval`` after
    TRUNCATE wipes them back to 1.
    """
    settings = _migrated_settings
    tables: list[str] = []
    table_dumps: dict[str, bytes] = {}
    sequences: dict[str, tuple[int, bool]] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'uw_scan' ORDER BY tablename"
            )
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                buf = io.BytesIO()
                with cur.copy(f'COPY uw_scan."{t}" TO STDOUT') as copy:
                    for chunk in copy:
                        buf.write(bytes(chunk))
                table_dumps[t] = buf.getvalue()
            cur.execute(
                "SELECT sequence_name FROM information_schema.sequences "
                "WHERE sequence_schema = 'uw_scan' ORDER BY sequence_name"
            )
            seq_names = [r[0] for r in cur.fetchall()]
            for s in seq_names:
                cur.execute(f'SELECT last_value, is_called FROM uw_scan."{s}"')
                row = cur.fetchone()
                sequences[s] = (int(row[0]), bool(row[1]))
    return {"tables": tables, "dumps": table_dumps, "sequences": sequences}


def _reset_to_baseline(
    conn: psycopg.Connection,
    snapshot: dict[str, Any],
) -> None:
    """Restore the post-migration baseline on ``conn``."""
    tables: list[str] = snapshot["tables"]
    dumps: dict[str, bytes] = snapshot["dumps"]
    sequences: dict[str, tuple[int, bool]] = snapshot["sequences"]
    with conn.cursor() as cur:
        if tables:
            quoted = ", ".join(f'uw_scan."{t}"' for t in tables)
            cur.execute(f"TRUNCATE {quoted} CASCADE")
        for t in tables:
            data = dumps[t]
            if not data:
                continue
            with cur.copy(f'COPY uw_scan."{t}" FROM STDIN') as copy:
                copy.write(data)
        for s, (last_value, is_called) in sequences.items():
            cur.execute(
                f"SELECT setval('uw_scan.\"{s}\"', %s, %s)",
                (last_value, is_called),
            )


@pytest.fixture
def seeded_db_empty_cards(
    _migrated_settings: Settings,
    _baseline_snapshot: dict[str, Any],
) -> Iterator[Repository]:
    """Freshly-migrated test DB + 54-ticker watchlist seed; zero card rows."""
    settings = _migrated_settings
    conn = psycopg.connect(settings.db_dsn())
    try:
        _reset_to_baseline(conn, _baseline_snapshot)
        conn.commit()
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
    # A real full_scan persists its aggregates; latest_run_id keys on this to
    # distinguish canonical runs from side-channel ones (see scan_runs.py).
    repo.set_aggregates(
        run_id, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
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
