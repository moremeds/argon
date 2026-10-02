"""M2 emitter sites — every site reads prev persisted state BEFORE writing,
then emits an `mcp_event` row only on a real change.

Per site the contract is two-sided: a differing prior state produces exactly
one row; the same state produces none (the second case is what catches
read-after-write — `insert_snapshot` self-commits, so a read placed after it
would compare the row to itself and never emit).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied
from uw_scan import alerts
from uw_scan.config import Settings
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.scanners.live_quotes import LiveQuote
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.regime_live import regime_live_scan_once
from uw_scan.worker.jobs.vrp_macro_signal import vrp_macro_signal_refresh

pytestmark = pytest.mark.integration


def _events(conn: psycopg.Connection) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind, subject, basis, payload FROM uw_scan.mcp_event ORDER BY id"
        )
        return cur.fetchall()


def _seed_vol(
    vol_repo: VolIndexRepository,
    symbol: str,
    values: list[float],
    *,
    start: date,
) -> None:
    vol_repo.upsert_rows(
        [
            {
                "symbol": symbol,
                "trade_date": start + timedelta(days=i),
                "open": v,
                "high": v,
                "low": v,
                "close": v,
                "adj_close": v,
                "volume": 0,
            }
            for i, v in enumerate(values)
        ]
    )


_CRI_SEED_START = date(2026, 1, 1)
_CRI_SEED_DAYS = 140  # > cri MIN_ALIGNED_BARS (120)


def _seed_cri_inputs(repo) -> None:
    vol_repo = VolIndexRepository(repo.conn, schema=repo._schema)
    for sym, base in (("VIX", 16.0), ("VVIX", 95.0), ("COR1M", 20.0)):
        _seed_vol(vol_repo, sym, [base] * _CRI_SEED_DAYS, start=_CRI_SEED_START)
    _seed_vol(
        vol_repo,
        "SPX",
        [4500.0 + i for i in range(_CRI_SEED_DAYS)],
        start=_CRI_SEED_START,
    )


_VCG_SEED_DAYS = 120  # > vcg MIN_ALIGNED_BARS (94)


def _seed_vcg_inputs(repo) -> None:
    vol_repo = VolIndexRepository(repo.conn, schema=repo._schema)
    n = _VCG_SEED_DAYS
    _seed_vol(
        vol_repo,
        "VIX",
        [16.0 + 0.05 * (i % 7) for i in range(n)],
        start=_CRI_SEED_START,
    )
    _seed_vol(
        vol_repo,
        "VVIX",
        [90.0 + 0.3 * (i % 11) for i in range(n)],
        start=_CRI_SEED_START,
    )
    _seed_vol(
        vol_repo,
        "HYG",
        [80.0 - 0.02 * i + 0.05 * (i % 5) for i in range(n)],
        start=_CRI_SEED_START,
    )


def _seed_prior_cri(repo, level: str, *, basis: str) -> None:
    CriSnapshotRepository(repo.conn, schema=repo._schema).insert_snapshot(
        payload={"cri": {"level": level}},
        data_date=_CRI_SEED_START,
        basis=basis,
    )


def _seed_prior_vcg(repo, regime: str, *, basis: str) -> None:
    VcgSnapshotRepository(repo.conn, schema=repo._schema).insert_snapshot(
        payload={"signal": {"regime": regime}, "credit_proxy": "HYG"},
        data_date=_CRI_SEED_START,
        basis=basis,
    )


_LIVE_QUOTED = datetime(2026, 6, 12, 15, 30, tzinfo=timezone.utc)  # Friday RTH


def test_cri_eod_emits_on_level_change(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "CRITICAL", basis="eod")

    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None

    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("cri_regime", "CRI", "eod")
    assert payload["from"] == "CRITICAL"
    assert payload["to"] in {"LOW", "ELEVATED", "HIGH", "CRITICAL"}
    assert payload["to"] != "CRITICAL"


def test_cri_eod_same_level_emits_nothing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)

    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert _events(repo.conn) == []


def test_cri_eod_gap_recovery_never_emits(seeded_db_empty_cards) -> None:
    """as_of runs (recover_recent_gaps) must not emit — the event stream is a
    live-state feed, not a backfill replay."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "CRITICAL", basis="eod")

    as_of = _CRI_SEED_START + timedelta(days=_CRI_SEED_DAYS - 1)
    assert cri_scanner.run(repo.conn, schema=repo._schema, as_of=as_of) is not None
    assert _events(repo.conn) == []


