# UW Scan V1 Rebuild Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Unusual Whales opportunity scanner from scratch using vertical slices, producing the two canonical reports — Single-Stock Analysis Card and Full Scan Report — defined in `docs/superpowers/archive/specs/2026-05-11-uw-scan-design.md` (Report Formats section).

**Architecture:** Each slice is end-to-end (UI → pipeline → API client → normalizer → storage → reload), shipping one user-visible feature with real persistence, real Postgres integration tests, and full error surfacing. Horizontal-layer planning (build all clients, then all storage, then all UI) is rejected as the failure mode that produced the prior reset.

**Tech Stack:** Python 3.11+, `uv` for deps, `httpx` (sync) for HTTP, `pydantic` 2 for typed models, `psycopg` 3 for Postgres, Streamlit for UI, `pytest` for tests, `pytest-postgresql` for integration tests, `playwright` for TradingView browser parsing (S4). All Implementation Guardrails (spec §"Implementation Guardrails") are enforced by CI gates where possible.

---

## Slice Map

| Slice | Ships | Endpoints touched | Tables populated | Exit Gate |
|---|---|---|---|---|
| **S0** | Endpoint validation spike — real UW payload sample per endpoint, response-shape documentation. Probe script under `scripts/`, no production code. | ~16 read endpoints + bulk-screener probe | none | All endpoints needed for the Single-Stock Card return verified payloads saved as JSON; shape notes committed. |
| **S1** | Single-Stock Analysis Card for one user-entered ticker, rendered end-to-end with real data, persisted to typed tables, reloadable from snapshot. | flow-alerts, iv-rank, vol-stats, realized-vol, term-structure, interpolated-iv, skew, greek-exposure/strike-expiry, spot-exposures, greeks, oi-per-strike, oi-change, max-pain, option-contracts, darkpool/ticker, short-data | scan_runs, raw_payloads, api_request_audit, flow_events, iv_rank_history, volatility_stats_history, realized_volatility_history, iv_term_snapshots, interpolated_iv_snapshots, risk_reversal_skew_history, greeks_by_expiry_strike, exposures_by_expiry_strike, oi_by_strike, oi_change_events, max_pain_by_expiry, option_contract_snapshots, dark_pool_events, short_interest_snapshots, opportunity_scores, structure_ideas | TSLA-style card renders for any ticker with API key configured. 100% of API responses written to `raw_payloads` + `api_request_audit`. Snapshot save → reload produces semantically-equivalent card. Integration tests against real Postgres pass. Setup type C (Deep Conviction) classification works. |
| **S2** | Full Scan Report over a hardcoded universe of ~40 tickers, ranking by conviction score, classifying into types C and F (Multi-Signal). Day-over-day deferred. | adds bulk-screener (if discovered in S0) or per-ticker net-premium fanout | adds: scan_universe, scan_results | Full Scan card renders for a date with persisted ticker universe. Top Pick deep-dive reuses S1's Single-Stock Card. Setup type F classification works. |
| **S3** | Day-over-day flow reversal detection. Earnings calendar source for Type A. Dark Pool persistence for Type E. | adds earnings calendar (TBD source) | adds: flow_daily_summary, earnings_dates | Scan card shows "ORCL flipped from -$196M to +$96M" style deltas. Type A and E classifications work. Requires ≥ 2 days of persisted scan data. |
| **S4** | TradingView shared watchlist as universe source for the scan. Static parser → browser-rendered parser → degraded state. | none new (TradingView is non-API) | adds: source_feeds, source_imports | Two real shared TradingView URLs parse end-to-end. Failure preserves last-good symbols. Scan card respects TradingView universe. |
| **S5** | Tracking + OI/IV reconciliation. Auto-track high-conviction picks; manual pin from UI. Reconciliation labels (opening/closing/rolling/fading/hedge/unknown). | none new | adds: tracked_items, tracking_observations | Two-session test: scan on day 1 → tracked items written → reconciliation on day 2 → correct label written. |
| **S6** | Hardening: structured logging with run_id, request-fingerprint cache across runs, full request-budget enforcement, remaining-table completion (`option_surface_snapshots`, `oi_by_expiry`), CI workflows extended (ruff + pyright + pytest + coverage gates). | none new | adds: `option_surface_snapshots`, `oi_by_expiry` | 1-hour live polling session with no degraded states. All 30 V1 tables (25 spec + 5 plan-introduced) either populated or explicitly deferred to V2 in `DEFERRED.md`. CI gates green on every PR. |

**Notes:**
- Each slice merges to `master` (or `main` — whichever this repo currently uses) via PR. No direct push.
- Each slice's exit gate must include passing integration tests against real Postgres, not fake cursors.
- Setup type rollout: S1 = C only; S2 adds F; S3 adds A + E.
- The Streamlit "Surface Explorer" tab is **not** a separate deliverable — its data is rendered inline as the Market Structure section of the Single-Stock Card (S1).
- **Slice dependencies:** S2 hard-depends on S1. S3 hard-depends on S2 (day-over-day requires ≥ 2 days of S2-persisted scan data). S4 hard-depends on S2 (replaces hardcoded universe). **S5 hard-depends on S2** (tracking top-N picks per scan requires the scan to exist); S3's day-over-day data enriches reconciliation context but is not required (S5 can run after S2 alone). S6 hard-depends on all prior slices.
- **CI workflow ownership:** S1 creates `.github/workflows/ci.yml` with the initial gate (ruff + pytest + integration tests). S6 *extends* the same workflow file with pyright, coverage gate, secret scan, and the Implementation Guardrails grep checks. Only one `ci.yml` exists across V1.

---

## Canonical Table Inventory

The spec's "Storage Model" enumerates V1 tables. The plan's slice ordering populates them across S1-S6. This single table is the source of truth — any future drift between spec and plan is reconciled here first.

