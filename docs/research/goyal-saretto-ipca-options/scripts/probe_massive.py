"""Authoritative re-probe of massive.com endpoints for fundamentals coverage.

Reads MASSIVE_API_KEY + MASSIVE_BASE_URL from .env in the project root.
Emits JSON to stdout with per-endpoint: path, status, latency_ms, top-level
keys, row counts, date ranges, sample fields.

Run from any cwd; resolves .env from /Users/chenxi/projects/unusual-whales/.env.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

ENV_PATH = Path("/Users/chenxi/projects/unusual-whales/.env")
env = dotenv_values(ENV_PATH)
API_KEY = env.get("MASSIVE_API_KEY")
BASE_URL = env.get("MASSIVE_BASE_URL", "https://api.massive.com")

if not API_KEY:
    sys.stderr.write("MASSIVE_API_KEY missing in .env\n")
    sys.exit(2)

# Endpoints to probe. Tuple: (label, path, params, why_we_care)
PROBES: list[tuple[str, str, dict[str, Any], str]] = [
    # --- Fundamentals ---
    (
        "fundamentals_v2_AAPL",
        "/v2/reference/financials/AAPL",
        {"limit": 100, "type": "Q"},
        "Legacy Polygon endpoint — 103 raw Compustat-style fields per quarter",
    ),
    (
        "fundamentals_v2_AAPL_annual",
        "/v2/reference/financials/AAPL",
        {"limit": 100, "type": "Y"},
        "Annual variant of /v2",
    ),
    (
        "fundamentals_vx_AAPL",
        "/vX/reference/financials",
        {"ticker": "AAPL", "limit": 100, "timeframe": "quarterly"},
        "Modern Polygon endpoint — ~55 fields, current data",
    ),
    (
        "fundamentals_vx_AAPL_annual",
        "/vX/reference/financials",
        {"ticker": "AAPL", "limit": 50, "timeframe": "annual"},
        "Annual variant of /vX",
    ),
    (
        "fundamentals_vx_RBLX",
        "/vX/reference/financials",
        {"ticker": "RBLX", "limit": 30, "timeframe": "quarterly"},
        "Newer-IPO coverage check (RBLX listed 2021)",
    ),
    (
        "fundamentals_vx_TSLA",
        "/vX/reference/financials",
        {"ticker": "TSLA", "limit": 30, "timeframe": "quarterly"},
        "Mid-cap parity check (TSLA)",
    ),
    # --- Short interest ---
    (
        "short_interest_AAPL",
        "/stocks/v1/short-interest",
        {"ticker": "AAPL", "limit": 500},
        "FINRA biweekly short interest — paper's RSI char",
    ),
    # --- Reference / universe ---
    (
        "tickers_AAPL",
        "/v3/reference/tickers/AAPL",
        {},
        "CIK, SIC, exchange, share-code-equivalent type",
    ),
    (
        "tickers_list",
        "/v3/reference/tickers",
        {"market": "stocks", "active": "true", "limit": 5, "type": "CS"},
        "Universe filter — does ?type=CS work for common-stock-only?",
    ),
    # --- Corporate actions ---
    (
        "dividends_AAPL",
        "/v3/reference/dividends",
        {"ticker": "AAPL", "limit": 50},
        "Ex-div dates — paper's 'no dividend during holding period' filter",
    ),
    (
        "splits_AAPL",
        "/v3/reference/splits",
        {"ticker": "AAPL", "limit": 50},
        "Splits — share adjustment for NewIss",
    ),
    # --- Live data ---
    (
        "snapshot_AAPL",
        "/v2/snapshot/locale/us/markets/stocks/tickers/AAPL",
        {},
        "Live spot for stock-price char",
    ),
    (
        "market_status",
        "/v1/marketstatus/now",
        {},
        "Calendar utility — sanity for trading-day math",
    ),
    # --- Gaps (known 404, confirm) ---
    (
        "gap_13f_v1",
        "/rest/stocks/filings/13-f-filings",
        {"ticker": "AAPL"},
        "InstOwn — 13-F filings (docs path, expected 404)",
    ),
    (
        "gap_13f_v2",
        "/vX/reference/13-f",
        {"ticker": "AAPL"},
        "InstOwn — Polygon-style guess (expected 404)",
    ),
    (
        "gap_benzinga_earnings",
        "/rest/partners/benzinga/earnings",
        {"ticker": "AAPL"},
        "AnalystDisp — Benzinga earnings (docs path, expected 404)",
    ),
    (
        "gap_benzinga_analyst",
        "/rest/partners/benzinga/analyst-ratings",
        {"ticker": "AAPL"},
        "AnalystDisp — Benzinga analyst ratings (docs path, expected 404)",
    ),
]


def shape_summary(payload: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Summarize a JSON payload: list-of-dict → {len, sample_keys}, dict → keys."""
    if depth > max_depth:
        return "..."
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, list):
                if v and isinstance(v[0], dict):
                    out[k] = {
                        "_list_len": len(v),
                        "_first_keys": sorted(list(v[0].keys()))[:25],
                    }
                else:
                    out[k] = {"_list_len": len(v)}
            elif isinstance(v, dict):
                out[k] = shape_summary(v, depth + 1, max_depth)
            else:
                out[k] = type(v).__name__
        return out
    return type(payload).__name__


