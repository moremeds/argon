"""End-to-end test using a small-window label contract.
v0.3 — real test, no pytest.skip; CO-6 schema fix; CL-5 proper DSN."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml


def _load_script():
    name = "score_vcg_classification_accuracy"
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parents[2]
        / "scripts/score_vcg_classification_accuracy.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def small_window_label_dir(tmp_path):
    """Temporary label contract with rolling_window=5 (no real warmup needed)."""
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    (label_dir / "level1-thresholds.yaml").write_text(
        yaml.safe_dump(
            {
                "label_version": 1,
                "contract_committed_at": "2026-05-26",
                "rolling_window_days": 5,
                "realized_vol_window_days": 3,
                "percentile_tie_rule": "strict_lt",
                "P_SUPP": 0.30,
                "P_RO": 0.80,
                "P_PANIC": 0.95,
                "DD_EDR": 0.07,
                "N_BOUNCE": 2,
                "NORMAL_LOW": 0.30,
                "NORMAL_HIGH": 0.80,
                "NORMAL_DD": 0.05,
                "N_MIN_CLASS_DAYS": 1,
                "K_MIN_CORE_ELIGIBLE": 4,
                "MACRO_F1_PASS": 0.30,
                "PANIC_SUPPRESSION_RATIO": 0.20,
                "SPARSITY_RATIO": 0.25,
                "MISMATCH_CONCENTRATION": 0.60,
                "BENCH_RANGE": 0.15,
                "fred_series": {
                    "credit_stress_primary": "NFCI",
                    "credit_stress_sensitivity": "ANFCI",
                    "recession_dating": "USREC",
                },
                "eval_start": "2024-01-15",
                "eval_end": "auto",
                "period_buckets": [
                    {"name": "all", "start": "2024-01-15", "end": "auto"}
                ],
            }
        )
    )
    (label_dir / "named-crises.yaml").write_text(
        yaml.safe_dump({"label_version": 1, "crises": []})
    )
    (label_dir / "vcg-source.yaml").write_text(
        yaml.safe_dump(
            {
                "label_version": 1,
                "vcg_source": {
                    "run_id": 0,
                    "indicator": "vcg",
                    "composite_version": "1",
                    "run_scope": "production",
                    "credit_proxy": "HYG",
                    "pinned_at": "2026-05-26",
                    "pinned_because": "e2e",
                },
            }
        )
    )
    (label_dir / "label-version.yaml").write_text(
        yaml.safe_dump({"version": 1, "committed_at": "2026-05-26", "notes": "e2e"})
    )
    return label_dir


def _seed_market_data(conn, schema: str, start: date, n_days: int = 60):
    """v0.3 / CO-6: macro_series_daily requires as_of + source NOT NULL."""
    dates = pd.bdate_range(start, periods=n_days)
    as_of_ts = datetime(2026, 5, 26, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        for d in dates:
            for symbol, close in (("VIX", 18.0), ("VVIX", 85.0), ("SPX", 4500.0)):
                cur.execute(
                    f"INSERT INTO {schema}.vol_index_daily (trade_date, symbol, close) "
                    f"VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (d.date(), symbol, close),
                )
            # Spike vol on middle day -> triggers RISK_OFF (post-warmup days only)
            if d == dates[len(dates) // 2]:
                cur.execute(
                    f"UPDATE {schema}.vol_index_daily SET close=60.0 "
                    f"WHERE trade_date=%s AND symbol='VIX'",
                    (d.date(),),
                )
                cur.execute(
                    f"UPDATE {schema}.vol_index_daily SET close=150.0 "
                    f"WHERE trade_date=%s AND symbol='VVIX'",
                    (d.date(),),
                )
            for series_id, value in (("NFCI", -0.5), ("USREC", 0.0)):
                cur.execute(
                    f"INSERT INTO {schema}.macro_series_daily "
                    f"(obs_date, series_id, value, as_of, source) "
                    f"VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (d.date(), series_id, value, as_of_ts, "test"),
                )
    conn.commit()


def _seed_vcg_run(conn, schema: str, start: date, n_days: int = 60) -> int:
    """Insert synthetic VCG production run."""
    from uw_scan.storage.regime_backtest_repository import (
        RegimeBacktestRepository,
    )

    rb = RegimeBacktestRepository(conn, schema=schema)
    dates = list(pd.bdate_range(start, periods=n_days))
    run_id = rb.insert_run(
        indicator="vcg",
        composite_version="1",
        start_date=dates[0].date(),
        end_date=dates[-1].date(),
        window_days=21,
        n_days=len(dates),
        params={},
        summary={},
        note="e2e vcg",
        run_scope="production",
        composite_method="single_proxy",
        credit_proxy="HYG",
    )
    rows = []
    for i, d in enumerate(dates):
        label = "RISK_OFF" if i == len(dates) // 2 else "NORMAL"
        rows.append(
            {"trade_date": d.date(), "score": 0.0, "level": label, "payload": {}}
        )
    rb.bulk_insert_daily(run_id, rows)
    rb.mark_run_completed(run_id)
    return run_id


def test_e2e_classification_full_pipeline(
    seeded_db_empty_cards,
    small_window_label_dir,
    tmp_path,
    monkeypatch,
):
    """v0.3 fixes verified end-to-end."""
    repo = seeded_db_empty_cards
    schema = repo._schema
    eval_start = date(2024, 1, 15)
    data_start = eval_start - timedelta(days=30)
    _seed_market_data(repo.conn, schema, data_start, n_days=60)
    vcg_run_id = _seed_vcg_run(repo.conn, schema, data_start, n_days=60)

    src_yaml = small_window_label_dir / "vcg-source.yaml"
    src = yaml.safe_load(src_yaml.read_text())
    src["vcg_source"]["run_id"] = vcg_run_id
    src_yaml.write_text(yaml.safe_dump(src))

    # DSN from psycopg .info. Local pytest-postgresql runs trust auth (empty
    # password); CI Linux requires a password — include cinfo.password when
    # present. libpq key=value form mirrors Settings.db_dsn() so subprocess
    # connection semantics match production code.
    cinfo = repo.conn.info
    password_clause = f" password={cinfo.password}" if cinfo.password else ""
    db_url = (
        f"host={cinfo.host} port={cinfo.port} dbname={cinfo.dbname} "
        f"user={cinfo.user}{password_clause}"
    )
    monkeypatch.setenv("UW_SCAN_DB_URL", db_url)

    report_path = tmp_path / "report.md"
    mod = _load_script()
    rc = mod.main(
        [
            "--label-dir",
            str(small_window_label_dir),
            "--out",
            str(report_path),
        ]
    )
    assert rc == 0

    # Verify classification run inserted with correct tags
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT id, run_scope, composite_method, credit_proxy, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE composite_method='classification_accuracy' ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    classification_run_id = row[0]
    assert row[1] == "research"
    assert row[2] == "classification_accuracy"
    assert row[3] == "CLASSIFICATION"
    # v0.3 / CR-1: report_md persisted
    assert "report_md" in row[5]["extras"]["classification"]

    # v0.3 / CL-3: daily payload includes NFCI_value
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT payload FROM {schema}.regime_backtest_daily "
            f"WHERE run_id=%s LIMIT 1",
            (classification_run_id,),
        )
        payload = cur.fetchone()[0]
    assert "label_components" in payload
    assert "NFCI_value" in payload["label_components"]

    # v0.3 / CL-6: report contains Data vintages section
    text = report_path.read_text()
    assert "Data vintages" in text
    assert "NFCI" in text
    assert "This classification score measures descriptive agreement" in text

    # v0.3 / CR-1: BYTE-IDENTICAL replay
    replay_path = tmp_path / "replay.md"
    rc3 = mod.main(
        [
            "--render-run-id",
            str(classification_run_id),
            "--out",
            str(replay_path),
        ]
    )
    assert rc3 == 0
    assert report_path.read_bytes() == replay_path.read_bytes(), (
        "replay not byte-identical"
    )

    # v0.3 / CR-2: --force-new-run on existing race -> exit 1
    rc4 = mod.main(
        [
            "--label-dir",
            str(small_window_label_dir),
            "--out",
            str(tmp_path / "force.md"),
            "--force-new-run",
        ]
    )
    assert rc4 == 1