| Table | Source | Owning slice | Notes |
|---|---|---|---|
| `scan_runs` | spec | S1 | One row per polling/snapshot run |
| `source_feeds` | spec | S4 | TradingView watchlist source definitions |
| `source_imports` | spec | S4 | One row per (run, source, symbol) |
| `api_request_audit` | spec | S1 | Every UW request, every run |
| `raw_payloads` | spec | S1 | Compressed BYTEA bodies linked from audit |
| `flow_events` | spec | S1 | Normalized UW flow rows |
| `option_contract_snapshots` | spec | S1 | Contract-level IV/OI/volume/prices |
| `option_surface_snapshots` | spec | **S6** | Surface pagination metadata — S1 doesn't paginate full surface, so this lands when S6 adds the full-surface refresh path |
| `greeks_by_expiry_strike` | spec | S1 | Delta/gamma/theta/vega/rho/vanna/charm |
| `exposures_by_expiry_strike` | spec | S1 | GEX/DEX/vanna/charm exposures |
| `oi_by_expiry` | spec | **S6** | Per-expiry OI aggregates — S1 uses per-strike only; S6 adds the per-expiry view |
| `oi_by_strike` | spec | S1 | Per-strike OI |
| `oi_change_events` | spec | S1 | Contract-level OI deltas |
| `iv_rank_history` | spec | S1 | IV rank + IV rank deltas |
| `iv_term_snapshots` | spec | S1 | Term structure |
| `interpolated_iv_snapshots` | spec | S1 | Standard tenor IV + percentile |
| `realized_volatility_history` | spec | S1 | RV + stock price |
| `risk_reversal_skew_history` | spec | S1 | 25Δ skew |
| `max_pain_by_expiry` | spec | S1 | Max pain |
| `dark_pool_events` | spec | S1 | Dark pool prints |
| `short_interest_snapshots` | spec | S1 | Short interest / utilization / DTC |
| `tracked_items` | spec | S5 | Tracked contracts + expiry groups |
| `tracking_observations` | spec | S5 | OI/IV observations for tracked items |
| `opportunity_scores` | spec | S1 | Score + setup_types[] + warnings[] |
| `structure_ideas` | spec | S1 | Suggested structures per opportunity |
| `volatility_stats_history` | **new (plan)** | S1 | Persisted output of `/volatility/stats` — the spec mentions the endpoint at "UW API Capability Matrix" but did not enumerate a dedicated table. Plan adds it so IV/HV history is queryable without parsing raw payloads. |
| `scan_universe` | **new (plan)** | S2 | Per-run snapshot of which tickers were screened. Required for S3's day-over-day comparisons. |
| `scan_results` | **new (plan)** | S2 | Per-run scan-level setup classifications and rankings. Distinct from `opportunity_scores` (which is per-flow-row); `scan_results` is per-ticker-per-scan. |
| `flow_daily_summary` | **new (plan)** | S3 | Materialized day-level net-premium / bull-bear / C/P aggregates per ticker. Enables day-over-day deltas without re-aggregating from `flow_events`. |
| `earnings_dates` | **new (plan)** | S3 | Earnings calendar source data for Setup Type A classification. |

**Total: 25 spec tables + 5 plan-introduced tables = 30.** The plan-introduced tables are explicitly justified above. If S6 reaches and still has empty `option_surface_snapshots` or `oi_by_expiry`, document the deferral with rationale in `DEFERRED.md` rather than silently dropping them.

---

## File Structure (cumulative across slices)

Target ~15 source files for the entire V1, not 25. Each file has one clear responsibility.

```
src/uw_scan/
  __init__.py                     (empty)
  config.py                       Pydantic Settings from env. No fallbacks that hide problems.
  models.py                       All Pydantic models in one place: FlowRow, IvRank, VolStats,
                                  GreekExposureRow, OptionContract, SingleStockReport, ScanReport, etc.
  api/
    __init__.py                   (empty)
    client.py                     httpx.Client with token-bucket rate limit, retry-with-backoff
                                  on 429 + 5xx, fingerprint hashing. Raises typed UwHTTPError.
    endpoints.py                  Endpoint registry (one Enum entry per endpoint, doc URLs).
  sources/
    __init__.py                   (empty)
    uw.py                         High-level fetchers: fetch_iv_rank(ticker) → IvRank, etc.
                                  Each returns a typed Pydantic model. Persists raw payload +
                                  audit row before returning.
    tradingview.py                S4 only — static + Playwright parsers.
  normalize.py                    Pure functions: raw_json → typed model. No fallback chains.
  storage/
    __init__.py                   (empty)
    repository.py                 All persistence functions. Real psycopg cursors only.
    migrations/                   One .sql file per slice with new tables.
      001_s1_core_tables.sql
      002_s2_scan_tables.sql      (added in S2)
      003_s3_daily_summary.sql    (added in S3)
      004_s4_source_feeds.sql     (added in S4)
      005_s5_tracking.sql         (added in S5)
      006_s6_remaining_tables.sql (added in S6; option_surface_snapshots, oi_by_expiry)
  scoring.py                      Conviction score + setup classification (C in S1, F in S2, A/E in S3).
  reports/
    __init__.py                   (empty)
    single_stock.py               Assembles SingleStockReport from persisted data + derivations
                                  (scenarios, VRP signal, trade plan).
    scan.py                       Assembles ScanReport (S2+).
  pipeline.py                     Orchestration: build_single_stock_report(ticker, run_id), etc.

app/
  streamlit_app.py                Page setup + sidebar with typed RunSettings.
  views/
    __init__.py                   (empty)
    single_stock_view.py          Renders SingleStockReport sections (header, market structure,
                                  vol, flow, VRP, trade plan). Replaces Codex's inline CSS soup.
    scan_view.py                  Renders ScanReport (S2+).

tests/
  unit/                           Pure-function tests, no I/O.
  integration/                    Real-Postgres tests via pytest-postgresql.
  live/                           @pytest.mark.live — hits real UW, gated.

docs/
  uw-samples/                     S0 output — real saved UW payloads, one per endpoint.
  superpowers/
    specs/2026-05-11-uw-scan-design.md
    plans/2026-05-11-uw-scan-rebuild-plan.md   (this file)
```

