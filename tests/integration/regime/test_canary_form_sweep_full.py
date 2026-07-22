"""Integration tests for canary --form-sweep-full and its renderer.

All tests use the synthetic vol-complex fixture in
_canary_form_sweep_fixture.py and the project's pytest-postgresql fixture
(real Postgres, migrations applied per tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest


def test_delete_runs_by_batch_id_removes_rows_and_cascades_daily(
    seeded_db_empty_cards,
):
    """Insert a 4-row form_sweep_full batch + daily rows, then delete
    by batch_id. All runs AND daily rows must be gone."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    batch_id = str(uuid.uuid4())

    inserted_run_ids: list[int] = []
    for form in ("linear", "convex", "concave", "sigmoid"):
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=100,
            params={
                "score_form": form,
                "phase": "form_sweep_full",
                "batch_id": batch_id,
                "purpose": "candidate_discovery_not_validation",
            },
            summary={
                "is_winning_form": False,
                "score_form": form,
                "batch_id": batch_id,
                "phase": "form_sweep_full",
            },
            run_scope="research",
        )
        inserted_run_ids.append(run_id)
        repo.bulk_insert_daily(
            run_id,
            [
                {
                    "trade_date": date(2024, 1, 2),
                    "score": 20.0,
                    "level": "NONE",
                    "payload": {"raw_score": 20.0},
                },
            ],
        )

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (batch_id,),
        )
        assert cur.fetchone()[0] == 4
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily "
            f"WHERE run_id = ANY(%s)",
            (inserted_run_ids,),
        )
        assert cur.fetchone()[0] == 4

    n_deleted = repo.delete_runs_by_batch_id(batch_id)
    assert n_deleted == 4

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (batch_id,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily "
            f"WHERE run_id = ANY(%s)",
            (inserted_run_ids,),
        )
        assert cur.fetchone()[0] == 0


def test_delete_runs_by_batch_id_returns_zero_when_no_match(seeded_db_empty_cards):
    """Calling with an unknown batch_id is a no-op returning 0."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    n = repo.delete_runs_by_batch_id("00000000-0000-0000-0000-000000000000")
    assert n == 0


def test_delete_runs_by_batch_id_scoped_to_canary_research_form_sweep_full(
    seeded_db_empty_cards,
):
    """A row with the same batch_id but a DIFFERENT indicator/scope/phase
    must NOT be deleted. Defends against UUID4 collisions and accidental
    over-scoping if the method is reused without thinking."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    batch_id = str(uuid.uuid4())

    lookalikes = [
        # Wrong indicator
        dict(
            indicator="vcg",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=10,
            params={"phase": "form_sweep_full", "batch_id": batch_id},
            summary={"phase": "form_sweep_full"},
            run_scope="research",
        ),
        # Wrong run_scope
        dict(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=10,
            params={"phase": "form_sweep_full", "batch_id": batch_id},
            summary={"phase": "form_sweep_full"},
            run_scope="production",
        ),
        # Wrong phase
        dict(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=10,
            params={"phase": "calibrate", "batch_id": batch_id},
            summary={"phase": "calibrate"},
            run_scope="research",
        ),
    ]
    lookalike_ids = [repo.insert_run(**spec) for spec in lookalikes]

    target_id = repo.insert_run(
        indicator="canary",
        composite_version="1",
        start_date=date(2011, 2, 8),
        end_date=date(2026, 5, 21),
        window_days=350,
        n_days=10,
        params={
            "score_form": "linear",
            "phase": "form_sweep_full",
            "batch_id": batch_id,
            "purpose": "candidate_discovery_not_validation",
        },
        summary={
            "is_winning_form": False,
            "score_form": "linear",
            "batch_id": batch_id,
            "phase": "form_sweep_full",
        },
        run_scope="research",
    )

    n_deleted = repo.delete_runs_by_batch_id(batch_id)
    assert n_deleted == 1, "only the in-scope target row should be deleted"

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {db_schema}.regime_backtest_runs WHERE id = ANY(%s)",
            (lookalike_ids,),
        )
        remaining = [r[0] for r in cur.fetchall()]
        assert sorted(remaining) == sorted(lookalike_ids), (
            "lookalike rows must remain — scoping violation"
        )
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs WHERE id = %s",
            (target_id,),
        )
        assert cur.fetchone()[0] == 0


