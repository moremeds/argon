"""Offline actual-function diagnostics. All persistence/provider boundaries mocked.

Input JSON: {ticker, bars, spy_bars, provenance}. Bars are captured real historical
OHLCV in Apex's time/open/high/low/close/volume shape; provenance is required.
No provider requests, database connections, or application modifications.
"""
from __future__ import annotations

import argparse
import cProfile
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from uw_scan.cards import technicals
from uw_scan.worker.jobs import option_surface_capture as surface
from uw_scan.worker.jobs import technical_daily_refresh as daily

ROOT = Path(__file__).resolve().parents[2]


def surface_membership() -> dict:
    """Reproduce count-vs-membership defect; synthetic labels, no market prices."""
    expected = ["MOCK_PRESENT", "MOCK_MISSING"]
    done = ["MOCK_PRESENT", "MOCK_REMOVED"]
    repo = MagicMock()
    repo._schema = "mock_only"
    repo.list_watchlist_cards.return_value = [SimpleNamespace(ticker=t) for t in expected]
    repo.conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [(t,) for t in done]

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 25)

    with patch.object(surface, "_date", FrozenDate), patch.object(surface, "_build_ticker_rows") as fetch:
        result = surface.option_surface_backfill(repo=repo, client=MagicMock(), days_back=1)
    missing = sorted(set(expected) - set(done))
    assert missing == ["MOCK_MISSING"]
    assert fetch.call_count == 0 and result == 0, "Baseline defect changed; review diagnostic"
    return {"kind": "explicitly_mocked_membership_regression", "watchlist": expected,
            "captured": done, "expected_missing": missing, "actual_fetch_calls": fetch.call_count,
            "actual_rows_written": result, "bug_reproduced": True, "mock_market_date": "2026-09-24"}


def calculation(bars, spy, reuse: bool):
    if not reuse:
        snapshot = technicals.build_technical_snapshot(bars, spy)
        series = technicals.build_technical_series(bars, spy)
    else:
        series = technicals.build_technical_series(bars, spy)
        # Diagnostic substitution only: execute the actual snapshot, reuse its
        # already computed input. This is not a shipped signature/code change.
        with patch.object(technicals, "build_technical_series", return_value=series):
            snapshot = technicals.build_technical_snapshot(bars, spy)
    return snapshot, series


def actual_job_count(ticker, bars, spy) -> dict:
    repo = MagicMock()
    repo.list_daily_ohlc.return_value = []  # Explicitly absent recent overlay.
    original = technicals.build_technical_series
    count = 0

    def counted(*args, **kwargs):
        nonlocal count
        count += 1
        return original(*args, **kwargs)

    def captured(t):
        assert t in {ticker, "SPY"}
        return spy if t == "SPY" else bars

    with patch.object(daily, "fetch_daily_bars", side_effect=captured), \
         patch.object(daily, "TechnicalsRepository") as storage, \
         patch.object(daily, "build_technical_series", side_effect=counted), \
         patch.object(technicals, "build_technical_series", side_effect=counted):
        result = daily.technical_daily_refresh(repo=repo, settings=SimpleNamespace(db_schema="mock_only"), ticker_filter=[ticker])
        writes = storage.return_value.upsert_series.call_args_list
    expected = 1 if ticker == "SPY" else 2
    assert result["ok"] == expected and result["failed"] == 0
    assert count == expected * 2
    return {"summary": result, "series_calls": count, "calls_per_successful_ticker": count / expected,
            "mocked_series_write_rowcounts": [len(call.args[1]) for call in writes],
            "boundaries": "captured bars; mocked source/persistence; no recent OHLC overlay"}