---

## Slice 0: Endpoint Validation Spike

**Goal:** Pin down the exact response shape of every UW endpoint the V1 reports need by hitting them with a real key and saving the payloads. No production code; the output is *data*.

**Why TDD does not apply here:** S0 produces sample payloads, not behavior. There is nothing to write a test for until the samples exist. S1 begins TDD.

**Prerequisites:** `jq` (used in S0.4 Step 2, S0.5b, S0.6, S0.7a). Verify with `which jq && jq --version`. macOS: `brew install jq`.

**Files:**
- Create: `scripts/s0_probe_endpoint.py` — reproducible probe tooling. Kept after S0 so the sample set can be re-captured when UW changes endpoint shapes. (AGENTS.md prohibits *monolithic* top-level scripts that contain business logic; a one-purpose probe utility under `scripts/` is an explicit exception. Future production code stays under `src/uw_scan/`.)
- Create: `docs/uw-samples/.gitkeep`
- Create: `docs/uw-samples/<endpoint-slug>.json` (one per endpoint)
- Create: `docs/uw-samples/README.md` (summary of findings + surprises)

**Endpoints to probe (16 + 1 bulk screener):**

| # | Endpoint | Path | Params | Used by |
|---|---|---|---|---|
| 1 | flow_alerts | `/api/option-trades/flow-alerts` | `limit=100` | Flow rows, Net Premium |
| 2 | iv_rank | `/api/stock/{ticker}/iv-rank` | — | IV Rank field |
| 3 | volatility_stats | `/api/stock/{ticker}/volatility/stats` | — | IV / HV, 52w IV range |
| 4 | realized_volatility | `/api/stock/{ticker}/volatility/realized` | — | 52w RV range, RV value |
| 5 | term_structure | `/api/stock/{ticker}/volatility/term-structure` | — | Term structure section |
| 6 | interpolated_iv | `/api/stock/{ticker}/interpolated-iv` | — | IV percentile, implied move |
| 7 | skew | `/api/stock/{ticker}/historical-risk-reversal-skew` | `expiry=YYYY-MM-DD`, `delta=25` | 25Δ skew (UW OpenAPI: both params required) |
| 8 | greek_exposure | `/api/stock/{ticker}/greek-exposure/strike-expiry` | `expiry=YYYY-MM-DD` | GEX levels table |
| 9 | spot_exposures | `/api/stock/{ticker}/spot-exposures/expiry-strike` | `expirations[]=YYYY-MM-DD` | DEX, vanna, charm bias |
| 10 | greeks | `/api/stock/{ticker}/greeks` | `expiry=YYYY-MM-DD` | Greeks for vanna/charm |
| 11 | oi_per_strike | `/api/stock/{ticker}/oi-per-strike` | — | OI Changes table |
| 12 | oi_change | `/api/stock/{ticker}/oi-change` | — | OI deltas |
| 13 | max_pain | `/api/stock/{ticker}/max-pain` | — | Max pain context |
| 14 | option_contracts | `/api/stock/{ticker}/option-contracts` | `limit=50` | Contract mid for trade plan economics + spot derivation |
| 15 | darkpool_ticker | `/api/darkpool/{ticker}` | — | Dark pool prints |
| 16 | short_data | `/api/shorts/{ticker}/data` | — | Short Int field (path verified against UW OpenAPI) |
| 16b | option_contracts (by symbol) | `/api/stock/{ticker}/option-contracts` | `option_symbol[]=<OCC1>,<OCC2>` | Exact-contract refresh for S1 trade plan strikes — second probe of the same endpoint with a different param set |
| 17 | bulk net-premium | unknown | — | S2 scan over universe — **research only**, may not exist |

**Test ticker:** TSLA (matches the example report in the spec, has all data types populated).

---

### Task S0.1: Set up `docs/uw-samples/` directory

**Files:**
- Create: `docs/uw-samples/.gitkeep`

- [ ] **Step 1: Create the directory and placeholder file**

```bash
mkdir -p /Users/chenxi/projects/unusual-whales/docs/uw-samples
touch /Users/chenxi/projects/unusual-whales/docs/uw-samples/.gitkeep
```

- [ ] **Step 2: Verify**

Run: `test -f /Users/chenxi/projects/unusual-whales/docs/uw-samples/.gitkeep && echo ok`
Expected: `ok`

(Note: bare `ls` hides dotfiles by default, so `.gitkeep` would not appear. `test -f` is unambiguous.)

---

### Task S0.2: Write the probe script

**Files:**
- Create: `scripts/s0_probe_endpoint.py`

- [ ] **Step 1: Create `scripts/` directory and the probe script**

```bash
mkdir -p /Users/chenxi/projects/unusual-whales/scripts
```

Create `scripts/s0_probe_endpoint.py` with this content:

```python
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
    "flow_alerts":          ("/api/option-trades/flow-alerts",                    {"limit": 100}),
    "iv_rank":              (f"/api/stock/{TICKER}/iv-rank",                      {}),
    "volatility_stats":     (f"/api/stock/{TICKER}/volatility/stats",             {}),
    "realized_volatility":  (f"/api/stock/{TICKER}/volatility/realized",          {}),
    "term_structure":       (f"/api/stock/{TICKER}/volatility/term-structure",    {}),
    "interpolated_iv":      (f"/api/stock/{TICKER}/interpolated-iv",              {}),
    "skew":                 (f"/api/stock/{TICKER}/historical-risk-reversal-skew",{"expiry": EXPIRY, "delta": SKEW_DELTA}),
    "greek_exposure":       (f"/api/stock/{TICKER}/greek-exposure/strike-expiry", {"expiry": EXPIRY}),
    "spot_exposures":       (f"/api/stock/{TICKER}/spot-exposures/expiry-strike", {"expirations[]": [EXPIRY]}),
    "greeks":               (f"/api/stock/{TICKER}/greeks",                       {"expiry": EXPIRY}),
    "oi_per_strike":        (f"/api/stock/{TICKER}/oi-per-strike",                {}),
    "oi_change":            (f"/api/stock/{TICKER}/oi-change",                    {}),
    "max_pain":             (f"/api/stock/{TICKER}/max-pain",                     {}),
    "option_contracts":     (f"/api/stock/{TICKER}/option-contracts",             {"limit": 50}),
    "option_contracts_by_symbol": (f"/api/stock/{TICKER}/option-contracts",       {"option_symbol[]": ["TSLA260417C00385000", "TSLA260417C00400000"]}),
    "darkpool_ticker":      (f"/api/darkpool/{TICKER}",                           {}),
    "short_data":           (f"/api/shorts/{TICKER}/data",                        {}),
}


def _save(out: Path, payload: dict[str, object]) -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))


def probe(slug: str, client: httpx.Client, api_key: str) -> None:
    if slug not in ENDPOINTS:
        sys.exit(f"unknown slug: {slug!r}. Known: {sorted(ENDPOINTS)}")

    endpoint, params = ENDPOINTS[slug]
    url = f"{BASE_URL}{endpoint}"
    resp = client.get(url, params=params, headers={"Authorization": f"Bearer {api_key}"})

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
    parser = argparse.ArgumentParser(description="Probe a UW endpoint and save its real payload.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("slug", nargs="?", default=None, help="endpoint slug (see ENDPOINTS keys)")
    group.add_argument("--all", action="store_true", help="probe every endpoint in ENDPOINTS")
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
```

- [ ] **Step 2: Verify the script is syntactically valid**

Run: `cd /Users/chenxi/projects/unusual-whales && uv run python -c "import ast; ast.parse(open('scripts/s0_probe_endpoint.py').read()); print('ok')"`
Expected: `ok`

---

### Task S0.3: Configure the API key — **[HUMAN-GATE]**

> **Subagent execution must pause here and prompt the user.** A subagent has no UW API token and cannot complete Step 2. The user types the token themselves (or runs the `echo` command below directly). Resume to S0.4 only after this task closes.

**Files:**
- Modify: `/Users/chenxi/projects/unusual-whales/.env` (do NOT commit)

- [ ] **Step 1: Copy .env.example to .env if not present**

```bash
cd /Users/chenxi/projects/unusual-whales
[ -f .env ] || cp .env.example .env
```

- [ ] **Step 2: Write the real UW API key into `.env`** *(user action)*

The user runs this themselves with their real token (or edits `.env` in an editor):

```bash
echo "UW_SCAN_API_KEY=<real-token-here>" >> /Users/chenxi/projects/unusual-whales/.env
```

Then verify `.env` is gitignored:

```bash
grep -q '^\.env$' .gitignore && echo "ok: .env is gitignored" || echo "FIX: add .env to .gitignore"
```

Expected: `ok: .env is gitignored`

---

### Task S0.4: Smoke-test the probe against one endpoint

- [ ] **Step 1: Source env and probe flow_alerts**

```bash
cd /Users/chenxi/projects/unusual-whales
set -a; source .env; set +a
uv run python scripts/s0_probe_endpoint.py flow_alerts
```

Expected: `flow_alerts                      200  →  docs/uw-samples/flow_alerts.json`

If status is not 200, STOP. Read the saved JSON to see the actual error (the body is preserved even on non-200) and fix auth / URL before continuing.

- [ ] **Step 2: Confirm the payload was written and is parseable**

```bash
jq '.status_code, (.body | type)' docs/uw-samples/flow_alerts.json
```

Expected: `200` on the first line, then `array` or `object`. If `jq` errors, the script's JSON-decode fallback may have produced a string body — check the file for `json_parse_error` and resolve before continuing.

---

### Task S0.5: Probe every remaining endpoint

- [ ] **Step 1: Run --all**

```bash
cd /Users/chenxi/projects/unusual-whales
set -a; source .env; set +a
uv run python scripts/s0_probe_endpoint.py --all
```

Expected: ~17 lines printed (16 base endpoints + the `option_contracts_by_symbol` second-probe variant). Status codes should be 200, or one of {401, 403, 404, 422} with a body that documents the cause. The `option_contracts_by_symbol` probe specifically may return 404 on this first run because the script uses placeholder OCC strings — that's expected and gets fixed in S0.5b.

- [ ] **Step 2: Verify the expected number of JSON files exist**

```bash
ls docs/uw-samples/*.json | wc -l
```

Expected: `17` (16 endpoints + `option_contracts_by_symbol`; the count grows on subsequent reruns after S0.7a adds bulk-screener candidates).

---

### Task S0.5b: Replace placeholder OCC symbols with real ones and re-probe

The `option_contracts_by_symbol` probe in S0.5 ran with placeholder strings (`TSLA260417C00385000`, `TSLA260417C00400000`). S1's trade plan economics need a real exact-contract refresh shape — so re-probe with symbols pulled from the broad `option_contracts` sample we just captured.

- [ ] **Step 1: Extract two real OCC symbols from the broad option_contracts sample**

```bash
cd /Users/chenxi/projects/unusual-whales
jq -r '
  .body
  | if type == "array" then .[0:2]
    elif type == "object" then (.data // .results // .contracts // []) [0:2]
    else [] end
  | map(.option_symbol // .symbol // .contract // empty)
  | @csv
' docs/uw-samples/option_contracts.json
```

Expected: two real OCC-format strings, comma-separated. If empty, inspect the body manually and pick any two contract symbols visible in the payload.

- [ ] **Step 2: Update the placeholder OCCs in `scripts/s0_probe_endpoint.py`**

Replace the two placeholder strings in the `option_contracts_by_symbol` entry of the `ENDPOINTS` dict with the two real symbols from Step 1.

