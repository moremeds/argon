#!/usr/bin/env python3
"""Track 3 — empirically probe how far back UW's risk-reversal-skew history reaches.

The banked ``risk_reversal_skew_history`` starts 2025-05-13. Is that because argon only
began banking then, or because UW genuinely caps the history? The engine accumulates one
date forward per night, which *suggests* a short per-call window — but that's inference.
This makes the actual calls and reports the returned date span per expiry, so "deeper
time is/ isn't available" is a measured fact, not a guess.

Endpoint: GET /api/stock/{ticker}/historical-risk-reversal-skew?expiry=YYYY-MM-DD&delta=25
Uses a handful of UW requests (budget-approved). Read-only; persists nothing.

Reproduce:
    export UW_SCAN_API_KEY=...   # or leave unset to read argon .env
    uv run --directory /Users/chenxi/projects/argon \
        python .worktrees/skew-directional-probe/scripts/oneshot/skew_backfill_probe.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

BASE = "https://api.unusualwhales.com"
SLUG = "/api/stock/{ticker}/historical-risk-reversal-skew"
# (ticker, expiry) pairs: a long-lived far expiry (max possible lookback) + a near one.
PROBES = [
    ("QQQ", "2026-12-18"),
    ("QQQ", "2027-01-15"),
    ("QQQ", "2026-09-18"),
    ("NVDA", "2026-12-18"),
    ("SPY", "2027-01-15"),
]


def _api_key() -> str:
    key = os.environ.get("UW_SCAN_API_KEY")
    if key:
        return key
    env = Path("/Users/chenxi/projects/argon/.env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("UW_SCAN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no UW_SCAN_API_KEY in env or argon .env")


def _dates(body: object) -> list[str]:
    """Pull whatever date field the payload carries out of a list-or-wrapped-list body."""
    rows = body.get("data", body) if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if isinstance(r, dict):
            for k in ("date", "market_date", "timestamp", "trading_date"):
                if r.get(k):
                    out.append(str(r[k])[:10])
                    break
    return sorted(out)


def main() -> None:
    key = _api_key()
    with httpx.Client(timeout=30.0) as c:
        for ticker, expiry in PROBES:
            url = f"{BASE}{SLUG.format(ticker=ticker)}"
            try:
                resp = c.get(
                    url,
                    params={"expiry": expiry, "delta": 25},
                    headers={"Authorization": f"Bearer {key}"},
                )
            except httpx.HTTPError as exc:
                print(f"{ticker} exp={expiry}: transport error {exc!r}")
                continue
            if resp.status_code != 200:
                print(
                    f"{ticker} exp={expiry}: HTTP {resp.status_code} {resp.text[:160]}"
                )
                continue
            body = resp.json()
            ds = _dates(body)
            if not ds:
                # show the shape so we can adapt if the date key differs
                shape = json.dumps(body, default=str)[:240]
                print(f"{ticker} exp={expiry}: 200 but no dates parsed; shape={shape}")
                continue
            print(
                f"{ticker} exp={expiry}: n={len(ds)}  span {ds[0]} .. {ds[-1]}  "
                f"(lookback ~{(len(ds))} obs)"
            )


if __name__ == "__main__":
    main()
