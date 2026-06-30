"""verify-all writes a readable evidence artifact and makes ZERO provider calls
(it is audit-only). Proves the report shape and that no heal/budget ran."""

from __future__ import annotations

import importlib.util
import json
import types
from datetime import date

from uw_scan.reports.data_gap_healer import REGISTRY
from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "data_gap_healer_cli", "scripts/backfill/data_gap_healer.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _settings(repo):
    return types.SimpleNamespace(
        db_schema=repo._schema, db_host="127.0.0.1", db_name="option_wizard_test"
    )


def _ohlc(repo, ticker, d):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.daily_ohlc (ticker, date, close, source) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (ticker, d, 1.0, "test"),
        )
    repo.conn.commit()


def test_verify_all_writes_evidence_and_makes_no_provider_calls(
    seeded_db_empty_cards, tmp_path
):
    repo = seeded_db_empty_cards
    cli = _load_cli()
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    d1, d2 = date(2026, 6, 10), date(2026, 6, 11)
    _ohlc(repo, "AAPL", d1)  # AAPL missing d2 -> at least one gap

    as_of = date(2026, 6, 30)
    evidence, paths = cli.verify_all(
        repo,
        gap,
        _settings(repo),
        start=d1,
        end=d2,
        as_of=as_of,
        out_dir=tmp_path,
        command="verify-all",
    )

    # shape
    assert evidence["run_id"] is not None
    assert evidence["total_gaps"] >= 1
    assert evidence["registry_count"] == len(REGISTRY)
    assert isinstance(evidence["unregistered_tables"], list)
    assert "daily_ohlc" in evidence["datasets"]
    # audit-only: no heal ran, no budget spent
    assert evidence["heal_outcome"] == {}
    assert evidence["budget_spent"] == {}

    # artifact files exist and the json round-trips
    md_path = tmp_path / f"{as_of.isoformat()}-gap-report.md"
    json_path = tmp_path / f"{as_of.isoformat()}-gap-report.json"
    assert md_path.exists() and json_path.exists()
    assert paths["md"] == str(md_path)
    loaded = json.loads(json_path.read_text())
    assert loaded["total_gaps"] == evidence["total_gaps"]
    assert "# Data gap report" in md_path.read_text()


def test_verify_all_creates_an_audit_run(seeded_db_empty_cards, tmp_path):
    repo = seeded_db_empty_cards
    cli = _load_cli()
    gap = DataGapHealerRepository(repo.conn, schema=repo._schema)
    evidence, _ = cli.verify_all(
        repo,
        gap,
        _settings(repo),
        start=date(2026, 6, 1),
        end=date(2026, 6, 2),
        as_of=date(2026, 6, 30),
        out_dir=tmp_path,
        command="verify-all",
    )
    run = gap.get_run(evidence["run_id"])
    assert run["mode"] == "audit"
    assert run["status"] == "complete"