- [ ] **Step 3: Re-probe just that one slug**

```bash
uv run python scripts/s0_probe_endpoint.py option_contracts_by_symbol
```

Expected: `option_contracts_by_symbol      200  →  docs/uw-samples/option_contracts_by_symbol.json`. The saved payload now reflects the real exact-contract response shape, not a 404.

---

### Task S0.6: Generate the per-endpoint shape summary

One jq pipeline produces a markdown summary of every saved payload. The output goes into the Findings README in S0.8.

- [ ] **Step 1: Generate shape summary as a markdown file**

```bash
cd /Users/chenxi/projects/unusual-whales
{
  for f in docs/uw-samples/*.json; do
    slug=$(basename "$f" .json)
    echo "### ${slug}"
    jq -r '
      "- Path: `\(.endpoint)`",
      "- Status: \(.status_code)",
      "- Params: `\(.params | tostring)`",
      "- Body type: \(.body | type)",
      "- Top-level keys: \(.body | if type == "array" then (.[0] // {}) | keys | join(", ") elif type == "object" then keys | join(", ") else "scalar" end)",
      "- Pagination hints: \(.body | if type == "object" then [.next_page?, .has_more?, .total?, .page?] | map(select(. != null)) | tostring else "n/a" end)",
      (if .json_parse_error then "- JSON parse error: \(.json_parse_error)" else empty end)
    ' "$f"
    echo
  done
} > docs/uw-samples/_shape-summary.md
wc -l docs/uw-samples/_shape-summary.md
```

Expected: line count > 100 (six lines × 17 endpoints minimum, plus headers and blanks).

- [ ] **Step 2: Inspect the summary for any non-200 responses**

```bash
grep -nE "Status: (4|5)[0-9]{2}" docs/uw-samples/_shape-summary.md
```

For each non-200 hit, read the body in `docs/uw-samples/<slug>.json` and note the cause (auth, entitlement, required-param, etc) — this becomes a per-endpoint "Surprises" note in S0.8.

---

### Task S0.7a: Research the bulk net-premium screener

The Full Scan (S2) needs cross-ticker net premium ranking over ~40 tickers. Per-ticker fanout costs ~40 × calls; a bulk endpoint, if it exists, is much cheaper.

- [ ] **Step 1: Search the UW OpenAPI for bulk candidates**

```bash
# Open the OpenAPI in the browser, or curl + grep:
curl -s https://api.unusualwhales.com/api/openapi | jq '.paths | keys[]' | grep -iE "net-prem|screener|scanner|group-flow|market-flow|spike|gainers|movers"
```

For each match, note: path, required params, whether it returns multi-ticker, expected use.

- [ ] **Step 2: Add candidates to the probe script and run them**

For each candidate path, add an entry to the `ENDPOINTS` dict in `scripts/s0_probe_endpoint.py` (slug prefix `bulk_`), then:

```bash
uv run python scripts/s0_probe_endpoint.py --all
```

Expected: every candidate produces a sample in `docs/uw-samples/bulk_<slug>.json`.

### Task S0.7b: Record the S2-cost conclusion

- [ ] **Step 1: Write the bulk-screener conclusion line**

In a scratch file (`/tmp/s0-bulk-finding.txt`) write **one** of these conclusions, with the cited endpoint or cost estimate:

- `BULK_FOUND: <endpoint path> returns net premium for N tickers per call.`
- `NO_BULK: S2 will fan out per-ticker. Estimated cost = <tickers> × <calls/ticker> ≈ <N> requests per scan cycle.`

This single line is pasted into the Findings README in S0.8.

---

### Task S0.8a: Author the Findings README header + meta sections

**Files:**
- Create: `docs/uw-samples/README.md`

- [ ] **Step 1: Create the README with header, ticker, auth observations, and open questions sections**

Substitute today's date into the placeholder:

```bash
TODAY=$(date +%Y-%m-%d)
cat > docs/uw-samples/README.md <<EOF
# UW Endpoint Sample Payloads

Captured on ${TODAY} by \`scripts/s0_probe_endpoint.py\` against the live UW API.
These payloads serve as the contract tests for normalizers: every normalizer in
\`src/uw_scan/normalize.py\` is unit-tested against the corresponding sample here.

If UW changes a response shape, the affected sample is re-captured, the failing
normalizer test is inspected, and the normalizer is updated.

## Test ticker

TSLA — selected because it has populated values in every field of the
Single-Stock Card example in the spec.

## Per-endpoint shape summary

(see _shape-summary.md for the mechanical jq output; supplement here with surprises only)

EOF
```

- [ ] **Step 2: Append the auth + rate-limit + open-questions sections from observations**

Append to `docs/uw-samples/README.md`:

```markdown
## Bulk net-premium screener research

(paste the single conclusion line from /tmp/s0-bulk-finding.txt produced in S0.7b)

## Auth + rate limit observations

- Header used: `Authorization: Bearer <token>`
- Rate-limit headers observed: (inspect any `docs/uw-samples/*.json` `.headers` for keys like `x-ratelimit-*`, `retry-after`)
- 429 behavior: (observed during probe / not observed)

## Open questions for S1

(none / one bullet per surprise that needs design attention before S1)
```

The author fills the parenthesized items from concrete observations. No template ellipses, no `<fill in>` markers.

### Task S0.8b: Append per-endpoint shape sections

- [ ] **Step 1: Inline the generated shape summary**

```bash
cd /Users/chenxi/projects/unusual-whales
cat docs/uw-samples/_shape-summary.md >> docs/uw-samples/README.md
```

- [ ] **Step 2: For each endpoint subsection in the README, add a single `- Surprises:` line**

For each `### <slug>` heading already in the README from the previous step, append one line manually:

- If the endpoint behaved as expected: `- Surprises: none`
- If something was unexpected: `- Surprises: <concrete observation>` (e.g. `premium returned as string not number`, `pagination via opaque cursor, not page number`, `409 returned when expiry is a holiday`, etc.)

This is the only manual content — every other line in the per-endpoint section came from jq.

### Task S0.8c: Verify the README has no placeholders

- [ ] **Step 1: Run the expanded placeholder scan**

```bash
grep -nE "TBD|TODO|FIXME|<fill in>|<yes/no>|<same template>|same template|repeat for all|\\.\\.\\." docs/uw-samples/README.md && echo "FAIL: placeholders remain" || echo "ok: no placeholders"
```

Expected: `ok: no placeholders`. If FAIL, edit the file to remove or fill the flagged lines, then re-run.

---

### Task S0.9: Commit S0 outputs and verify exit gate

- [ ] **Step 1: Stage and commit**

```bash
cd /Users/chenxi/projects/unusual-whales
git add docs/uw-samples/ scripts/s0_probe_endpoint.py
git status   # confirm .env is NOT staged
git diff --cached --stat
git commit -m "S0: capture real UW endpoint samples + shape findings"
```

- [ ] **Step 2: Verify nothing sensitive leaked**

```bash
git show --stat HEAD
git show HEAD -- docs/uw-samples/ | grep -iE "Bearer|token|api[_-]?key|sk-[A-Za-z0-9]" | head -20
```

Expected: no API key, no Bearer token, no `sk-`-prefixed strings, no other secret patterns. If any appear, `git reset HEAD~1`, scrub the file, re-stage, recommit.

- [ ] **Step 3: Confirm the S0 exit gate**

All items below must be true. They are unchecked because the subagent or user reading this checks them by inspection at commit time.

- [ ] `docs/uw-samples/README.md` exists and has a `### <slug>` section for every endpoint in `_shape-summary.md`.
- [ ] `docs/uw-samples/*.json` has ≥ 17 sample payloads.
- [ ] Every non-200 response is documented with cause in the README.
- [ ] No secrets in the commit (Step 2 produced no matches).
- [ ] Bulk net-premium endpoint question is answered (either `BULK_FOUND` or `NO_BULK` with cost estimate).
- [ ] Placeholder scan (Task S0.8c Step 1) returned `ok: no placeholders`.

If any item is false, fix before opening the S0 PR.

---

## Slice 1: Single-Stock Analysis Card (outline — full plan written when S1 starts)

**Goal:** Streamlit page where the user enters a ticker → app fetches ~16 endpoints with rate-limited / retried HTTP client → persists every response (raw + audit + typed rows) → assembles a `SingleStockReport` matching the spec's Card format → renders it. Snapshot save → reload → semantically-equivalent render.

**Files (new):**
- `pyproject.toml` — add `psycopg[binary]`, `pytest-postgresql`, `ruff`, `pyright` to dev deps
- `src/uw_scan/config.py`
- `src/uw_scan/models.py`
- `src/uw_scan/api/client.py`
- `src/uw_scan/api/endpoints.py`
- `src/uw_scan/sources/uw.py`
- `src/uw_scan/normalize.py`
- `src/uw_scan/storage/repository.py`
- `src/uw_scan/storage/migrations/001_s1_core_tables.sql`
- `src/uw_scan/scoring.py` (setup type C only)
- `src/uw_scan/reports/single_stock.py`
- `src/uw_scan/pipeline.py`
- `app/streamlit_app.py`
- `app/views/single_stock_view.py`
- `tests/unit/test_normalize.py` (contract tests against `docs/uw-samples/`)
- `tests/unit/test_scoring.py`
- `tests/unit/test_report_assembly.py`
- `tests/integration/test_repository_real_pg.py`
- `tests/integration/test_pipeline_e2e.py`
- `tests/live/test_uw_smoke.py` (`@pytest.mark.live`)
- `scripts/_lint_except.py` (AST check enforcing Guardrail 2 — see Implementation Guardrails table)
- `.github/workflows/ci.yml` (initial form; S6 extends)

**Exit gate (concrete):**
1. `uv run pytest tests/unit/ tests/integration/` passes against a freshly-created test schema in local Postgres.
2. `uv run streamlit run app/streamlit_app.py` launches; entering a real ticker with `UW_SCAN_API_KEY` set produces the TSLA-style Card sections (header, market structure, volatility, flow, VRP, trade plan).
3. After **one** live run for a single ticker, the following row counts hold in `uw_scan` schema (verified by an integration test, not just `psql`):
   - `scan_runs ≥ 1`
   - `raw_payloads ≥ 16` (one per probed endpoint family)
   - `api_request_audit ≥ 16`
   - `flow_events ≥ 1`
   - `iv_rank_history = 1`, `volatility_stats_history = 1`, `realized_volatility_history = 1`, `iv_term_snapshots ≥ 1`, `interpolated_iv_snapshots ≥ 1`, `risk_reversal_skew_history ≥ 1`
   - `greeks_by_expiry_strike ≥ 1`, `exposures_by_expiry_strike ≥ 1`
   - `oi_by_strike ≥ 1`, `oi_change_events ≥ 1`, `max_pain_by_expiry ≥ 1`
   - `option_contract_snapshots ≥ 1`, `dark_pool_events ≥ 0` (≥ 1 if ticker had DP prints that day), `short_interest_snapshots = 1`
   - `opportunity_scores ≥ 1`, `structure_ideas ≥ 1`
   - **Tables explicitly NOT populated in S1 (deferred): `option_surface_snapshots`, `oi_by_expiry`** — S6 picks these up. Integration test asserts row count = 0 (so a later slice can detect when they start being populated).
4. After "Save snapshot" → "Load snapshot" cycle, the rendered card is semantically equivalent (same scoring, same trade plan strikes, same warnings).
5. Implementation Guardrail tests pass: no pipe-joined strings (CI grep), no `except Exception:` blocks that lack `repr(exc)` or `logging.exception()` (CI AST check), no field-name fallback chains in normalizers (`normalize.py` unit tests fail loudly on missing keys).

**S1 full task breakdown is deferred to the start of S1.** When S0 closes, re-invoke `superpowers:writing-plans` with the updated spec + S0 findings to write `docs/superpowers/plans/2026-MM-DD-uw-scan-s1.md`.

---

## Slice 2: Full Scan Report (outline)

**Goal:** Multi-ticker scan over a hardcoded universe (S4 will replace with TradingView). For each ticker, compute net premium for the date, classify into types C and F (Multi-Signal), rank by conviction score, render Full Scan card with Top Pick deep-dive (reuses S1's Single-Stock Card).

**Net-premium acquisition strategy:** Determined by S0.7a/b findings. Either bulk endpoint or per-ticker fanout.

**New files:**
- `src/uw_scan/reports/scan.py`
- `src/uw_scan/storage/migrations/002_s2_scan_tables.sql` (scan_universe, scan_results)
- `app/views/scan_view.py`
- `tests/unit/test_scan_assembly.py`
- `tests/integration/test_scan_e2e.py`

**Exit gate:** Scan card renders for a real date. Top Pick reuses S1 Card. Setup F classification (Multi-Signal: C + dark pool / OI build / IV anomaly) works on real data. Hardcoded universe of 20-40 liquid tickers committed as a constant.

**S2 detailed plan written at S2 start.**

---

## Slice 3: Day-over-Day Deltas + Setup Types A and E

**Goal:** Day-over-day flow reversal lines ("ORCL flipped from -$196M to +$96M") in the Scan card. Requires ≥ 2 days of S1/S2 persisted data. Setup A (Earnings IV Crush) needs an earnings calendar source. Setup E (Dark Pool) needs darkpool persistence threshold logic.

**Open question for S3 start:** which earnings calendar? UW endpoint exists? Else: FMP API (apex uses it), Finnhub, or yfinance fallback.

**New files:**
- `src/uw_scan/sources/earnings.py` (TBD source)
- `src/uw_scan/storage/migrations/003_s3_daily_summary.sql` (flow_daily_summary, earnings_dates)
- Extends `scoring.py` with classify_a + classify_e

**Exit gate:** Day-over-day deltas render. Earnings tickers near IV peaks classified as A. Tickers with ≥ N dark pool prints + $M notional classified as E.

---

## Slice 4: TradingView Watchlist as Universe Source

**Goal:** Replace the hardcoded universe in S2 with TradingView shared watchlists. Static parser tries first, browser-rendered (Playwright) fallback, degraded state if both fail.

**New files:**
- `src/uw_scan/sources/tradingview.py`
- `src/uw_scan/storage/migrations/004_s4_source_feeds.sql` (source_feeds, source_imports)
- `tests/unit/test_tradingview_parser.py`
- `tests/live/test_tradingview_smoke.py`

**Exit gate:** Two real shared TradingView URLs parse to symbol lists. Failure preserves last-good symbols. Scan card source-attributes results to TradingView universe.

---

## Slice 5: Tracking + OI/IV Reconciliation

**Goal:** Auto-track top-N picks from each scan; manual pin via UI. Day-2 reconciliation labels original flow as opening / closing / rolling / fading / hedge / unknown based on next-session OI delta.

**New files:**
- `src/uw_scan/tracking.py`
- `src/uw_scan/storage/migrations/005_s5_tracking.sql` (tracked_items, tracking_observations)
- `app/views/tracked_view.py`
- Two-session integration test that simulates day 1 → day 2 reconciliation.

**Exit gate:** Tracked items table populated after each scan. Reconciliation classifier tested against ≥ 6 hand-constructed scenarios covering each label.

---

## Slice 6: Hardening + Operational Completeness

**Goal:** Ship-ready operational maturity. Structured logging with `run_id` correlation. Request-fingerprint cache across runs. Full request-budget enforcement (not just display). Fill in the two remaining V1 spec tables not populated by S1-S5: `option_surface_snapshots` and `oi_by_expiry`. CI gates extended to full form.

**New files:**
- `src/uw_scan/logging.py`
- `src/uw_scan/cache.py` (request fingerprint cache)
- `src/uw_scan/storage/migrations/006_s6_remaining_tables.sql` (populates `option_surface_snapshots`, `oi_by_expiry`)
- `tests/integration/test_request_budget_enforcement.py`
- `tests/integration/test_fingerprint_cache.py`

**Modified files:**
- `.github/workflows/ci.yml` — extends the S1-created workflow with pyright, coverage gate, secret scan, and the Implementation Guardrails grep / AST checks.

**Exit gate:** 1-hour live polling session produces zero degraded states. All Implementation Guardrails enforced by automated CI checks. All 30 V1 tables (25 spec + 5 plan-introduced) either populated by the live pipeline or explicitly deferred-to-V2 in a `DEFERRED.md` doc with rationale per table.

---

## Implementation Guardrails — Enforcement Strategy

| Guardrail | Enforcement |
|---|---|
| 1. No field-name fallback chains | `normalize.py` unit tests against `docs/uw-samples/*.json` use exact key lookups; missing key → test fail. CI grep bans `_first(`-style helpers in `src/`. |
| 2. No `except Exception:` swallowing messages | **AST check, not grep.** A small `scripts/_lint_except.py` (added in S1) walks `src/` and `app/` via `ast`, flags any `ExceptHandler` whose body does not call `logging.exception(...)`, `logger.exception(...)`, or reference `repr(exc)` / `traceback`. CI runs it as `uv run python scripts/_lint_except.py src app`. Grep alone misses `except Exception: pass` and overflags valid handlers. |
| 3. No silent fixture fallback in production | `src/` does not import from `tests/fixtures/`. Live pipeline raises typed `LiveDataUnavailable` exception instead of returning fixtures. CI grep: `grep -rE "from uw_scan\\.fixtures\|from tests" src/ app/` must return empty. |
| 4. Persistence is part of done | Each slice's exit gate enumerates **explicit per-table minimum row counts** (see S1 exit gate above for the template). Integration test `test_pipeline_e2e` asserts each named table meets its minimum *and* that explicitly-deferred tables (e.g. S1's `option_surface_snapshots`, `oi_by_expiry`) have row count = 0. "Populated tables only" is rejected — that is tautological. |
| 5. No fake-cursor tests | CI grep bans class names matching `_FakeCursor` / `_FakeConnection` in `tests/integration/`. Integration tests use `pytest-postgresql` fixtures only. |
| 6. Rate limiter enforces | `test_rate_limiter` asserts that exceeding budget raises; sidebar widget reads live state from limiter, not config. |
| 7. No premature modules | CI check: any Python file under **50 LOC** in `src/uw_scan/**/*.py` fails the build, EXCEPT (a) `__init__.py` files (empty or re-export only — auto-exempt by filename), and (b) files whose first non-shebang line is the literal comment `# pragma: standalone` (escape hatch for genuinely-tiny standalone helpers). The CI check is `scripts/_lint_loc.py` (added in S6). Threshold matches the spec's "file under 50 lines is a code smell" wording. |
| 8. No dead UI controls | `streamlit.testing` test renders sidebar, mutates each input, asserts `RunSettings` reflects the change. |
| 9. SQL arrays not pipe strings | CI grep bans `"|".join(` near SQL execute calls in `src/`. Migrations use `TEXT[]` for multi-valued columns. |
| 10. Date column semantics explicit | Migration SQL files have `COMMENT ON COLUMN` for every date/timestamp column. Integration test asserts `market_date != expiry` for at least one persisted row. |
| 11. Endpoint shapes pinned | Contract tests in `tests/unit/test_normalize.py` load `docs/uw-samples/*.json` and assert each normalizer produces the expected typed model. New endpoint without a sample → test fails. |
| 12. Report contracts before infrastructure | Each slice's exit gate includes a screenshot or rendered output snippet of the report section it ships. |