def date_range_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull min/max date across known date-bearing fields."""
    date_keys = (
        "filing_date",
        "fiscal_period_end_date",
        "period_of_report",
        "calendarDate",
        "date",
        "settlement_date",
        "ex_dividend_date",
        "execution_date",
    )
    seen: list[tuple[str, str]] = []
    for row in results:
        for k in date_keys:
            if k in row and row[k]:
                seen.append((k, str(row[k])))
                break
    if not seen:
        return {"_no_date_field": True}
    seen.sort(key=lambda x: x[1])
    return {"earliest": seen[0], "latest": seen[-1], "n": len(seen)}


def probe(label: str, path: str, params: dict[str, Any], why: str) -> dict[str, Any]:
    url = BASE_URL.rstrip("/") + path
    headers = {"Authorization": f"Bearer {API_KEY}"}
    t0 = time.time()
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.get(url, params=params, headers=headers)
        latency_ms = int((time.time() - t0) * 1000)
        rec: dict[str, Any] = {
            "label": label,
            "path": path,
            "params": params,
            "why": why,
            "status": r.status_code,
            "latency_ms": latency_ms,
        }
        if r.status_code == 200:
            try:
                payload = r.json()
            except Exception as e:
                rec["error"] = f"json-decode: {e}"
                rec["text_head"] = r.text[:300]
                return rec
            rec["top_level_keys"] = (
                sorted(list(payload.keys())) if isinstance(payload, dict) else None
            )
            rec["shape"] = shape_summary(payload)
            # results list date range
            results = None
            if isinstance(payload, dict):
                for k in ("results", "data", "tickers"):
                    if isinstance(payload.get(k), list):
                        results = payload[k]
                        break
            if results:
                rec["results_count"] = len(results)
                if results and isinstance(results[0], dict):
                    rec["first_row_keys"] = sorted(list(results[0].keys()))
                    rec["field_count"] = len(results[0])
                    rec["date_range"] = date_range_from_results(results)
        else:
            rec["body_head"] = r.text[:300]
        return rec
    except Exception as e:
        return {
            "label": label,
            "path": path,
            "params": params,
            "why": why,
            "status": None,
            "error": f"{type(e).__name__}: {e}",
        }


out = {
    "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "base_url": BASE_URL,
    "probes": [],
}
for label, path, params, why in PROBES:
    rec = probe(label, path, params, why)
    out["probes"].append(rec)

json.dump(out, sys.stdout, indent=2, default=str)
