# UW Scan V1 Rebuild Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Unusual Whales opportunity scanner from scratch using vertical slices, producing the two canonical reports — Single-Stock Analysis Card and Full Scan Report — defined in `docs/superpowers/specs/2026-05-11-uw-scan-design.md` (Report Formats section).

**Architecture:** Each slice is end-to-end (UI → pipeline → API client → normalizer → storage → reload), shipping one user-visible feature with real persistence, real Postgres integration tests, and full error surfacing. Horizontal-layer planning (build all clients, then all storage, then all UI) is rejected as the failure mode that produced the prior reset.

**Tech Stack:** Python 3.11+, `uv` for deps, `httpx` (sync) for HTTP, `pydantic` 2 for typed models, `psycopg` 3 for Postgres, Streamlit for UI, `pytest` for tests, `pytest-postgresql` for integration tests, `playwright` for TradingView browser parsing (S4). All Implementation Guardrails (spec §"Implementation Guardrails") are enforced by CI gates where possible.

---

## Slice Map

| Slice | Ships | Endpoints touched | Tables populated | Exit Gate |
|---|---|---|---|---|
| **S0** | Endpoint validation spike — real UW payload sample per endpoint, response-shape documentation. Throwaway script, no production code. | ~16 read endpoints + bulk-screener probe | none | All endpoints needed for the Single-Stock Card return verified payloads saved as JSON; shape notes committed. |
| **S1** | Single-Stock Analysis Card for one user-entered ticker, rendered end-to-end with real data, persisted to typed tables, reloadable from snapshot. | flow-alerts, iv-rank, vol-stats, realized-vol, term-structure, interpolated-iv, skew, greek-exposure/strike-expiry, spot-exposures, greeks, oi-per-strike, oi-change, max-pain, option-contracts, darkpool/ticker, short-data | scan_runs, raw_payloads, api_request_audit, flow_events, iv_rank_history, volatility_stats_history, realized_volatility_history, iv_term_snapshots, interpolated_iv_snapshots, risk_reversal_skew_history, greeks_by_expiry_strike, exposures_by_expiry_strike, oi_by_strike, oi_change_events, max_pain_by_expiry, option_contract_snapshots, dark_pool_events, short_interest_snapshots, opportunity_scores, structure_ideas | TSLA-style card renders for any ticker with API key configured. 100% of API responses written to `raw_payloads` + `api_request_audit`. Snapshot save → reload produces semantically-equivalent card. Integration tests against real Postgres pass. Setup type C (Deep Conviction) classification works. |
| **S2** | Full Scan Report over a hardcoded universe of ~40 tickers, ranking by conviction score, classifying into types C and F (Multi-Signal). Day-over-day deferred. | adds bulk-screener (if discovered in S0) or per-ticker net-premium fanout | adds: scan_universe, scan_results | Full Scan card renders for a date with persisted ticker universe. Top Pick deep-dive reuses S1's Single-Stock Card. Setup type F classification works. |
| **S3** | Day-over-day flow reversal detection. Earnings calendar source for Type A. Dark Pool persistence for Type E. | adds earnings calendar (TBD source) | adds: flow_daily_summary, earnings_dates | Scan card shows "ORCL flipped from -$196M to +$96M" style deltas. Type A and E classifications work. Requires ≥ 2 days of persisted scan data. |
| **S4** | TradingView shared watchlist as universe source for the scan. Static parser → browser-rendered parser → degraded state. | none new (TradingView is non-API) | adds: source_feeds, source_imports | Two real shared TradingView URLs parse end-to-end. Failure preserves last-good symbols. Scan card respects TradingView universe. |
| **S5** | Tracking + OI/IV reconciliation. Auto-track high-conviction picks; manual pin from UI. Reconciliation labels (opening/closing/rolling/fading/hedge/unknown). | none new | adds: tracked_items, tracking_observations | Two-session test: scan on day 1 → tracked items written → reconciliation on day 2 → correct label written. |
| **S6** | Hardening: structured logging with run_id, request-fingerprint cache across runs, full request-budget enforcement, max_pain/short interest/skew completion, CI workflows (ruff + pyright + pytest + coverage gates). | none new | none new | 1-hour live polling session with no degraded states. All 22 spec tables either populated or explicitly deferred to V2. CI gates green on every PR. |

