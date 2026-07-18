#!/usr/bin/env python
"""One-off GEX-history cache for the chanlun trust probe's Phase-2 regime gate.

Fetches UW aggregate greek-exposure per universe ticker (timeframe=3Y — the tier
cap is ~730 trading days, so this reaches back to ~2023-08) and caches
net dealer gamma = call_gamma + put_gamma per (ticker, date). The probe reads this
cache to tag each divergence's confirmation date with its dealer-gamma regime.

Research-endorsed use of GEX: a HOLD/regime gate (positive gamma = dealers dampen
moves → mean-reverting; negative gamma = amplify), NOT a directional predictor.
Coverage caps at ~2.8y, so only post-2023-08 confirmations get a regime.

Durable artifact (persist-research rule). Reproduce:
  uv run python scripts/research/_chanlun_trust_gex.py
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

OUT_DIR = Path("docs/research/2026-07-18-chanlun-trust-silver")
UNIVERSE_CSV = OUT_DIR / "universe.csv"
GEX_CSV = OUT_DIR / "gex_history.csv"
UW_URL = "https://api.unusualwhales.com/api/stock/{ticker}/greek-exposure"


def _api_key() -> str:
    env = Path(".env").read_text()
    m = re.search(r"^UW_SCAN_API_KEY\s*=\s*(.+)$", env, re.M)
    if not m:
        raise SystemExit("UW_SCAN_API_KEY not found in .env")
    return m.group(1).strip().strip('"').strip("'")


def _rows_of(payload) -> list[dict]:
    if isinstance(payload, dict):
        return payload.get("data") or payload.get("result") or []
    return payload if isinstance(payload, list) else []


def main() -> None:
    key = _api_key()
    tickers = [
        line.split(",")[0]
        for line in UNIVERSE_CSV.read_text().splitlines()[1:]
        if line.strip()
    ]
    out: list[str] = ["ticker,date,net_gamma"]
    kept = 0
    with httpx.Client(timeout=30.0) as c:
        for i, t in enumerate(tickers, 1):
            try:
                r = c.get(
                    UW_URL.format(ticker=t),
                    params={"timeframe": "3Y"},
                    headers={"Authorization": f"Bearer {key}"},
                )
                r.raise_for_status()
                rows = _rows_of(r.json())
            except Exception as exc:  # never-raise: a missing name just gets no regime
                print(f"  [{i}/{len(tickers)}] {t}: FAIL {exc!r}")
                continue
            n = 0
            for row in rows:
                d = row.get("date")
                cg = row.get("call_gamma")
                pg = row.get("put_gamma")
                if d is None or cg is None or pg is None:
                    continue
                out.append(f"{t},{d},{float(cg) + float(pg)}")
                n += 1
            if n:
                kept += 1
            print(f"  [{i}/{len(tickers)}] {t}: {n} rows")
            time.sleep(0.15)  # ponytail: gentle spacing, 223 calls is trivial vs budget
    GEX_CSV.write_text("\n".join(out) + "\n")
    print(f"kept {kept}/{len(tickers)} tickers, {len(out) - 1} rows -> {GEX_CSV}")


if __name__ == "__main__":
    main()