def test_cmd_form_sweep_full_persists_4_rows_sharing_batch_id(seeded_db_empty_cards):
    """Run the script's wrapper. Assert: 4 research rows, same batch_id, same generated_at."""
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id', summary->>'generated_at', "
            f"       params->>'score_form', summary->>'is_winning_form', run_scope "
            f"FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full' "
            f"ORDER BY params->>'score_form'"
        )
        rows = cur.fetchall()

    assert len(rows) == 4
    batch_ids = {r[0] for r in rows}
    gen_ats = {r[1] for r in rows}
    forms = {r[2] for r in rows}
    is_winning = {r[3] for r in rows}
    run_scopes = {r[4] for r in rows}
    assert len(batch_ids) == 1, f"all 4 rows must share batch_id, got {batch_ids}"
    assert len(gen_ats) == 1, f"all 4 rows must share generated_at, got {gen_ats}"
    assert forms == {"linear", "convex", "concave", "sigmoid"}
    assert is_winning == {"false"}, (
        f"is_winning_form must be false for all, got {is_winning}"
    )
    assert run_scopes == {"research"}, (
        f"run_scope must be research for all, got {run_scopes}"
    )


def test_cmd_form_sweep_full_writes_daily_rows(seeded_db_empty_cards):
    """Each form's run has exactly `n_days` corresponding regime_backtest_daily rows."""
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT r.params->>'score_form', r.n_days, COUNT(d.trade_date) "
            f"FROM {db_schema}.regime_backtest_runs r "
            f"LEFT JOIN {db_schema}.regime_backtest_daily d ON d.run_id = r.id "
            f"WHERE r.params->>'phase' = 'form_sweep_full' "
            f"GROUP BY r.params->>'score_form', r.n_days"
        )
        rows = cur.fetchall()
    assert len(rows) == 4, f"expected 4 form rows, got {len(rows)}"
    seen_forms: set[str] = set()
    for form, n_days, daily_count in rows:
        seen_forms.add(form)
        assert n_days > 0, f"{form} run.n_days must be > 0, got {n_days}"
        assert daily_count == n_days, (
            f"{form}: daily-row count {daily_count} != run.n_days {n_days} "
            f"— persistence is not writing every computed eval row"
        )
    assert seen_forms == {"linear", "convex", "concave", "sigmoid"}


def test_cmd_form_sweep_full_summary_schema(seeded_db_empty_cards):
    """summary JSONB has all the spec-required keys."""
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT summary FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full' LIMIT 1"
        )
        summary = cur.fetchone()[0]
    for key in (
        "is_winning_form",
        "score_form",
        "phase",
        "source",
        "batch_id",
        "generated_at",
        "n_days",
        "aucs",
        "auc_ci95",
        "band_distribution",
        "within_band_aucs",
        "vol_only_gap",
    ):
        assert key in summary, f"summary missing key: {key}"
    for series in ("composite", "vol_only", "speed_only"):
        assert series in summary["aucs"]
        for horizon in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
            assert horizon in summary["aucs"][series], (
                f"aucs.{series}.{horizon} missing"
            )
    for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        assert band in summary["band_distribution"]


def test_cmd_form_sweep_full_prints_renderer_output(seeded_db_empty_cards, capsys):
    """After persistence, the command must call the renderer and print its
    output to stdout. A buggy implementation that persists correctly but
    skips the print would otherwise pass every DB-only test."""
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    captured = capsys.readouterr()
    stdout = captured.out
    for form in ("linear", "convex", "concave", "sigmoid"):
        assert form in stdout, f"renderer output missing form row '{form}'"
    li = stdout.index("linear")
    cv = stdout.index("convex")
    cc = stdout.index("concave")
    sg = stdout.index("sigmoid")
    assert li < cv < cc < sg, (
        f"form rows must appear in canonical order, got positions "
        f"linear={li}, convex={cv}, concave={cc}, sigmoid={sg}"
    )
    assert "Observations" in stdout, "renderer output missing Observations section"
    assert "What this run does NOT decide" in stdout, (
        "renderer footer missing — guardrail prose against misuse"
    )