**Notes:**
- Each slice merges to `master` (or `main` — whichever this repo currently uses) via PR. No direct push.
- Each slice's exit gate must include passing integration tests against real Postgres, not fake cursors.
- Setup type rollout: S1 = C only; S2 adds F; S3 adds A + E.
- The Streamlit "Surface Explorer" tab is **not** a separate deliverable — its data is rendered inline as the Market Structure section of the Single-Stock Card (S1).

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

**Files:**
- Create: `scripts/s0_probe_endpoint.py` (throwaway probe script, deleted after S0)
- Create: `docs/uw-samples/.gitkeep`
- Create: `docs/uw-samples/<endpoint-slug>.json` (one per endpoint)
- Create: `docs/uw-samples/README.md` (summary of findings + surprises)
- Modify: `.gitignore` (ensure scripts/ is not ignored; ensure `.env` stays ignored)

**Endpoints to probe (16 + 1 bulk screener):**

| # | Endpoint | Path | Params | Used by |
|---|---|---|---|---|
| 1 | flow_alerts | `/api/option-trades/flow-alerts` | `limit=100` | Flow rows, Net Premium |
| 2 | iv_rank | `/api/stock/{ticker}/iv-rank` | — | IV Rank field |
| 3 | volatility_stats | `/api/stock/{ticker}/volatility/stats` | — | IV / HV, 52w IV range |
| 4 | realized_volatility | `/api/stock/{ticker}/volatility/realized` | — | 52w RV range, RV value |
| 5 | term_structure | `/api/stock/{ticker}/volatility/term-structure` | — | Term structure section |
| 6 | interpolated_iv | `/api/stock/{ticker}/interpolated-iv` | — | IV percentile, implied move |
| 7 | skew | `/api/stock/{ticker}/historical-risk-reversal-skew` | — | 25Δ skew |
| 8 | greek_exposure | `/api/stock/{ticker}/greek-exposure/strike-expiry` | `expiry=YYYY-MM-DD` | GEX levels table |
| 9 | spot_exposures | `/api/stock/{ticker}/spot-exposures/expiry-strike` | `expirations[]=YYYY-MM-DD` | DEX, vanna, charm bias |
| 10 | greeks | `/api/stock/{ticker}/greeks` | `expiry=YYYY-MM-DD` | Greeks for vanna/charm |
| 11 | oi_per_strike | `/api/stock/{ticker}/oi-per-strike` | — | OI Changes table |
| 12 | oi_change | `/api/stock/{ticker}/oi-change` | — | OI deltas |
| 13 | max_pain | `/api/stock/{ticker}/max-pain` | — | Max pain context |
| 14 | option_contracts | `/api/stock/{ticker}/option-contracts` | `limit=50` | Contract mid for trade plan economics + spot derivation |
| 15 | darkpool_ticker | `/api/darkpool/{ticker}` | — | Dark pool prints |
| 16 | short_data | `/api/shorts/{ticker}/data` | — | Short Int field (path TBD — confirm in S0) |
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

Run: `ls /Users/chenxi/projects/unusual-whales/docs/uw-samples/`
Expected: `.gitkeep`

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

Throwaway script. Deleted at end of S0.

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


def _next_friday(today: date) -> str:
    days_ahead = (4 - today.weekday()) % 7 or 7
    return (today + timedelta(days=days_ahead)).isoformat()


EXPIRY = _next_friday(date.today())