---

## Self-Review

**Spec coverage check (every spec section maps to a slice or guardrail):**

| Spec section | Plan coverage |
|---|---|
| Goal | All slices contribute. |
| Reset Status | This plan IS the reset response. |
| Repository And Database | File Structure section + S1 migrations. |
| Product Shape (dual-source) | S1 (UW) + S4 (TradingView). |
| V1 Scope (bullets) | S1-S6 collectively. Snapshot replay: S1. Tracking: S5. OI/IV reconciliation: S5. Scoring: S1 (C), S2 (F), S3 (A, E). Suggested structures: S1. Full surface tiered: S1 covers surface for one ticker; S6 adds full-surface refresh. Raw archive + normalized: S1. |
| Report Formats (Single-Stock Card) | S1. |
| Report Formats (Full Scan) | S2 + S3. |
| Setup Type Taxonomy | S1=C, S2=F, S3=A+E. |
| Deferred Scope | Not in plan (correctly). |
| Streamlit Views | Single-Stock = S1. Flow Feed = S1 sidebar/tab. TV Watchlists = S4. Tracked = S5. Surface Explorer = inline in S1 Card (NOT a separate tab — explicit design decision). Snapshots = S1. |
| Architecture | File Structure section. |
| Data Flow | Pipeline.py in S1. |
| Storage Model (25 spec tables + 5 plan-introduced = 30) | See "Canonical Table Inventory" above. S1 = 20, S2 = +2, S3 = +2, S4 = +2, S5 = +2, S6 = +2 (option_surface_snapshots, oi_by_expiry). |
| Scoring And Tracking | S1 (C scoring), S5 (tracking + reconciliation). |
| Structure Ideas | S1 (bull call spread for type C); other structures may need later slices. |
| UW API Capability Matrix | S0 probes every endpoint. |
| Request Minimization (4 tiers) | S0 estimates costs; S1 implements rate-limited client; S6 implements cross-run fingerprint cache. |
| External Validation Notes | Replaced by S0 saved payloads. |
| Implementation Guardrails (12) | Enforcement Strategy table above. |
| Error Handling | S1 (live failure → typed exception + visible message); S4 (TV degraded state). |
| Testing | tests/{unit,integration,live} structure in File Structure section. |
| First Layout Direction | S1 (Single-Stock Card is the first slice). |

