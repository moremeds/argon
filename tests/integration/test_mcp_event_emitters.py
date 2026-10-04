"""M2 emitter sites — every site reads prev persisted state BEFORE writing,
then emits an `mcp_event` row only on a real change.

Per site the contract is two-sided: a differing prior state produces exactly
one row; the same state produces none (the second case is what catches
read-after-write — `insert_snapshot` self-commits, so a read placed after it
would compare the row to itself and never emit).
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied
from uw_scan import alerts
from uw_scan.cards.cri_scoring import run_analysis as _cri_run_analysis
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_signal import (
    current_macro_signal as _vrp_current_macro_signal,
)
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.scanners.live_quotes import LiveQuote
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.mcp_events import emit_event, emit_on_change
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


def _seed_emitted_event(
    conn: psycopg.Connection,
    *,
    kind: str,
    subject: str,
    basis: str,
    to: object,
    from_: object = None,
    age_hours: float | None = None,
) -> int:
    """A real committed `mcp_event` row — the emitter's own record of the last
    state the stream told subscribers about. ``age_hours`` pushes emitted_at
    back so a live-cooldown site lets the recovered emit through."""
    new_id = emit_event(
        conn,
        kind=kind,
        subject=subject,
        basis=basis,
        payload={"from": from_, "to": to},
    )
    assert new_id is not None
    if age_hours:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE uw_scan.mcp_event "
                "SET emitted_at = now() - %s * interval '1 hour' WHERE id = %s",
                (age_hours, new_id),
            )
    conn.commit()
    return new_id


def _fail_emit_once(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Patch the emit_on_change reference at ``target`` to raise on its first
    call only — a crashed emit after the snapshot row already committed."""
    calls = {"n": 0}

    def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("emit exploded")
        return emit_on_change(*args, **kwargs)

    monkeypatch.setattr(target, _flaky)


def _force_cri_levels(monkeypatch: pytest.MonkeyPatch, levels: list[str]) -> None:
    """Wrap the real cri_scoring.run_analysis but stamp ``cri.level`` from
    ``levels`` (in call order; the last entry repeats) — the level knob
    without faking the pipeline or the persisted payload."""
    calls = {"i": 0}

    def _wrapped(*args, **kwargs):
        payload = _cri_run_analysis(*args, **kwargs)
        payload["cri"]["level"] = levels[min(calls["i"], len(levels) - 1)]
        calls["i"] += 1
        return payload

    monkeypatch.setattr("uw_scan.cards.cri_scoring.run_analysis", _wrapped)