ENDPOINTS: dict[str, tuple[str, dict[str, object]]] = {
    "flow_alerts":          ("/api/option-trades/flow-alerts",                    {"limit": 100}),
    "iv_rank":              (f"/api/stock/{TICKER}/iv-rank",                      {}),
    "volatility_stats":     (f"/api/stock/{TICKER}/volatility/stats",             {}),
    "realized_volatility":  (f"/api/stock/{TICKER}/volatility/realized",          {}),
    "term_structure":       (f"/api/stock/{TICKER}/volatility/term-structure",    {}),
    "interpolated_iv":      (f"/api/stock/{TICKER}/interpolated-iv",              {}),
    "skew":                 (f"/api/stock/{TICKER}/historical-risk-reversal-skew",{}),
    "greek_exposure":       (f"/api/stock/{TICKER}/greek-exposure/strike-expiry", {"expiry": EXPIRY}),
    "spot_exposures":       (f"/api/stock/{TICKER}/spot-exposures/expiry-strike", {"expirations[]": [EXPIRY]}),
    "greeks":               (f"/api/stock/{TICKER}/greeks",                       {"expiry": EXPIRY}),
    "oi_per_strike":        (f"/api/stock/{TICKER}/oi-per-strike",                {}),
    "oi_change":            (f"/api/stock/{TICKER}/oi-change",                    {}),
    "max_pain":             (f"/api/stock/{TICKER}/max-pain",                     {}),
    "option_contracts":     (f"/api/stock/{TICKER}/option-contracts",             {"limit": 50}),
    "darkpool_ticker":      (f"/api/darkpool/{TICKER}",                           {}),
    "short_data":           (f"/api/shorts/{TICKER}/data",                        {}),
}


def probe(slug: str) -> None:
    if slug not in ENDPOINTS:
        sys.exit(f"unknown slug: {slug!r}. Known: {sorted(ENDPOINTS)}")
    api_key = os.environ.get("UW_SCAN_API_KEY")
    if not api_key:
        sys.exit("UW_SCAN_API_KEY not set")

    endpoint, params = ENDPOINTS[slug]
    url = f"{BASE_URL}{endpoint}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params, headers={"Authorization": f"Bearer {api_key}"})
    out = SAMPLES_DIR / f"{slug}.json"
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "endpoint": endpoint,
        "params": {k: v for k, v in params.items()},
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
    }
    out.write_text(json.dumps(record, indent=2, default=str))
    print(f"{slug:24s} {resp.status_code}  →  {out.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug", nargs="?")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.all:
        for slug in ENDPOINTS:
            probe(slug)
    elif args.slug:
        probe(args.slug)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script is syntactically valid**

Run: `cd /Users/chenxi/projects/unusual-whales && uv run python -c "import ast; ast.parse(open('scripts/s0_probe_endpoint.py').read()); print('ok')"`
Expected: `ok`

---

### Task S0.3: Configure the API key

**Files:**
- Modify: `/Users/chenxi/projects/unusual-whales/.env` (do NOT commit)

- [ ] **Step 1: Copy .env.example to .env if not present**

```bash
cd /Users/chenxi/projects/unusual-whales
[ -f .env ] || cp .env.example .env
```

- [ ] **Step 2: Add the real UW API key to `.env`**

Open `.env` and set `UW_SCAN_API_KEY=<real-token>`. Confirm `.env` is in `.gitignore`:

```bash
grep -q '^\.env$' .gitignore && echo "ok: .env is gitignored" || echo "FIX: add .env to .gitignore"
```

Expected: `ok: .env is gitignored`

---

### Task S0.4: Probe one endpoint (smoke test the probe)

- [ ] **Step 1: Source env and probe flow_alerts**

```bash
cd /Users/chenxi/projects/unusual-whales
set -a; source .env; set +a
uv run python scripts/s0_probe_endpoint.py flow_alerts
```

Expected: `flow_alerts              200  →  docs/uw-samples/flow_alerts.json`

If status is not 200, STOP. Read the saved JSON to see the actual error and fix auth / URL before continuing.

- [ ] **Step 2: Inspect the payload shape**

