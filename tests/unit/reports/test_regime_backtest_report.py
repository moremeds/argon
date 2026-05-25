"""Snapshot test for the markdown renderer.

The renderer must reproduce docs/research/regime/cri-backtest.md byte-for-byte
when fed the same data the legacy write_report() saw. The fixture for `daily`
comes from re-parsing the checked-in CSV — the CSV is the recorded output of
the same rolling_compute() that produced the markdown.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from uw_scan.reports.regime_backtest_report import render_backtest_markdown

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MD_PATH = _REPO_ROOT / "docs" / "research" / "regime" / "cri-backtest.md"
_CSV_PATH = _REPO_ROOT / "docs" / "research" / "regime" / "cri-backtest.csv"


def _load_daily() -> list[dict]:
    daily: list[dict] = []
    with _CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            daily.append(
                {
                    "trade_date": date.fromisoformat(row["date"]),
                    "score": float(row["score"]),
                    "level": row["level"],
                    "payload": {
                        "fired": row["fired"] == "True",
                        "vix": float(row["vix"]),
                        "vvix": float(row["vvix"]),
                        "cor1m": float(row["cor1m"]),
                        "spx_distance_pct": float(row["spx_distance_pct"]),
                    },
                }
            )
    return daily


def test_render_matches_existing_cri_backtest_md_byte_for_byte() -> None:
    daily = _load_daily()
    run = {
        "indicator": "cri",
        "composite_version": "3",
        # NOTE: start_date is intentionally NOT used by the renderer for the
        # "Date range" line — the renderer derives the visible window from
        # daily[0].trade_date (rolling_compute skips the first 150 sessions).
        "start_date": date(2006, 1, 1),
        "end_date": daily[-1]["trade_date"],
        "window_days": 150,
        "n_days": len(daily),
        "summary": {"oos": None, "extras": {}},
    }
    expected = _MD_PATH.read_text(encoding="utf-8")
    actual = render_backtest_markdown(run, daily)
    assert actual == expected, (
        "renderer drifted from cri-backtest.md — diff intentional? "
        "If yes, regenerate the fixture in the SAME PR; if no, fix the "
        "renderer (window-start uses daily[0].trade_date, not run.start_date)."
    )