def test_cri_live_emits_on_level_change(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "CRITICAL", basis="live")
    quotes = {
        "SPX": LiveQuote("SPX", 4600.0, _LIVE_QUOTED, "xenon_ws"),
    }

    assert (
        cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
        is not None
    )
    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("cri_regime", "CRI", "live")
    assert payload["from"] == "CRITICAL"

    # Same level again — and still inside the 1h cooldown — emits nothing.
    assert (
        cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
        is not None
    )
    assert len(_events(repo.conn)) == 1


def test_cri_live_same_level_emits_nothing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    quotes = {
        "SPX": LiveQuote("SPX", 4600.0, _LIVE_QUOTED, "xenon_ws"),
    }

    # First run: prev=None is not a change. Second: level unchanged.
    assert (
        cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
        is not None
    )
    assert (
        cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
        is not None
    )
    assert _events(repo.conn) == []


def test_vcg_eod_emits_on_regime_change(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_vcg_inputs(repo)
    _seed_prior_vcg(repo, "PANIC", basis="eod")

    assert vcg_scanner.run(repo.conn, proxy="HYG", schema=repo._schema) is not None

    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("vcg_regime", "HYG", "eod")
    assert payload["from"] == "PANIC"
    assert payload["to"] != "PANIC"


def test_vcg_eod_same_regime_emits_nothing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_vcg_inputs(repo)

    assert vcg_scanner.run(repo.conn, proxy="HYG", schema=repo._schema) is not None
    assert vcg_scanner.run(repo.conn, proxy="HYG", schema=repo._schema) is not None
    assert _events(repo.conn) == []


def test_vcg_live_emits_on_regime_change(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_vcg_inputs(repo)
    _seed_prior_vcg(repo, "PANIC", basis="live")
    quotes = {
        "HYG": LiveQuote("HYG", 79.5, _LIVE_QUOTED, "xenon_ws"),
    }

    assert (
        vcg_scanner.run_live(
            repo.conn,
            schema=repo._schema,
            quotes=quotes,
            proxy="HYG",
            persist=True,
        )
        is not None
    )
    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("vcg_regime", "HYG", "live")
    assert payload["from"] == "PANIC"


def test_vcg_live_same_regime_emits_nothing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_vcg_inputs(repo)
    quotes = {
        "HYG": LiveQuote("HYG", 79.5, _LIVE_QUOTED, "xenon_ws"),
    }

    assert (
        vcg_scanner.run_live(
            repo.conn,
            schema=repo._schema,
            quotes=quotes,
            proxy="HYG",
            persist=True,
        )
        is not None
    )
    assert (
        vcg_scanner.run_live(
            repo.conn,
            schema=repo._schema,
            quotes=quotes,
            proxy="HYG",
            persist=True,
        )
        is not None
    )
    assert _events(repo.conn) == []


def _flip_stored_action(repo, *, basis: str) -> str:
    """Rewrite the stored SPX action to the opposite of what the run produced,
    so the next refresh sees a genuine transition."""
    row = repo.fetch_latest_vrp_macro_signals(["SPX"], basis=basis)[0]
    other = "SKIP" if row["action"] == "TRADE" else "TRADE"
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.vrp_macro_signal_daily SET action = %s "
            "WHERE name = 'SPX' AND basis = %s",
            (other, basis),
        )
    repo.conn.commit()
    return other


def test_vrp_eod_job_emits_on_action_change(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    settings = Settings.from_env()

    out = vrp_macro_signal_refresh(
        repo=repo,
        settings=settings,
        snapshot_date=date(2026, 6, 22),
        names=("SPX",),
    )
    assert out["persisted"] == 1
    assert _events(repo.conn) == []  # first-ever row is not a change

    prev = _flip_stored_action(repo, basis="eod")
    out = vrp_macro_signal_refresh(
        repo=repo,
        settings=settings,
        snapshot_date=date(2026, 6, 22),
        names=("SPX",),
    )
    assert out["persisted"] == 1

    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("vrp_macro_signal", "SPX", "eod")
    assert payload["from"] == prev
    assert payload["to"] != prev

    # A third run on the now-same state adds nothing.
    vrp_macro_signal_refresh(
        repo=repo,
        settings=settings,
        snapshot_date=date(2026, 6, 22),
        names=("SPX",),
    )
    assert len(_events(repo.conn)) == 1


def test_vrp_eod_job_same_action_emits_nothing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    settings = Settings.from_env()

    for _ in range(2):
        out = vrp_macro_signal_refresh(
            repo=repo,
            settings=settings,
            snapshot_date=date(2026, 6, 22),
            names=("SPX",),
        )
        assert out["persisted"] == 1
    assert _events(repo.conn) == []


def test_vrp_eod_emit_failure_keeps_upserts(seeded_db_empty_cards, monkeypatch) -> None:
    """An emit that raises must not cost the staged upserts: the savepoint
    rolls back only the event row and the job still commits the signal."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    settings = Settings.from_env()

    vrp_macro_signal_refresh(
        repo=repo,
        settings=settings,
        snapshot_date=date(2026, 6, 22),
        names=("SPX",),
    )
    flipped = _flip_stored_action(repo, basis="eod")

    def _boom(*_a, **_k):
        raise RuntimeError("emit exploded")

    monkeypatch.setattr("uw_scan.worker.jobs.vrp_macro_signal.emit_on_change", _boom)
    out = vrp_macro_signal_refresh(
        repo=repo,
        settings=settings,
        snapshot_date=date(2026, 6, 22),
        names=("SPX",),
    )
    assert out["persisted"] == 1
    rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
    assert len(rows) == 1
    assert rows[0]["action"] != flipped  # second upsert committed
    assert _events(repo.conn) == []


def test_regime_live_vrp_leg_emits_on_action_change(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _LIVE_QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _LIVE_QUOTED, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    settings = Settings.from_env()

    summary = regime_live_scan_once(
        repo, settings, now=_LIVE_QUOTED + timedelta(minutes=1)
    )
    assert summary["vrp"] == "ok"
    assert _events(repo.conn) == []  # first-ever live row is not a change

    prev = _flip_stored_action(repo, basis="live")
    summary = regime_live_scan_once(
        repo, settings, now=_LIVE_QUOTED + timedelta(minutes=2)
    )
    assert summary["vrp"] == "ok"

    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("vrp_macro_signal", "SPX", "live")
    assert payload["from"] == prev
    assert payload["to"] != prev


def test_regime_live_vrp_leg_same_action_emits_nothing(
    seeded_db_empty_cards,
) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _LIVE_QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _LIVE_QUOTED, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    settings = Settings.from_env()

    for minute in (1, 2):
        summary = regime_live_scan_once(
            repo, settings, now=_LIVE_QUOTED + timedelta(minutes=minute)
        )
        assert summary["vrp"] == "ok"
    assert _events(repo.conn) == []


def test_send_alert_emits_ops_event_without_webhook(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """No webhook configured still emits — and the return value keeps meaning
    'webhook delivered' (False here)."""
    repo = seeded_db_empty_cards
    # Point send_alert's own autocommit conn at THIS test DB — including the
    # per-worker gwN suffix pytest-xdist assigns under parallel runs.
    monkeypatch.setenv("UW_SCAN_DB_NAME", os.environ["UW_SCAN_TEST_DB_NAME"])
    monkeypatch.setattr(alerts, "_webhook_url", lambda: "")

    assert alerts.send_alert("worker died", "full_scan streak=3") is False

    events = _events(repo.conn)
    assert len(events) == 1
    kind, subject, basis, payload = events[0]
    assert (kind, subject, basis) == ("ops", "worker died", "ops")
    assert payload["message"] == "full_scan streak=3"