def test_cmd_form_sweep_full_does_not_persist_when_compute_fails_mid_run(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Compute-all-before-persist invariant (spec §4.2 / AC-13).

    Patches `deps.compute_canary_series` to raise on the *third* invocation
    (= third form). Asserts: zero `form_sweep_full` rows are persisted.
    """
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )
    from uw_scan.reports import regime_canary_form_sweep_full as impl_mod

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    real_run = impl_mod.run_form_sweep_full
    call_count = {"compute": 0}

    def make_failing_run(conn, *, schema, deps):
        real_compute = deps.compute_canary_series

        def patched_compute(*args, **kwargs):
            call_count["compute"] += 1
            if call_count["compute"] == 3:
                raise RuntimeError(
                    "synthetic failure on form 3 — compute-before-persist test"
                )
            return real_compute(*args, **kwargs)

        from dataclasses import replace

        patched_deps = replace(deps, compute_canary_series=patched_compute)
        return real_run(conn, schema=schema, deps=patched_deps)

    monkeypatch.setattr(impl_mod, "run_form_sweep_full", make_failing_run)

    with pytest.raises(RuntimeError, match="synthetic failure on form 3"):
        cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full'"
        )
        assert cur.fetchone()[0] == 0, (
            "compute-before-persist violated: rows for forms 1/2 leaked "
            "into the DB before form 3's compute failed"
        )
    assert call_count["compute"] == 3, (
        f"expected compute to be called 3 times before failing, "
        f"got {call_count['compute']}"
    )


def test_form_sweep_full_cleanup_on_failure(seeded_db_empty_cards, monkeypatch):
    """Simulate a real DB failure on the 3rd form's bulk_insert_daily call.
    Assert: rollback happens and zero failed-batch rows remain afterwards."""
    from importlib.resources import files

    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    calib_path = files("uw_scan.cards") / "data" / "canary-calibration-v1.json"
    before_calib_bytes = calib_path.read_bytes()
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    real_bulk = RegimeBacktestRepository.bulk_insert_daily
    call_count = {"n": 0}

    def fail_on_third_call(self, run_id, rows):
        call_count["n"] += 1
        if call_count["n"] == 3:
            with self._conn.cursor() as cur:
                cur.execute("INSERT INTO definitely_missing_table VALUES (1)")
        return real_bulk(self, run_id, rows)

    monkeypatch.setattr(
        RegimeBacktestRepository,
        "bulk_insert_daily",
        fail_on_third_call,
    )

    with pytest.raises(Exception):
        cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full'"
        )
        assert cur.fetchone()[0] == 0, (
            "cleanup-on-failure must remove all rows for failed batch_id"
        )
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily d "
            f"JOIN {db_schema}.regime_backtest_runs r ON d.run_id = r.id "
            f"WHERE r.params->>'phase' = 'form_sweep_full'"
        )
        assert cur.fetchone()[0] == 0, "daily rows must cascade-delete"
    assert calib_path.read_bytes() == before_calib_bytes, (
        "calibration file changed on failure"
    )


def test_form_sweep_full_renderer_picks_latest_complete_batch(seeded_db_empty_cards):
    """Two complete batches, different created_at — loader picks the latest."""
    from uw_scan.reports.regime_canary_backtest_report import (
        _load_latest_complete_batch,
    )
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)

    def insert_batch(batch_id: str):
        for form in ("linear", "convex", "concave", "sigmoid"):
            run_id = repo.insert_run(
                indicator="canary",
                composite_version="1",
                start_date=date(2011, 2, 8),
                end_date=date(2026, 5, 21),
                window_days=350,
                n_days=100,
                params={
                    "score_form": form,
                    "phase": "form_sweep_full",
                    "batch_id": batch_id,
                },
                summary={
                    "is_winning_form": False,
                    "score_form": form,
                    "batch_id": batch_id,
                    "phase": "form_sweep_full",
                    "n_days": 100,
                    "aucs": {
                        "composite": {
                            "up5d_2pct": 0.6,
                            "up20d_5pct": 0.6,
                            "up60d_10pct": 0.6,
                        },
                        "vol_only": {
                            "up5d_2pct": 0.6,
                            "up20d_5pct": 0.6,
                            "up60d_10pct": 0.6,
                        },
                        "speed_only": {
                            "up5d_2pct": 0.5,
                            "up20d_5pct": 0.5,
                            "up60d_10pct": 0.5,
                        },
                    },
                    "band_distribution": {
                        "NONE": 60,
                        "WATCH": 30,
                        "BUY": 10,
                        "STRONG_BUY": 0,
                    },
                    "within_band_aucs": {
                        "NONE": {"up60d_10pct": 0.55},
                        "WATCH": {"up60d_10pct": 0.55},
                        "BUY": {"up60d_10pct": 0.45},
                        "STRONG_BUY": {"up60d_10pct": None},
                    },
                    "vol_only_gap": {
                        "up5d_2pct": 0.0,
                        "up20d_5pct": 0.0,
                        "up60d_10pct": 0.0,
                    },
                },
                run_scope="research",
            )
            repo.mark_run_completed(run_id)

    insert_batch("batch-A")
    insert_batch("batch-B")

    runs = _load_latest_complete_batch(db_conn, db_schema)
    assert len(runs) == 4
    batch_ids = {r["params"]["batch_id"] for r in runs}
    assert batch_ids == {"batch-B"}, f"expected batch-B, got {batch_ids}"


def test_renderer_skips_incomplete_batch(seeded_db_empty_cards):
    """Earlier complete batch + later incomplete (3 rows) batch — loader returns the earlier."""
    from uw_scan.reports.regime_canary_backtest_report import (
        _load_latest_complete_batch,
    )
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)

    def insert_run_for(batch_id: str, form: str, *, completed: bool = True):
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=100,
            params={
                "score_form": form,
                "phase": "form_sweep_full",
                "batch_id": batch_id,
            },
            summary={
                "is_winning_form": False,
                "score_form": form,
                "batch_id": batch_id,
                "phase": "form_sweep_full",
                "n_days": 100,
                "aucs": {
                    "composite": {
                        "up5d_2pct": 0.6,
                        "up20d_5pct": 0.6,
                        "up60d_10pct": 0.6,
                    },
                    "vol_only": {
                        "up5d_2pct": 0.6,
                        "up20d_5pct": 0.6,
                        "up60d_10pct": 0.6,
                    },
                    "speed_only": {
                        "up5d_2pct": 0.5,
                        "up20d_5pct": 0.5,
                        "up60d_10pct": 0.5,
                    },
                },
                "band_distribution": {
                    "NONE": 60,
                    "WATCH": 30,
                    "BUY": 10,
                    "STRONG_BUY": 0,
                },
                "within_band_aucs": {
                    "NONE": {"up60d_10pct": 0.55},
                    "WATCH": {"up60d_10pct": 0.55},
                    "BUY": {"up60d_10pct": 0.45},
                    "STRONG_BUY": {"up60d_10pct": None},
                },
                "vol_only_gap": {
                    "up5d_2pct": 0.0,
                    "up20d_5pct": 0.0,
                    "up60d_10pct": 0.0,
                },
            },
            run_scope="research",
        )
        if completed:
            repo.mark_run_completed(run_id)

    for form in ("linear", "convex", "concave", "sigmoid"):
        insert_run_for("batch-complete", form)
    for form in ("linear", "convex", "concave"):
        insert_run_for("batch-partial", form)

    runs = _load_latest_complete_batch(db_conn, db_schema)
    batch_ids = {r["params"]["batch_id"] for r in runs}
    assert batch_ids == {"batch-complete"}, (
        f"loader must skip incomplete batches, got {batch_ids}"
    )


def test_form_sweep_full_does_not_write_calibration_file(seeded_db_empty_cards):
    """canary-calibration-v1.json byte content unchanged after run."""
    import hashlib
    from importlib.resources import files

    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    calib_path = files("uw_scan.cards") / "data" / "canary-calibration-v1.json"
    assert calib_path.exists(), f"calibration file not found at {calib_path}"

    before_bytes = calib_path.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()
    before_mtime = calib_path.stat().st_mtime

    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)
    cmd_form_sweep_full(db_conn, schema=db_schema)

    after_bytes = calib_path.read_bytes()
    after_hash = hashlib.sha256(after_bytes).hexdigest()
    after_mtime = calib_path.stat().st_mtime

    assert before_bytes == after_bytes, "calibration file content changed"
    assert before_hash == after_hash, "calibration SHA-256 mismatch"
    assert before_mtime == after_mtime, "calibration mtime changed"


def test_form_sweep_full_invisible_to_oos_gate(seeded_db_empty_cards):
    """Production find_latest_run does not return any research-scoped form_sweep_full row."""
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    winning_run_id = repo.insert_run(
        indicator="canary",
        composite_version="1",
        start_date=date(2020, 1, 2),
        end_date=date(2026, 5, 21),
        window_days=350,
        n_days=1605,
        params={"score_form": "linear", "phase": "final_oos_report"},
        summary={"is_winning_form": True, "score_form": "linear"},
    )
    repo.mark_run_completed(winning_run_id)

    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)
    cmd_form_sweep_full(db_conn, schema=db_schema)

    latest = repo.find_latest_run("canary", composite_version="1")
    assert latest is not None
    assert latest["id"] == winning_run_id, (
        f"find_latest_run returned {latest['id']}; expected pre-existing v1 run "
        f"{winning_run_id}. form_sweep_full rows must be research scoped."
    )


def test_form_sweep_full_invisible_to_validation_api(seeded_db_empty_cards):
    """The /api/regime/canary/validation router function returns the same
    row before and after a form_sweep_full run."""
    from scripts.backtest_canary import cmd_form_sweep_full
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_canary_snapshots,
        seed_vol_index,
    )
    from uw_scan.api.routers.regime import get_canary_validation
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    pre_winning_id = repo.insert_run(
        indicator="canary",
        composite_version="1",
        start_date=date(2020, 1, 2),
        end_date=date(2026, 5, 21),
        window_days=350,
        n_days=1605,
        params={"score_form": "linear", "phase": "final_oos_report"},
        summary={"is_winning_form": True, "score_form": "linear"},
    )
    repo.mark_run_completed(pre_winning_id)

    before = get_canary_validation(repo=seeded_db_empty_cards).model_dump_json()
    assert f'"run_id":{pre_winning_id}' in before

    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)
    cmd_form_sweep_full(db_conn, schema=db_schema)

    after = get_canary_validation(repo=seeded_db_empty_cards).model_dump_json()
    assert before == after, "validation API payload changed across form_sweep_full"
