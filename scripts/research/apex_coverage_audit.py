"""Audit apex daily-bar coverage for the S&P 500 + Nasdaq-100 universe.

For every ticker in universe_union.csv, probe apex `/bars/{ticker}?timeframe=1d`
back to 1990 and classify history depth. Produces the enrichment worklist:
who lacks full-since-IPO daily history.

Reproduce:
  uv run python scripts/research/apex_coverage_audit.py \
    --universe-dir docs/research/alpha191-short-swing/universe \
    --apex-url http://100.66.147.98:8322
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# The livewire backfill floor: names truncated to this date existed earlier but
# apex only holds post-floor bars -> enrichment needed. (Verified 2026-07-06:
# SPY/IWM/DIA/sector-SPDRs all start 2021-05-18/2021-06-11; deep equities 1995.)
FLOOR_LO, FLOOR_HI = "2021-05-10", "2021-06-30"
MIN_FULL_BARS = 200  # < ~1yr of history is unusable regardless of start date


def probe(apex_url: str, ticker: str) -> dict:
    url = (
        f"{apex_url}/bars/{ticker}?timeframe=1d"
        f"&start=1990-01-01T00:00:00Z&end=2026-07-06T00:00:00Z"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            d = json.load(resp)
        bars = d.get("bars", [])
        first = bars[0]["time"][:10] if bars else ""
        last = bars[-1]["time"][:10] if bars else ""
        return {
            "ticker": ticker,
            "found": bool(bars),
            "first_bar": first,
            "last_bar": last,
            "bar_count": len(bars),
        }
    except Exception as exc:  # noqa: BLE001 (audit tool: record, don't crash)
        return {
            "ticker": ticker,
            "found": False,
            "first_bar": "",
            "last_bar": "",
            "bar_count": 0,
            "error": repr(exc)[:120],
        }


def classify(row: dict) -> str:
    if not row["found"] or row["bar_count"] == 0:
        return "missing"
    if row["bar_count"] < MIN_FULL_BARS:
        return "thin"  # e.g. BRK.B = 31 bars: broken, needs enrichment
    first = row["first_bar"]
    if first < FLOOR_LO:
        return "full"
    if FLOOR_LO <= first <= FLOOR_HI:
        return "floor_truncated"
    return "post_floor_start"  # genuine recent IPO OR partial — user verifies


def load_col(path: Path, col: str = "ticker") -> set[str]:
    with path.open() as f:
        return {r[col].strip().upper() for r in csv.DictReader(f) if r.get(col)}


def run(universe_dir: Path, apex_url: str, workers: int) -> None:
    uni = sorted(load_col(universe_dir / "universe_union.csv"))
    sp = load_col(universe_dir / "sp500_current.csv")
    ndx = load_col(universe_dir / "ndx100_current.csv")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda t: probe(apex_url, t), uni))

    rows = []
    for r in results:
        status = classify(r)
        rows.append(
            {
                "ticker": r["ticker"],
                "in_sp500": r["ticker"] in sp,
                "in_ndx100": r["ticker"] in ndx,
                "found": r["found"],
                "first_bar": r["first_bar"],
                "last_bar": r["last_bar"],
                "bar_count": r["bar_count"],
                "status": status,
                "needs_enrichment": status in {"missing", "thin", "floor_truncated"},
                "error": r.get("error", ""),
            }
        )
    rows.sort(key=lambda x: (not x["needs_enrichment"], x["status"], x["ticker"]))

    out = universe_dir / "coverage"
    out.mkdir(exist_ok=True)
    fields = [
        "ticker",
        "in_sp500",
        "in_ndx100",
        "found",
        "first_bar",
        "last_bar",
        "bar_count",
        "status",
        "needs_enrichment",
        "error",
    ]
    with (out / "apex_coverage.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    need = [r for r in rows if r["needs_enrichment"]]
    with (out / "needs_enrichment.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(need)

    from collections import Counter

    counts = Counter(r["status"] for r in rows)
    lines = [f"- {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    summary = f"""# apex coverage audit — S&P 500 + Nasdaq-100 ({len(rows)} tickers)

Probed apex `/bars/{{t}}?timeframe=1d` back to 1990 (apex_url={apex_url}).

## Status breakdown
{chr(10).join(lines)}

## Needs enrichment: {len(need)} tickers
`missing` (no bars), `thin` (<{MIN_FULL_BARS} bars), or `floor_truncated`
(starts in {FLOOR_LO}..{FLOOR_HI}, the livewire backfill floor — existed earlier).
`post_floor_start` names are likely genuine post-2021 IPOs with full history;
verify individually. See needs_enrichment.csv for the actionable list.

Files: coverage/apex_coverage.csv, coverage/needs_enrichment.csv
"""
    (out / "coverage_summary.md").write_text(summary)
    print(summary)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--universe-dir", required=True)
    p.add_argument("--apex-url", default="http://100.66.147.98:8322")
    p.add_argument("--workers", type=int, default=10)
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    run(Path(a.universe_dir), a.apex_url, a.workers)