def _force_vrp_actions(monkeypatch: pytest.MonkeyPatch, actions: list[str]) -> None:
    """Wrap the real current_macro_signal but stamp ``action`` from
    ``actions`` (in call order; the last entry repeats) — the action knob
    without faking the job or the persisted row."""
    calls = {"i": 0}

    def _wrapped(*args, **kwargs):
        sig = _vrp_current_macro_signal(*args, **kwargs)
        action = actions[min(calls["i"], len(actions) - 1)]
        calls["i"] += 1
        return replace(sig, action=action)

    monkeypatch.setattr(
        "uw_scan.worker.jobs.vrp_macro_signal.current_macro_signal", _wrapped
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


def test_cri_eod_emit_failure_recovers_from_event_stream(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """A crashed emit must not lose the flip: the next scan anchors `prev` on
    the last EMITTED level (event stream), not the last committed snapshot —
    which by then already holds the new state."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "CRITICAL", basis="eod")
    _seed_emitted_event(
        repo.conn,
        kind="cri_regime",
        subject="CRI",
        basis="eod",
        from_="NORMAL",
        to="CRITICAL",
    )
    _fail_emit_once(monkeypatch, "uw_scan.scanners.cri.emit_on_change")

    # The snapshot lands; the emit dies → still just the seeded event.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 1

    # Recovery: prev = CRITICAL from the stream even though the snapshot
    # already holds the new level.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    events = _events(repo.conn)
    assert len(events) == 2
    kind, subject, basis, payload = events[1]
    assert (kind, subject, basis) == ("cri_regime", "CRI", "eod")
    assert payload["from"] == "CRITICAL"
    assert payload["to"] != "CRITICAL"

    # Steady state: once the flip is emitted the stream is the anchor again.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 2


def test_cri_eod_emit_failure_recovers_the_missed_step(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """LOW emitted; a scan lands HIGH but its emit dies (the snapshot
    commits anyway); the next scan is back at LOW. The stream must announce
    BOTH steps in order — the missed LOW→HIGH flagged ``recovered``, then
    the current HIGH→LOW."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "LOW", basis="eod")
    _seed_emitted_event(
        repo.conn,
        kind="cri_regime",
        subject="CRI",
        basis="eod",
        from_="NORMAL",
        to="LOW",
    )
    _force_cri_levels(monkeypatch, ["HIGH", "LOW", "LOW"])
    _fail_emit_once(monkeypatch, "uw_scan.scanners.cri.emit_on_change")

    # HIGH snapshot commits; the emit dies → still just the seeded event.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 1
    # The HIGH row's own context — what the recovered step must carry.
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT data_date, (payload->'cri'->>'score')::float8"
            "  FROM uw_scan.cri_snapshots WHERE basis = 'eod'"
            " ORDER BY scanned_at DESC LIMIT 1"
        )
        high_date, high_score = cur.fetchone()
    repo.conn.commit()

    # snapshot_prev=HIGH sits ahead of anchor=LOW → missed step first, then
    # the current transition.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    events = _events(repo.conn)
    assert len(events) == 3
    assert events[1][3] == {
        "data_date": high_date.isoformat(),
        "score": high_score,
        "from": "LOW",
        "to": "HIGH",
        "recovered": True,
    }
    assert events[2][0:3] == ("cri_regime", "CRI", "eod")
    # The normal event keeps its own shape: this scan's context, no flag.
    assert set(events[2][3]) == {"data_date", "score", "from", "to"}
    assert events[2][3]["from"] == "HIGH"
    assert events[2][3]["to"] == "LOW"

    # Steady state at LOW: one more scan adds nothing.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 3


def test_cri_eod_backfilled_older_date_is_not_a_missed_transition(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """The gap healer's as_of run writes an OLDER data_date with a fresh
    scanned_at. ``snapshot_prev`` keys on data_date, so the backfill must
    not read as a missed transition on the next regular scan."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "LOW", basis="eod")
    _seed_emitted_event(
        repo.conn,
        kind="cri_regime",
        subject="CRI",
        basis="eod",
        from_="NORMAL",
        to="LOW",
    )
    _force_cri_levels(monkeypatch, ["LOW", "HIGH", "LOW"])

    # Regular scan at LOW — equals the anchor; nothing emits.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 1

    # Gap-healer shape: an as_of run lands an OLDER data_date at a different
    # level (with a fresh scanned_at) and never emits.
    as_of = _CRI_SEED_START + timedelta(days=_CRI_SEED_DAYS - 10)
    assert cri_scanner.run(repo.conn, schema=repo._schema, as_of=as_of) is not None
    assert len(_events(repo.conn)) == 1

    # Next regular scan at LOW: snapshot_prev is the newest row by DATA DATE
    # (the earlier LOW row), not the fresh-scanned_at HIGH backfill — an
    # scanned_at-ordered read would fire a phantom recovered pair here.
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 1


def test_cri_eod_same_day_rerun_same_level_emits_nothing(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """A same-day re-run computing the level already on the stream is a
    genuine no-op — snapshot_prev equals the anchor, no recovered step."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "LOW", basis="eod")
    _seed_emitted_event(
        repo.conn,
        kind="cri_regime",
        subject="CRI",
        basis="eod",
        from_="NORMAL",
        to="LOW",
    )
    _force_cri_levels(monkeypatch, ["LOW", "LOW"])

    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert cri_scanner.run(repo.conn, schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 1


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


def test_cri_live_emit_failure_recovers_and_cooldown_intact(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """Live site: same self-heal, plus the 1h cooldown still suppresses a
    second flip once the recovered emit has landed."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "CRITICAL", basis="live")
    # Aged past the cooldown window so the recovered emit below can land.
    _seed_emitted_event(
        repo.conn,
        kind="cri_regime",
        subject="CRI",
        basis="live",
        from_="LOW",
        to="CRITICAL",
        age_hours=2,
    )
    _fail_emit_once(monkeypatch, "uw_scan.scanners.cri.emit_on_change")
    quotes = {"SPX": LiveQuote("SPX", 4600.0, _LIVE_QUOTED, "xenon_ws")}

    payload = cri_scanner.run_live(
        repo.conn, schema=repo._schema, quotes=quotes, persist=True
    )
    assert payload is not None
    recovered = payload["cri"]["level"]
    assert recovered != "CRITICAL"
    assert len(_events(repo.conn)) == 1  # emit died; only the seed

    assert (
        cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
        is not None
    )
    events = _events(repo.conn)
    assert len(events) == 2
    assert events[1][3]["from"] == "CRITICAL"
    assert events[1][3]["to"] == recovered

    assert (
        cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
        is not None
    )
    assert len(_events(repo.conn)) == 2

    # Cooldown intact: a genuinely different state inside the 1h window still
    # emits nothing — it re-attempts each tick and fires once the window
    # passes if the state still differs.
    shock = {
        "SPX": LiveQuote(
            "SPX", 4400.0, _LIVE_QUOTED + timedelta(minutes=10), "xenon_ws"
        ),
        "VIX": LiveQuote("VIX", 80.0, _LIVE_QUOTED + timedelta(minutes=10), "xenon_ws"),
    }
    shocked = cri_scanner.run_live(
        repo.conn, schema=repo._schema, quotes=shock, persist=True
    )
    assert shocked is not None
    assert shocked["cri"]["level"] != recovered
    assert len(_events(repo.conn)) == 2


def test_cri_live_flip_reverting_inside_cooldown_never_emits(
    seeded_db_empty_cards,
) -> None:
    """A flip that reverts inside the 1h cooldown never produces a stale
    event: A→B lands, B→C is suppressed, C→B collapses to a no-op (the stream
    is still at B — the suppressed excursion wrote no row), and once the
    window passes nothing fires because the stream is already at B."""
    repo = seeded_db_empty_cards
    _seed_cri_inputs(repo)
    _seed_prior_cri(repo, "CRITICAL", basis="live")

    calm = {"SPX": LiveQuote("SPX", 4600.0, _LIVE_QUOTED, "xenon_ws")}
    shock = {
        "SPX": LiveQuote(
            "SPX", 4400.0, _LIVE_QUOTED + timedelta(minutes=10), "xenon_ws"
        ),
        "VIX": LiveQuote("VIX", 80.0, _LIVE_QUOTED + timedelta(minutes=10), "xenon_ws"),
    }

    # A → B lands — the first-ever event; no cooldown window yet.
    payload = cri_scanner.run_live(
        repo.conn, schema=repo._schema, quotes=calm, persist=True
    )
    assert payload is not None
    level_b = payload["cri"]["level"]
    assert level_b != "CRITICAL"
    events = _events(repo.conn)
    assert len(events) == 1
    assert events[0][3]["from"] == "CRITICAL"
    assert events[0][3]["to"] == level_b

    # B → C inside the window: the cooldown suppresses the emit entirely —
    # no event row is written, and `prev` stays anchored at B.
    shocked = cri_scanner.run_live(
        repo.conn, schema=repo._schema, quotes=shock, persist=True
    )
    assert shocked is not None
    assert shocked["cri"]["level"] != level_b
    assert len(_events(repo.conn)) == 1

    # C → B, still inside the window: back at the last emitted state, a real
    # no-op — not a queued stale flip waiting on the cooldown.
    assert (
        cri_scanner.run_live(repo.conn, schema=repo._schema, quotes=calm, persist=True)
        is not None
    )
    assert len(_events(repo.conn)) == 1

    # Push the one emitted row outside the cooldown window and re-run at B:
    # still nothing — the stream never recorded the excursion.
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.mcp_event SET emitted_at = now() - interval '2 hours'"
        )
    repo.conn.commit()
    assert (
        cri_scanner.run_live(repo.conn, schema=repo._schema, quotes=calm, persist=True)
        is not None
    )
    assert len(_events(repo.conn)) == 1


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


def test_vcg_eod_emit_failure_recovers_from_event_stream(
    seeded_db_empty_cards, monkeypatch
) -> None:
    repo = seeded_db_empty_cards
    _seed_vcg_inputs(repo)
    _seed_prior_vcg(repo, "PANIC", basis="eod")
    _seed_emitted_event(
        repo.conn,
        kind="vcg_regime",
        subject="HYG",
        basis="eod",
        from_="NORMAL",
        to="PANIC",
    )
    _fail_emit_once(monkeypatch, "uw_scan.scanners.vcg.emit_on_change")

    assert vcg_scanner.run(repo.conn, proxy="HYG", schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 1

    assert vcg_scanner.run(repo.conn, proxy="HYG", schema=repo._schema) is not None
    events = _events(repo.conn)
    assert len(events) == 2
    kind, subject, basis, payload = events[1]
    assert (kind, subject, basis) == ("vcg_regime", "HYG", "eod")
    assert payload["from"] == "PANIC"
    assert payload["to"] != "PANIC"

    assert vcg_scanner.run(repo.conn, proxy="HYG", schema=repo._schema) is not None
    assert len(_events(repo.conn)) == 2


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


def test_vrp_eod_emit_failure_recovers_from_event_stream(
    seeded_db_empty_cards, monkeypatch
) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    settings = Settings.from_env()
    run_kw = {
        "repo": repo,
        "settings": settings,
        "snapshot_date": date(2026, 6, 22),
        "names": ("SPX",),
    }

    out = vrp_macro_signal_refresh(**run_kw)
    assert out["persisted"] == 1
    computed = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")[0]["action"]
    prev = _flip_stored_action(repo, basis="eod")  # stored action is now `prev`
    _seed_emitted_event(
        repo.conn,
        kind="vrp_macro_signal",
        subject="SPX",
        basis="eod",
        from_=computed,
        to=prev,
    )
    _fail_emit_once(monkeypatch, "uw_scan.worker.jobs.vrp_macro_signal.emit_on_change")

    # The upsert commits the recomputed action; the emit dies.
    out = vrp_macro_signal_refresh(**run_kw)
    assert out["persisted"] == 1
    assert len(_events(repo.conn)) == 1

    # Recovery: prev = `prev` from the stream even though the stored action
    # already flipped back to `computed`.
    out = vrp_macro_signal_refresh(**run_kw)
    assert out["persisted"] == 1
    events = _events(repo.conn)
    assert len(events) == 2
    kind, subject, basis, payload = events[1]
    assert (kind, subject, basis) == ("vrp_macro_signal", "SPX", "eod")
    assert payload["from"] == prev
    assert payload["to"] == computed

    vrp_macro_signal_refresh(**run_kw)
    assert len(_events(repo.conn)) == 2


def test_vrp_eod_emit_failure_recovers_the_missed_step(
    seeded_db_empty_cards, monkeypatch
) -> None:
    """SKIP emitted; a refresh lands TRADE but its emit dies (the upsert
    commits anyway); the next refresh is back at SKIP. The stream must
    announce BOTH steps in order — missed SKIP→TRADE ``recovered``, then
    TRADE→SKIP."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    settings = Settings.from_env()
    run_kw = {
        "repo": repo,
        "settings": settings,
        "snapshot_date": date(2026, 6, 22),
        "names": ("SPX",),
    }
    _force_vrp_actions(monkeypatch, ["SKIP", "TRADE", "SKIP", "SKIP"])

    # First refresh lands the stored row at SKIP; first-ever — no event.
    assert vrp_macro_signal_refresh(**run_kw)["persisted"] == 1
    assert _events(repo.conn) == []
    _seed_emitted_event(
        repo.conn,
        kind="vrp_macro_signal",
        subject="SPX",
        basis="eod",
        from_="TRADE",
        to="SKIP",
    )
    _fail_emit_once(monkeypatch, "uw_scan.worker.jobs.vrp_macro_signal.emit_on_change")

    # The TRADE upsert commits; the emit dies → still just the seeded event.
    assert vrp_macro_signal_refresh(**run_kw)["persisted"] == 1
    assert len(_events(repo.conn)) == 1
    trade_row = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")[0]
    repo.conn.commit()

    # snapshot_prev=TRADE sits ahead of anchor=SKIP → missed step first,
    # then the current transition.
    assert vrp_macro_signal_refresh(**run_kw)["persisted"] == 1
    events = _events(repo.conn)
    assert len(events) == 3
    assert events[1][0:3] == ("vrp_macro_signal", "SPX", "eod")
    assert events[1][3] == {
        "as_of": trade_row["as_of"].isoformat(),
        "vrp_z": float(trade_row["vrp_z"]),
        "weight": float(trade_row["weight"]),
        "from": "SKIP",
        "to": "TRADE",
        "recovered": True,
    }
    assert events[2][0:3] == ("vrp_macro_signal", "SPX", "eod")
    assert set(events[2][3]) == {"as_of", "vrp_z", "weight", "from", "to"}
    assert events[2][3]["from"] == "TRADE"
    assert events[2][3]["to"] == "SKIP"

    assert vrp_macro_signal_refresh(**run_kw)["persisted"] == 1
    assert len(_events(repo.conn)) == 3


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
        repo=repo, settings=settings, now=_LIVE_QUOTED + timedelta(minutes=1)
    )
    assert summary["vrp"] == "ok"
    assert _events(repo.conn) == []  # first-ever live row is not a change

    prev = _flip_stored_action(repo, basis="live")
    summary = regime_live_scan_once(
        repo=repo, settings=settings, now=_LIVE_QUOTED + timedelta(minutes=2)
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
            repo=repo, settings=settings, now=_LIVE_QUOTED + timedelta(minutes=minute)
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
