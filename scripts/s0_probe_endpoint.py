"""S0 endpoint probe — saves real UW payloads to docs/uw-samples/.

Reproducible. Re-run when UW changes endpoint shapes.

Usage:
    UW_SCAN_API_KEY=... uv run python scripts/s0_probe_endpoint.py <slug>
    UW_SCAN_API_KEY=... uv run python scripts/s0_probe_endpoint.py --all

Slugs match the endpoint table in the rebuild plan: flow_alerts, iv_rank, etc.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO_ROOT / "docs" / "uw-samples"
TICKER = "TSLA"
BASE_URL = "https://api.unusualwhales.com"
SKEW_DELTA = 25  # UW historical-risk-reversal-skew requires a delta; 25 is the standard 25Δ point.


def _next_friday(today: date) -> str:
    """Return the next Friday's date as ISO string. If today IS Friday, return today + 7."""
    days_ahead = (4 - today.weekday()) % 7 or 7
    return (today + timedelta(days=days_ahead)).isoformat()


EXPIRY = _next_friday(date.today())

# Each entry: slug → (endpoint_path, params_dict).
# `option_contracts` is probed twice: once ticker-scoped, once option_symbol[]-scoped,
# because S1 needs both shapes (broad surface + exact-contract refresh for trade plan economics).
# The option_symbol[] probe uses two placeholder OCC strings — fix them after the first
# probe of `option_contracts` reveals real symbols.
ENDPOINTS: dict[str, tuple[str, dict[str, object]]] = {
    "flow_alerts": ("/api/option-trades/flow-alerts", {"limit": 100}),
    "iv_rank": (f"/api/stock/{TICKER}/iv-rank", {}),
    "volatility_stats": (f"/api/stock/{TICKER}/volatility/stats", {}),
    "realized_volatility": (f"/api/stock/{TICKER}/volatility/realized", {}),
    "term_structure": (f"/api/stock/{TICKER}/volatility/term-structure", {}),
    "interpolated_iv": (f"/api/stock/{TICKER}/interpolated-iv", {}),
    "skew": (
        f"/api/stock/{TICKER}/historical-risk-reversal-skew",
        {"expiry": EXPIRY, "delta": SKEW_DELTA},
    ),
    "greek_exposure": (
        f"/api/stock/{TICKER}/greek-exposure/strike-expiry",
        {"expiry": EXPIRY},
    ),
    "spot_exposures": (
        f"/api/stock/{TICKER}/spot-exposures/expiry-strike",
        {"expirations[]": [EXPIRY]},
    ),
    "greeks": (f"/api/stock/{TICKER}/greeks", {"expiry": EXPIRY}),
    "oi_per_strike": (f"/api/stock/{TICKER}/oi-per-strike", {}),
    "oi_change": (f"/api/stock/{TICKER}/oi-change", {}),
    "max_pain": (f"/api/stock/{TICKER}/max-pain", {}),
    "option_contracts": (f"/api/stock/{TICKER}/option-contracts", {"limit": 50}),
    "option_contracts_by_symbol": (
        f"/api/stock/{TICKER}/option-contracts",
        {"option_symbol[]": ["TSLA260511C00440000", "TSLA260511C00425000"]},
    ),
    "darkpool_ticker": (f"/api/darkpool/{TICKER}", {}),
    "short_data": (f"/api/shorts/{TICKER}/data", {}),
    # S0.7a candidates: cross-ticker bulk endpoints for S2 scan
    "bulk_screener_stocks_sp500": (
        "/api/screener/stocks",
        {"is_s_p_500": "true", "limit": 100},
    ),
    "bulk_market_movers": ("/api/market/movers", {}),
}


def _save(out: Path, payload: dict[str, object]) -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))


def probe(slug: str, client: httpx.Client, api_key: str) -> None:
    if slug not in ENDPOINTS:
        sys.exit(f"unknown slug: {slug!r}. Known: {sorted(ENDPOINTS)}")

    endpoint, params = ENDPOINTS[slug]
    url = f"{BASE_URL}{endpoint}"
    resp = client.get(
        url, params=params, headers={"Authorization": f"Bearer {api_key}"}
    )

    # Save body even when JSON decoding fails — undocumented error payloads are
    # exactly what S0 needs to capture.
    content_type = resp.headers.get("content-type", "")
    body: object
    json_parse_error: str | None = None
    if content_type.startswith("application/json"):
        try:
            body = resp.json()
        except ValueError as exc:
            body = resp.text
            json_parse_error = repr(exc)
    else:
        body = resp.text

    record: dict[str, object] = {
        "endpoint": endpoint,
        "params": dict(params),
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": body,
    }
    if json_parse_error is not None:
        record["json_parse_error"] = json_parse_error

    out = SAMPLES_DIR / f"{slug}.json"
    _save(out, record)
    print(f"{slug:32s} {resp.status_code}  →  {out.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe a UW endpoint and save its real payload."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "slug", nargs="?", default=None, help="endpoint slug (see ENDPOINTS keys)"
    )
    group.add_argument(
        "--all", action="store_true", help="probe every endpoint in ENDPOINTS"
    )
    args = parser.parse_args()

    if not args.all and not args.slug:
        parser.error("provide a slug or --all")

    api_key = os.environ.get("UW_SCAN_API_KEY")
    if not api_key:
        sys.exit("UW_SCAN_API_KEY not set in environment")

    # Pool one client for the whole run — connection reuse matters when probing 17+ endpoints.
    with httpx.Client(timeout=30.0) as client:
        targets = list(ENDPOINTS) if args.all else [args.slug]
        for slug in targets:
            probe(slug, client, api_key)


if __name__ == "__main__":
    main()