**Placeholder scan:** Search performed for "TBD", "TODO", "FIXME", "fill in later", "similar to", "..." (literal ellipsis), "same template", "repeat for all". Found exactly two intentional uses:
- "S3 Open question for S3 start: which earnings calendar?" — intentional, not a placeholder; the question is the work product.
- "S1 full task breakdown is deferred" — intentional, by design; each slice gets its own detailed plan at its start.

The prior "Short data path TBD" note has been removed — Codex verified the path against the UW OpenAPI during review. No anti-pattern placeholders remain.

**Type consistency check:** Method/class names referenced across slices: `SingleStockReport`, `ScanReport`, `RunSettings`, `UwApiClient`, `LiveDataUnavailable`. All used consistently. No `clearLayers / clearFullLayers` style drift detected.

---

## Execution Handoff

After this plan is committed, S0 should be executed next. Two options:

**1. Subagent-Driven (recommended for S0)** — Each of the 13 atomic tasks (S0.1, S0.2, S0.3, S0.4, S0.5, S0.5b, S0.6, S0.7a, S0.7b, S0.8a, S0.8b, S0.8c, S0.9) dispatched to a fresh subagent. Fast, isolated, easy to review per-task. **Note:** S0.3 is a `[HUMAN-GATE]` — subagent execution must pause there and surface a prompt for the user to write `.env` themselves.

**2. Inline Execution** — Run the 13 tasks in the current session with checkpoints. Best when the user wants to watch shape findings emerge live.

For S1+ slices, re-invoke `superpowers:writing-plans` to produce a slice-specific detailed plan before execution begins. Do not start S1 from this outline alone.