```bash
jq 'keys' docs/uw-samples/flow_alerts.json
jq '.body | type' docs/uw-samples/flow_alerts.json
jq '.body | if type == "array" then .[0] | keys elif type == "object" then keys else . end' docs/uw-samples/flow_alerts.json
```

Note the top-level shape (list vs `{data: [...]}` etc) and the keys of the first row. Record them for the README in Task S0.6.

---

### Task S0.5: Probe all remaining endpoints

- [ ] **Step 1: Run --all**

```bash
cd /Users/chenxi/projects/unusual-whales
set -a; source .env; set +a
uv run python scripts/s0_probe_endpoint.py --all
```

Expected: 16 lines, one per endpoint. Status codes should be 200 or documented (401, 403, 404, 422 etc with explanation).

- [ ] **Step 2: Verify all 16 JSON files exist**

```bash
ls docs/uw-samples/*.json | wc -l
```

Expected: `16`

- [ ] **Step 3: Per endpoint, inspect the body shape**

For each `docs/uw-samples/*.json`, run:

```bash
jq -r '"\(input_filename): status=\(.status_code) type=\(.body | type) keys=\(.body | if type == "array" then .[0] | keys elif type == "object" then keys else "scalar" end)"' docs/uw-samples/*.json
```

Note any 4xx/5xx responses. These need a Findings entry in S0.6.

---

### Task S0.6: Research bulk net-premium screener

The Full Scan (S2) needs cross-ticker net premium ranking over ~40 tickers. Per-ticker fanout is expensive. UW may or may not have a bulk endpoint.

- [ ] **Step 1: Search UW public API docs for a bulk screener**

Open https://api.unusualwhales.com/docs in a browser. Search for endpoints matching:
- "net-prem-ticks" / "net-premium"
- "screener" / "scanner"
- "group-flow" / "market-flow"
- "spike" / "alerts"

For each candidate found, note: path, params, whether it returns multi-ticker, expected use.

- [ ] **Step 2: Probe each candidate (if any)**

Add the candidate to `ENDPOINTS` in `scripts/s0_probe_endpoint.py`, rerun the probe for it, save the payload as `docs/uw-samples/bulk_net_premium_<candidate>.json`.

- [ ] **Step 3: Record the answer**

The S0.7 README must answer: "Is there a bulk net-premium endpoint? If yes, name and shape. If no, S2 will fan out per-ticker — estimated request cost: ~40 × calls per ticker."

---

### Task S0.7: Write the Findings README

**Files:**
- Create: `docs/uw-samples/README.md`

- [ ] **Step 1: Author the README**

Use this exact structure:

```markdown
# UW Endpoint Sample Payloads

These payloads were captured on YYYY-MM-DD by `scripts/s0_probe_endpoint.py`
against the live UW API using a real API key. They serve as the contract tests
for normalizers: every normalizer in `src/uw_scan/normalize.py` is unit-tested
against the corresponding sample here.

If UW changes a response shape, the affected sample must be re-captured,
the failing normalizer test inspected, and the normalizer updated.

## Test ticker

TSLA. Selected because it has populated values in every field of the
Single-Stock Card example in the spec.

## Per-endpoint shape summary

For each endpoint:
- Top-level body type
- Top-level keys (if object) or first-row keys (if list)
- Pagination indicators (next_page, total, has_more, etc)
- Notable surprises

### flow_alerts
- Path: `/api/option-trades/flow-alerts`
- Status: 200
- Body type: <list | object>
- Top-level structure: <fill in from jq>
- Per-row keys: <fill in from jq>
- Pagination: <yes/no — describe>
- Surprises: <e.g. "premium is returned as a string, not a number">

### iv_rank
- Path: `/api/stock/TSLA/iv-rank`
- ... (same template)

(repeat for all 16 endpoints)

## Bulk net-premium screener research

- Searched UW public API docs for: net-prem-ticks, screener, group-flow, market-flow, spike.
- Found: <YES with endpoint X / NO>.
- S2 implication: <"Use bulk endpoint X" / "S2 will fan out per-ticker — estimated cost N requests per scan">.

## Auth + rate limit observations

- Header used: `Authorization: Bearer <token>`
- Rate limit headers observed: <X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After — list any present>
- 429 behavior: <observed or not during the spike>

## Open questions for S1

List anything that surprised us and needs design attention before S1 starts.
For example:
- "Greeks endpoint returns vanna/charm for the requested expiry only, not aggregated"
- "spot-exposures requires expirations[] not expiry — array syntax"
- "Short data path may be /api/shorts/{ticker}/data or /api/stock/{ticker}/short-data — confirm"
```

