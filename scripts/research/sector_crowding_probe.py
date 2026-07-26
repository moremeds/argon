"""Sector-crowding probe: absolute vs per-ETF-percentile ranking.

Answers the question that set the scoring design: does the source framework's
absolute 3M-relative-return ranking measure crowding, or does it just measure
beta? Prints both rankings side by side plus the trailing SD of each ETF's
3M spread, and writes the full result set to JSON.

Reproduce:
    uv run python scripts/research/sector_crowding_probe.py

Writes: docs/research/2026-07-26-sector-crowding-probe.json
"""

from __future__ import annotations

import json
import pathlib
import statistics

import httpx

from uw_scan.config import Settings
from uw_scan.reports.sector_crowding import (
    BENCHMARK,
    FLOW_WINDOW,
    RETURN_WINDOW,
    SECTOR_CROWDING_TICKERS,
)
from uw_scan.storage.market_data import normalize_etf_aum

BASE = "https://api.unusualwhales.com"
OUT = pathlib.Path("docs/research/2026-07-26-sector-crowding-probe.json")


def _fetch_flows(client: httpx.Client, ticker: str) -> list[dict]:
    r = client.get(
        f"{BASE}/api/etfs/{ticker}/in-outflow",
        params={"start_date": "2025-07-01", "end_date": "2026-07-24"},
    )
    r.raise_for_status()
    # UW returns newest-first; flip to chronological.
    return sorted(r.json().get("data", []), key=lambda x: x["date"])


def _fetch_aum(client: httpx.Client, ticker: str) -> float:
    r = client.get(f"{BASE}/api/etfs/{ticker}/info")
    r.raise_for_status()
    return float(normalize_etf_aum(r.json()["data"]["aum"]))


def _ret(rows: list[dict], end: int, window: int) -> float | None:
    start = end - window
    if start < 0:
        return None
    a, b = float(rows[start]["close"]), float(rows[end]["close"])
    return (b / a - 1.0) * 100.0 if a else None


def _pct_rank(series: list[float], value: float) -> float:
    if not series:
        return float("nan")
    return 100.0 * sum(1 for s in series if s < value) / len(series)


def main() -> None:
    settings = Settings.from_env()
    headers = {
        "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
        "Accept": "application/json",
    }
    out = []
    dropped_total = 0
    with httpx.Client(timeout=40, headers=headers) as client:
        bench_rows = _fetch_flows(client, BENCHMARK)
        bench_by_date = {r["date"]: r for r in bench_rows}
        # SPY's own 63-session return, printed for context only. It is NOT the
        # subtrahend for `rel` -- see the per-ticker join below.
        bench_3m = _ret(bench_rows, len(bench_rows) - 1, RETURN_WINDOW)

        for ticker in SECTOR_CROWDING_TICKERS:
            try:
                raw = _fetch_flows(client, ticker)
                aum = _fetch_aum(client, ticker)
            except Exception as exc:  # noqa: BLE001 - probe script
                print(f"{ticker}: FAILED {exc}")
                continue

            # Inner-join on date, same as reports/sector_crowding.py. Indexing
            # `rows` and `bench` at the same position assumes both series carry
            # identical sessions; one dropped UW row shifts every later index
            # and silently compares different days. `dropped` should be 0 --
            # if it is not, the fixtures frozen from an earlier position-aligned
            # run are stale and must be re-derived from this output.
            rows = [r for r in raw if r["date"] in bench_by_date]
            bench = [bench_by_date[r["date"]] for r in rows]
            dropped = len(raw) - len(rows)
            dropped_total += dropped
            if dropped:
                print(f"{ticker}: dropped {dropped} unmatched session(s)")

            if len(rows) < RETURN_WINDOW + FLOW_WINDOW:
                print(f"{ticker}: only {len(rows)} sessions, skipping")
                continue

            last = len(rows) - 1
            # Subtract the benchmark's return over THIS ticker's aligned
            # window, not SPY's own last-63-rows return. They are the same
            # number only when the two series carry identical sessions. SOXX
            # and IGV return 238 sessions to SPY's 267, so 63 rows back lands
            # ~135 calendar days ago for them and ~92 for SPY -- subtracting
            # SPY's 92-day return from their 135-day return overstates the
            # spread by ~5.2 points and inflates the percentile (SOXX 97th ->
            # 99th). `rel_hist` below already joins correctly; this line used
            # to not, so today's value was scored against a history computed a
            # different way. reports/sector_crowding.py has always used the
            # joined bench (`_window_return(bench, last, RETURN_WINDOW)`) --
            # this makes the probe agree with the module it is checking.
            rel = _ret(rows, last, RETURN_WINDOW) - _ret(bench, last, RETURN_WINDOW)
            flow_1m = sum(float(r["change_prem"]) for r in rows[-FLOW_WINDOW:])
            flow_aum = 100.0 * flow_1m / aum

            rel_hist = []
            for i in range(RETURN_WINDOW + FLOW_WINDOW, len(rows)):
                a, b = _ret(rows, i, RETURN_WINDOW), _ret(bench, i, RETURN_WINDOW)
                if a is not None and b is not None:
                    rel_hist.append(a - b)

            out.append(
                {
                    "ticker": ticker,
                    "aum_b": aum / 1e9,
                    "rel_3m": rel,
                    "rel_pctile": _pct_rank(rel_hist, rel),
                    "flow_aum": flow_aum,
                    "rel_hist_sd": statistics.pstdev(rel_hist) if rel_hist else 0.0,
                    "n_hist": len(rel_hist),
                    "dropped_sessions": dropped,
                }
            )

    print(f"\n{BENCHMARK} 3M return: {bench_3m:+.2f}%")
    print(f"unmatched sessions dropped across the universe: {dropped_total}\n")
    hdr = (
        f"{'ETF':<6}{'AUM$B':>8}{'3M vs SPY':>11}{'  pctile':>9}"
        f"{'1M flow/AUM':>13}{'  relSD':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(out, key=lambda x: -x["rel_3m"]):
        print(
            f"{r['ticker']:<6}{r['aum_b']:>8.1f}{r['rel_3m']:>+10.2f}%"
            f"{r['rel_pctile']:>8.0f}%{r['flow_aum']:>+12.2f}%"
            f"{r['rel_hist_sd']:>8.1f}"
        )

    print(
        "\nABSOLUTE ranking:  ",
        " > ".join(r["ticker"] for r in sorted(out, key=lambda x: -x["rel_3m"])),
    )
    print(
        "PERCENTILE ranking:",
        " > ".join(r["ticker"] for r in sorted(out, key=lambda x: -x["rel_pctile"])),
    )

    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
