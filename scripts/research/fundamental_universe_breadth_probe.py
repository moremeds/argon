#!/usr/bin/env python
"""How wide can the fundamental cross-section actually get?

Follows `fundamental_signal_validation.py`, whose verdict was NOT "the composite
fails" but "the composite is untestable at 25 names". Per-quarter IC noise runs
sigma ~ 1/sqrt(N-1), so detecting a realistic IC of 0.03 needs 444 quarters at
this cohort's median 11 names, versus 22 quarters at 200. Breadth is the only
lever that moves; quarters accrue at four a year.

This probe measures the ceiling on N. Two independent constraints, both of which
must hold for a name to be usable:

  1. PRICE  - the local lake mirror must carry deep daily history.
  2. FUNDAMENTALS - UW must return quarterly statements over the same span.

Measured on every candidate, not sampled and extrapolated. Extrapolating one
ticker's coverage to a cohort is the exact error this project already made once
(NVDA's 83% PIT join rate generalized to a cohort whose real rate was 45.2%).

SURVIVORSHIP IS NOT FIXABLE HERE, AND THAT IS THE POINT
------------------------------------------------------
Probed separately: ATVI, XLNX, TWTR, SIVB, FRC, VMW are absent from the lake
AND return HTTP 200 with an empty array from UW. Note the distinction that
matters - 200-with-zero-rows is a genuine "no data", not a transport error
misread as absence.

Both sources are live-tickers-only. So widening the universe buys statistical
power and nothing else: it CANNOT remove survivorship bias, because the names
that failed are not purchasable at any N. SIVB and FRC are the instructive
cases - actual failures, which is precisely what survivorship drops.

Any result from a widened test therefore still describes "what predicted returns
among companies that survived to 2026". That is a real limit on interpretation,
not a caveat to bury.

Reproduce:

    UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_universe_breadth_probe.py

Writes `universe_breadth.json` + `universe-breadth.md` under
`docs/research/2026-08-11-fundamental-signal-validation/`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pyarrow.parquet as pq

OUT_DIR = Path("docs/research/2026-08-11-fundamental-signal-validation")
LAKE = Path.home() / "market-warehouse/data-lake/bronze/asset_class=equity"
UW_BASE = "https://api.unusualwhales.com"

# Candidate gate on the price side. 2013 start gives ~52 quarters, comfortably
# past the ~22 that N=200 needs.
MIN_BARS = 2500
MAX_START = "2013-01-01"

# Fundamental gate. 40 quarters of statements over a 52-quarter price window.
MIN_QUARTERS = 40

# Names known to have delisted/merged, carried here so the survivorship claim in
# the docstring is regenerated as evidence rather than asserted from memory.
DELISTED_CONTROLS = ["ATVI", "XLNX", "TWTR", "SIVB", "FRC", "VMW"]

THROTTLE_S = 0.05


def _get(c: httpx.Client, url: str, params: dict, tries: int = 4):
    """Retry transient network failures. A ReadTimeout partway through ~280
    calls would otherwise lose the whole run."""
    for i in range(tries):
        try:
            return c.get(url, params=params)
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError):
            if i == tries - 1:
                raise
            time.sleep(2**i)
    raise RuntimeError("unreachable")


def lake_candidates() -> list[dict[str, Any]]:
    """Symbols whose local price history is deep enough to test on."""
    out = []
    for d in sorted(LAKE.iterdir()):
        f = d / "1d.parquet"
        if not f.exists():
            continue
        try:
            dates = (
                pq.read_table(f, columns=["trade_date"])
                .column("trade_date")
                .to_pylist()
            )
        except Exception:
            continue
        if not dates:
            continue
        first, last, n = str(min(dates)), str(max(dates)), len(dates)
        if n >= MIN_BARS and first <= MAX_START:
            out.append(
                {
                    "ticker": d.name.split("=")[1],
                    "bars": n,
                    "first_bar": first,
                    "last_bar": last,
                }
            )
    return out


def uw_quarters(c: httpx.Client, ticker: str) -> dict[str, Any]:
    """Quarterly income-statement coverage for one name.

    Records http_status and distinguishes 200-with-zero-rows (real absence)
    from a transport failure (unknown). Never collapses both to 0.
    """
    r = _get(c, f"/api/stock/{ticker}/income-statements", {"limit": 200})
    time.sleep(THROTTLE_S)
    if r.status_code != 200:
        return {"http_status": r.status_code, "quarters": None}
    rows = r.json().get("data") or []
    ends = sorted(
        str(x.get("fiscal_date_ending")) for x in rows if x.get("fiscal_date_ending")
    )
    return {
        "http_status": 200,
        "quarters": len(rows),
        "first_period": ends[0] if ends else None,
        "last_period": ends[-1] if ends else None,
    }


def main() -> int:
    key = os.environ.get("UW_SCAN_API_KEY")
    if not key:
        print("UW_SCAN_API_KEY not set", file=sys.stderr)
        return 2
    if not LAKE.exists():
        print(f"lake mirror missing: {LAKE}", file=sys.stderr)
        return 2

    print("== scanning local lake for deep-history names")
    cands = lake_candidates()
    print(f"   {len(cands)} candidates (>={MIN_BARS} bars, start <= {MAX_START})")

    with httpx.Client(
        base_url=UW_BASE,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=45.0,
    ) as c:
        print(f"\n== probing UW fundamentals for {len(cands)} names")
        for i, row in enumerate(cands, 1):
            row.update(uw_quarters(c, row["ticker"]))
            if i % 25 == 0:
                print(f"   {i}/{len(cands)}", flush=True)

        print("\n== delisted controls (survivorship check)")
        controls = {}
        for t in DELISTED_CONTROLS:
            controls[t] = uw_quarters(c, t)
            controls[t]["in_lake"] = (LAKE / f"symbol={t}").exists()
            print(
                f"   {t:6} uw_http={controls[t]['http_status']} "
                f"uw_quarters={controls[t]['quarters']} "
                f"in_lake={controls[t]['in_lake']}"
            )

    usable = [r for r in cands if (r.get("quarters") or 0) >= MIN_QUARTERS]
    errors = [r for r in cands if r.get("quarters") is None]

    payload = {
        "probed_at": "2026-08-11",
        "reproduce": "UW_SCAN_API_KEY=... uv run python "
        "scripts/research/fundamental_universe_breadth_probe.py",
        "gates": {
            "min_bars": MIN_BARS,
            "max_start": MAX_START,
            "min_quarters": MIN_QUARTERS,
        },
        "lake_candidates": len(cands),
        "usable": len(usable),
        "http_errors": len(errors),
        "delisted_controls": controls,
        "names": cands,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "universe_breadth.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT_DIR / "universe-breadth.md").write_text(_render(payload, usable, errors))

    print("\n== result")
    print(f"   lake candidates      {len(cands)}")
    print(f"   with >={MIN_QUARTERS} UW quarters  {len(usable)}")
    print(f"   http errors          {len(errors)}")
    if usable:
        spans = Counter(r["first_period"][:4] for r in usable if r.get("first_period"))
        print(f"   earliest fundamental year, most common: {spans.most_common(3)}")
    print(f"\nwrote {OUT_DIR}/universe_breadth.json and universe-breadth.md")
    return 0


def _render(p: dict, usable: list, errors: list) -> str:
    g = p["gates"]
    lines = [
        "# Universe breadth — how wide can the cross-section get?",
        "",
        f"*Probed {p['probed_at']} · REGENERATED on every run · "
        "interpretation lives in `VERDICT.md`*",
        "",
        "```bash",
        p["reproduce"],
        "```",
        "",
        f"Gates: local price history >= {g['min_bars']} daily bars starting "
        f"<= {g['max_start']}, AND >= {g['min_quarters']} quarters of UW "
        "statements.",
        "",
        "| | count |",
        "|---|---:|",
        f"| lake candidates (price gate) | {p['lake_candidates']} |",
        f"| **usable (both gates)** | **{p['usable']}** |",
        f"| UW http errors (unknown, not absent) | {p['http_errors']} |",
        "",
        "## Survivorship controls",
        "",
        "Delisted/merged names, probed to establish whether a point-in-time "
        "universe is constructible at all. `uw_quarters: 0` with `http: 200` is "
        "a genuine empty result, not a transport failure.",
        "",
        "| Ticker | in lake | UW http | UW quarters |",
        "|---|---|---:|---:|",
    ]
    for t, r in p["delisted_controls"].items():
        lines.append(f"| {t} | {r['in_lake']} | {r['http_status']} | {r['quarters']} |")
    lines += [
        "",
        "Both sources carry live tickers only. Widening the universe buys "
        "statistical power; it cannot buy survivorship correction.",
        "",
    ]
    if errors:
        lines += [
            "## HTTP errors (excluded, status unknown)",
            "",
            ", ".join(f"{r['ticker']} ({r['http_status']})" for r in errors),
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