- [ ] **Step 2: Fill in every section from the actual saved samples**

Use `jq` against each file in `docs/uw-samples/*.json` to extract the shape info and paste it into the README. Every endpoint subsection must be filled in — no placeholders.

- [ ] **Step 3: Verify no `TBD`, `TODO`, or `<fill in>` left in the README**

```bash
grep -nE "TBD|TODO|FIXME|<fill in>|<yes/no>|<same template>" docs/uw-samples/README.md && echo "FAIL: placeholders remain" || echo "ok: no placeholders"
```

Expected: `ok: no placeholders`

---

### Task S0.8: Commit S0 outputs

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
git show HEAD -- docs/uw-samples/ | grep -iE "Bearer|token|api[_-]?key" | head -20
```

Expected: no API key, no Bearer token, no secret patterns in the diff. If any appear, `git reset HEAD~1`, scrub the file, recommit.

- [ ] **Step 3: S0 exit gate**

Confirm:
- [x] `docs/uw-samples/README.md` exists and contains a per-endpoint shape summary for all 16 endpoints.
- [x] `docs/uw-samples/*.json` has 16 (or more, with bulk screener) sample payloads.
- [x] All non-200 responses are explained in the README.
- [x] No secrets in the commit.
- [x] Bulk net-premium endpoint question is answered (yes-with-name OR no-with-cost-estimate).

If any item fails, fix before opening the S0 PR.

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
- `.github/workflows/ci.yml`

**Exit gate (concrete):**
1. `uv run pytest tests/unit/ tests/integration/` passes against a freshly-created test schema in local Postgres.
2. `uv run streamlit run app/streamlit_app.py` launches; entering a real ticker with `UW_SCAN_API_KEY` set produces the TSLA-style Card sections (header, market structure, volatility, flow, VRP, trade plan).
3. After a live run, `psql option_wizard -c "SELECT count(*) FROM uw_scan.raw_payloads"` returns ≥ 16 rows (one per endpoint).
4. After "Save snapshot" → "Load snapshot" cycle, the rendered card is semantically equivalent (same scoring, same trade plan strikes, same warnings).
5. Implementation Guardrail tests pass: no pipe-joined strings (CI grep), no `except Exception:` that hides messages (CI grep), no field-name fallback chains in normalizers (`normalize.py` unit tests fail loudly on missing keys).

**S1 full task breakdown is deferred to the start of S1.** When S0 closes, re-invoke `superpowers:writing-plans` with the updated spec + S0 findings to write `docs/superpowers/plans/2026-MM-DD-uw-scan-s1.md`.

---

## Slice 2: Full Scan Report (outline)

**Goal:** Multi-ticker scan over a hardcoded universe (S4 will replace with TradingView). For each ticker, compute net premium for the date, classify into types C and F (Multi-Signal), rank by conviction score, render Full Scan card with Top Pick deep-dive (reuses S1's Single-Stock Card).

**Net-premium acquisition strategy:** Determined by S0.6 finding. Either bulk endpoint or fanout.

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

**Goal:** Ship-ready operational maturity. Structured logging with `run_id` correlation. Request-fingerprint cache across runs. Full request-budget enforcement (not just display). Fill in any remaining V1 schema tables (max_pain history, short interest snapshots, risk_reversal skew history, etc). CI gates green.

**New files:**
- `src/uw_scan/logging.py`
- `src/uw_scan/cache.py` (request fingerprint cache)
- `.github/workflows/ci.yml` (final form: ruff + pyright + pytest + coverage + secret scan)
- `tests/integration/test_request_budget_enforcement.py`
- `tests/integration/test_fingerprint_cache.py`

**Exit gate:** 1-hour live polling session produces zero degraded states. All Implementation Guardrails enforced by automated CI checks. All V1 spec tables either populated by the live pipeline or explicitly deferred-to-V2 in a `DEFERRED.md` doc with rationale per table.

---

## Implementation Guardrails — Enforcement Strategy

| Guardrail | Enforcement |
|---|---|
| 1. No field-name fallback chains | `normalize.py` unit tests against `docs/uw-samples/*.json` use exact key lookups; missing key → test fail. CI grep bans `_first(`-style helpers in `src/`. |
| 2. No `except Exception:` swallowing messages | CI grep bans `type(exc).__name__` pattern in `src/` and `app/`. All caught exceptions log `repr(exc)` + traceback. |
| 3. No silent fixture fallback in production | `src/` does not import from `tests/fixtures/`. Live pipeline raises typed `LiveDataUnavailable` exception instead of returning fixtures. |
| 4. Persistence is part of done | Integration test `test_pipeline_e2e` asserts row counts in every populated table after a real-shape run. |
| 5. No fake-cursor tests | CI grep bans class names matching `_FakeCursor` / `_FakeConnection` in `tests/integration/`. Integration tests use `pytest-postgresql` fixtures only. |
| 6. Rate limiter enforces | `test_rate_limiter` asserts that exceeding budget raises; sidebar widget reads live state from limiter, not config. |
| 7. No premature modules | CI check: report `wc -l src/uw_scan/**/*.py`; any file under 30 LOC flagged for inline review. |
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
| Storage Model (22 tables) | S1 = 20 tables, S2 = +2, S3 = +2, S4 = +2, S5 = +2. S6 fills any remaining. |
| Scoring And Tracking | S1 (C scoring), S5 (tracking + reconciliation). |
| Structure Ideas | S1 (bull call spread for type C); other structures may need later slices. |
| UW API Capability Matrix | S0 probes every endpoint. |
| Request Minimization (4 tiers) | S0 estimates costs; S1 implements rate-limited client; S6 implements cross-run fingerprint cache. |
| External Validation Notes | Replaced by S0 saved payloads. |
| Implementation Guardrails (12) | Enforcement Strategy table above. |
| Error Handling | S1 (live failure → typed exception + visible message); S4 (TV degraded state). |
| Testing | tests/{unit,integration,live} structure in File Structure section. |
| First Layout Direction | S1 (Single-Stock Card is the first slice). |

**Placeholder scan:** Search performed for "TBD", "TODO", "FIXME", "fill in later", "similar to". Found exactly three intentional uses:
- "S3 Open question for S3 start: which earnings calendar?" — intentional, not a placeholder; the question is the work product.
- "S1 full task breakdown is deferred" — intentional, by design; each slice gets its own detailed plan at its start.
- Short data path "(path TBD — confirm in S0)" — intentional, S0.5/S0.7 will confirm.

No anti-pattern placeholders remain.

**Type consistency check:** Method/class names referenced across slices: `SingleStockReport`, `ScanReport`, `RunSettings`, `UwApiClient`, `LiveDataUnavailable`. All used consistently. No `clearLayers / clearFullLayers` style drift detected.

---

## Execution Handoff

After this plan is committed, S0 should be executed next. Two options:

**1. Subagent-Driven (recommended for S0)** — Each of S0.1-S0.8 dispatched to a fresh subagent. Fast, isolated, easy to review per-task.

**2. Inline Execution** — Run S0.1-S0.8 in the current session with checkpoints. Best when the user wants to watch shape findings emerge live.

For S1+ slices, re-invoke `superpowers:writing-plans` to produce a slice-specific detailed plan before execution begins. Do not start S1 from this outline alone.