def capture_bars(destination: Path):
    """Explicit read-only Mini capture, invoked only by --capture-bars."""
    import psycopg
    from uw_scan.config import Settings, _load_dotenv
    source_root = ROOT.parents[1]
    _load_dotenv(source_root / ".env.local")
    _load_dotenv(source_root / ".env")
    settings = Settings.from_env().model_copy(update={"db_host": "100.66.147.98", "db_name": "option_wizard"})
    sql = """SELECT as_of, open, high, low, close, volume, inserted_at
             FROM uw_scan.technical_daily WHERE ticker = %s
             AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL
             AND close IS NOT NULL AND volume IS NOT NULL
             ORDER BY as_of DESC LIMIT 1300"""
    samples, timestamps = {}, {}
    with psycopg.connect(settings.db_dsn(), options="-c default_transaction_read_only=on -c statement_timeout=8000") as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            assert cur.fetchone()[0] == "on"
            cur.execute("SHOW statement_timeout")
            timeout = cur.fetchone()[0]
            for ticker in ("NVDA", "SPY"):
                cur.execute(sql, (ticker,))
                rows = list(reversed(cur.fetchall()))
                assert len(rows) >= 210
                samples[ticker] = [{"time": r[0].isoformat() + "T00:00:00+00:00",
                                   **{k: float(v) for k, v in zip(("open", "high", "low", "close", "volume"), r[1:6])}}
                                  for r in rows]
                timestamps[ticker] = {"min_inserted_at": min(r[6] for r in rows).isoformat(),
                                      "max_inserted_at": max(r[6] for r in rows).isoformat(), "rows": len(rows)}
    payload = {"ticker": "NVDA", "bars": samples["NVDA"], "spy_bars": samples["SPY"],
               "provenance": {"source": "Mini option_wizard uw_scan.technical_daily persisted OHLCV",
                              "capture_at": datetime.now(timezone.utc).isoformat(), "read_only": True,
                              "statement_timeout": timeout, "query": sql, "row_metadata": timestamps,
                              "caveat": "Persisted technical inputs; not a fresh Apex fetch. ISO UTC midnight maps stored session date without inferred intraday timestamp."}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path)
    parser.add_argument("--capture-bars", action="store_true", help="Explicitly capture read-only Mini OHLCV to --bars then validate offline")
    parser.add_argument("--repeats", type=int, default=0)
    parser.add_argument("--output", type=Path, default=ROOT / "output/profile-review/jobs-research")
    args = parser.parse_args()
    assert args.repeats >= 0
    args.output.mkdir(parents=True, exist_ok=True)
    for module in (technicals, surface, daily):
        assert Path(module.__file__).resolve().is_relative_to(ROOT / "src"), module.__file__
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "command_argv": sys.argv, "python": sys.version, "root": str(ROOT),
              "module_paths": {m.__name__: m.__file__ for m in (technicals, surface, daily)},
              "surface_membership": surface_membership(), "timings": []}
    if args.capture_bars:
        assert args.bars, "--capture-bars requires --bars destination"
        capture_bars(args.bars)
    if args.bars:
        raw = args.bars.read_bytes()
        payload = json.loads(raw)
        assert payload.get("provenance"), "Captured real-data provenance required"
        ticker = payload["ticker"].upper()
        bars, spy = payload["bars"], payload["spy_bars"]
        assert len(bars) >= 210 and len(spy) >= 210
        frame = technicals.bars_frame(bars)
        report["input"] = {"path": str(args.bars.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                           "provenance": payload["provenance"], "ticker": ticker, "bars": len(bars),
                           "spy_bars": len(spy), "first_date": str(frame.as_of.min()), "last_date": str(frame.as_of.max())}
        report["actual_job"] = actual_job_count(ticker, bars, spy)
        baseline = calculation(bars, spy, False)
        reuse = calculation(bars, spy, True)
        assert json.dumps(baseline[0], sort_keys=True, default=str) == json.dumps(reuse[0], sort_keys=True, default=str)
        pd.testing.assert_frame_equal(baseline[1], reuse[1], check_exact=True)
        report["parity"] = {"snapshot_equal": True, "series_exact_equal": True}
        # Warm-up and validation above excluded. Alternate order; every repeat
        # retained, no selected fastest-run or production end-to-end claim.
        for repetition in range(args.repeats):
            for mode in ((False, True) if repetition % 2 == 0 else (True, False)):
                start = time.perf_counter()
                calculation(bars, spy, mode)
                report["timings"].append({"repeat": repetition, "mode": "reuse" if mode else "baseline", "seconds": time.perf_counter() - start})
        if args.repeats:
            for mode in (False, True):
                profiler = cProfile.Profile()
                profiler.runcall(calculation, bars, spy, mode)
                profiler.dump_stats(str(args.output / ("reuse.prof" if mode else "baseline.prof")))
            report["median_seconds"] = {mode: statistics.median(r["seconds"] for r in report["timings"] if r["mode"] == mode) for mode in ("baseline", "reuse")}
        report["limits"] = "Pure real indicator compute only; reuse includes unittest.mock overhead; I/O/overlay/database/job scheduling excluded. One captured series, no fleet-level speed claim."
    else:
        assert args.repeats == 0, "Timing requires captured bars"
        report["limits"] = "Membership validation only; captured bars still required for technical diagnostic"
    destination = args.output / ("timing.json" if args.repeats else "validation.json")
    destination.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({"report": str(destination), "membership_bug_reproduced": True, "actual_job": report.get("actual_job"), "median_seconds": report.get("median_seconds")}))


if __name__ == "__main__":
    main()
