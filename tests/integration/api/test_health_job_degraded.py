"""/api/health ``job_degraded`` block over a real DB and the running app.

Each entry is read from a record the job already persists — the degraded block
itself writes nothing, is informational only (never flips ``ok``), and
self-clears on the next clean run/source success.
"""

from __future__ import annotations

from datetime import UTC, datetime


def test_health_reports_degraded_jobs(client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards

    # GRG thin-data run -> a 'degraded' scan_run record (scanners/grg.py).
    grg_run = repo.insert_scan_run("GRG", notes="grg_scan")
    repo.finish_scan_run(grg_run, status="degraded")

    # discovery partial-DP run -> an 'ok' run whose run meta counts enriched
    # candidates (pins the aggregates->'discovery' key shape the reader uses).
    from uw_scan.storage.signals_repository import SignalsRepository

    disc_run = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    SignalsRepository(repo.conn, schema="uw_scan").upsert_discovery_run_meta(
        disc_run, {"candidates_found": 2, "dp_enriched": 1}
    )
    repo.finish_scan_run(disc_run, status="ok")

    # Macro ingest partial failure -> macro_source_status 'degraded' row.
    repo.upsert_macro_source_status(
        "test_src",
        status="degraded",
        attempted_at=datetime.now(UTC),
        error_type="MacroSeriesFailures",
        error_message="1 of 7 series failed; first X: builtins.RuntimeError: 503",
    )
    repo.conn.commit()

    body = client.get("/api/health").json()
    degraded = {d["job_name"]: d for d in body["job_degraded"]}

    assert degraded["regime_grg_scan"]["record"] == "scan_run"
    assert degraded["regime_grg_scan"]["consecutive"] is None
    assert degraded["discovery_scan"]["record"] == "scan_run"
    assert degraded["discovery_scan"]["detail"] == "dp 1/2 enriched"
    assert degraded["test_src"]["record"] == "macro_source"
    assert degraded["test_src"]["consecutive"] == 1
    assert degraded["test_src"]["detail"].startswith("MacroSeriesFailures:")

    # Informational only: degraded is listed but the ok/reason gates are
    # unchanged (an empty test DB has never completed a full scan).
    assert body["ok"] is False
    assert body["reason"] == "no successful full scan yet"


def test_health_degraded_entries_self_clear(client, seeded_db_empty_cards):
    """A scan-run entry reflects only the LATEST run — the next clean run
    removes it, and a macro source clears when its next success upserts 'ok'."""
    repo = seeded_db_empty_cards

    bad = repo.insert_scan_run("GRG", notes="grg_scan")
    repo.finish_scan_run(bad, status="degraded")
    clean = repo.insert_scan_run("GRG", notes="grg_scan")
    repo.finish_scan_run(clean, status="ok")

    repo.upsert_macro_source_status(
        "test_src",
        status="degraded",
        attempted_at=datetime.now(UTC),
        error_type="MacroSeriesFailures",
        error_message="503",
    )
    repo.upsert_macro_source_status(
        "test_src", status="ok", attempted_at=datetime.now(UTC)
    )
    repo.conn.commit()

    names = [d["job_name"] for d in client.get("/api/health").json()["job_degraded"]]
    assert "regime_grg_scan" not in names
    assert "test_src" not in names


def test_health_degraded_absent_when_nothing_degraded(client, seeded_db_empty_cards):
    body = client.get("/api/health").json()
    assert body["job_degraded"] == []


def test_health_degraded_survives_an_in_flight_run(client, seeded_db_empty_cards):
    """An unfinished run has no outcome yet: while the next GRG run executes,
    the previous run's degraded entry stays listed."""
    repo = seeded_db_empty_cards

    done = repo.insert_scan_run("GRG", notes="grg_scan")
    repo.finish_scan_run(done, status="degraded")
    repo.insert_scan_run("GRG", notes="grg_scan")  # in flight, not finished

    body = client.get("/api/health").json()
    assert [d["job_name"] for d in body["job_degraded"]] == ["regime_grg_scan"]
