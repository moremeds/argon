# Scanner Page — Design Spec

**Date:** 2026-05-17
**Branch:** `worktree-scanner-page`
**Scope:** Phase 1 + 2 + 3 bundled — data foundation + scanner page UI + confluence/Type-F badges, end-to-end.
**Architectural lineage:** Port of `xenon/src/xenon/scanners/uw/*` (commit-equivalent), adapted to unusual-whales' Postgres-backed worker model and Next.js 16 RSC frontend.

---

## 1. Goal

Replace the `/scanner` route stub with a working scanner page that ranks watchlist tickers by multi-signal confluence and lets the user click through to deep evaluation via the existing Trade Insights AI surface.

The scanner answers one question: **"Of the names I'm already watching, which ones are showing one or more institutional-edge signals right now, and which ones are showing several (Type-F)?"**

It does NOT answer:
- "Which names outside my watchlist should I be watching?" (deferred — Phase 4 "discover")
- "What specific trade structure should I put on?" (deferred — that's the Trade Insights AI tab's job)
- "How sustained is this signal across days?" (deferred — the multi-day rolling-aggregate version of Strategy 1 is a future spec; xenon's actual code is single-snapshot, and that's what this spec ports)

---

## 2. Architecture overview

```
PER-TICKER SCAN PIPELINE (existing, extended)
─────────────────────────────────────────────
worker dequeues rescan job
    → fetches UW data into existing tables
    → NEW: scanner.pipeline.run_detectors(repo, run_id, ticker)
        → evaluates ALL 3 gates and records status (earnings, liquidity, regime)
        → IF regime_gate == "block": write signal_gates row and stop
        → ELSE: run 4 signal detectors + context-flag detector(s)
          (earnings/liquidity advisory states are passed through to the candidate
          but do NOT suppress detector emission — see §4)
        → writes results to uw_scan.signal_hits / signal_context_flags / signal_gates
    → finish_scan_run(run_id, status="ok")

SCANNER PAGE READ PATH (new)
─────────────────────────────────────────────
user opens /scanner
    → RSC fetches GET /api/scanner
        → for each watchlist ticker, find latest ok scan_run within
          last SCANNER_FRESHNESS_HOURS (default 6h)
        → pull associated signal_hits / context_flags / gates
        → build ScanCandidate per ticker (gates-passed only)
        → rank: (is_type_f desc, final_score desc, ticker asc)
        → return ranked candidates + gated-ticker explanation list
    → page renders tile-stack of candidates + "GATED" block

EVALUATE HANDOFF (existing, reused)
─────────────────────────────────────────────
user clicks "Evaluate →" on a row
    → navigates to /stock/[ticker]/trade-plan
    → existing Trade Insights AI tab handles the deep dive
```

**Three core design decisions:**

1. **Detectors fire inside the per-ticker scan pipeline.** Not a separate scheduled job, not on-demand at page render. The reasons: (a) data is guaranteed fresh at detector-time because it just got fetched, (b) no new scheduler entry needed, (c) `run_id` is a natural foreign key for the hit rows.

2. **New persistence module from the start.** `storage/signals_repository.py` is its own module, never appended to the 5,000-line `repository.py`. Standing rule [`feedback_repository_split_threshold.md`](../../../.claude/projects/-Users-chenxi-projects-unusual-whales/memory/feedback_repository_split_threshold.md).

3. **Existing `scoring.py` Setup C/F kept alongside the new `deep_conviction_flow` detector** for one release. The current full-scan pipeline still consumes Setup C/F badges on watchlist cards; ripping that out is a separate de-risk and doesn't belong in this spec. Retirement of Setup C/F is a follow-up spec once the new detector is proven.

---

## 3. Detectors

Four signal detectors + one context flag. Field thresholds are direct ports of xenon's; deviations are flagged.

### 3.1 `deep_conviction_flow` (Tier 1, headline edge)

**Reads:** UW `flow_alerts` per ticker. Endpoint `/api/option-trades/flow-alerts` already exists in `docs/uw-samples/flow_alerts.json` but is NOT currently in `sources/uw.py`. Adding it is part of this spec.

**Per-alert qualification:**
| Field | Threshold |
|---|---|
| `volume > open_interest` | required (new positioning, not closing) |
| `ask_side_percent` | ≥ 0.80 (aggressive buying) |
| `total_premium` | ≥ $500,000 |
| `multileg_percent` | < 0.10 (clean directional, not a spread) |
| `\|moneyness\|` | ≤ 0.12 (close to ATM) |
| `dte` | ≥ 6 |

**Detector-internal check:** must NOT have earnings within 14 days. This is intentionally redundant with the framework's `earnings_gate` (which is advisory for the framework but enforced *inside* this detector). Xenon preserves the same defensive duplication: even if `earnings_gate` is advisory, DCF itself returns `None` when earnings are within 14d so the detector can never emit a hit during the earnings window.

**Score:** `0.5 + 0.5 × min(total_premium / $2,000,000, 1.0)` aggregated over all qualifying alerts.

**Evidence stored:** `{qualifying_alerts: N, total_premium, top_strike, top_expiry}`.

### 3.2 `dark_pool_accumulation` (Tier 2, confirmation-only)

**Reads:** existing `uw_scan.dark_pool_events` table (already populated by the dark-pool ingest path).

**Cluster detection:**
- Find prints with `premium ≥ $1,000,000`
- For each such print as anchor: find all prints within `0.5%` of anchor price
- If cluster size ≥ 3, signal fires

**Score:** `min(1.0, total_cluster_premium / $10,000,000)`.

**Direction-neutral.** Evidence stores `{cluster_size, anchor_price, total_premium, direction_neutral: true}`. The signal asserts "size is being moved around this level," not "they're buying."

**Confluence-only:** excluded from `raw_score` via `RAW_RANKING_EXCLUDE = {"dark_pool_accumulation"}`. Contributes to `confluence_score` only. Reason: a dark-pool cluster alone is too easy to confuse with routine OTC routing; it needs another signal to matter.

**Freshness:** `"stale"` (UW dark pool data lags real-time).

### 3.3 `earnings_iv_crush` (Tier 1)

**Reads:** IV percentile (existing — `cards/vol_series.py` derives this) + earnings calendar.

**Earnings calendar source:** NEW data integration required. UW exposes earnings under `/api/earnings/...` (need to verify exact endpoint from `docs/uw-samples/unusual_whales_api.md`). Add fetcher to `sources/uw.py`, persistence table for earnings dates, refresh job (daily is sufficient).

**Threshold:**
- `iv_percentile ≥ 75`
- earnings within 14 days (must be present, opposite of DCF's gate)

**Score:** `min(1.0, (iv_percentile - 75) / 25 + 0.5)`.

**Evidence:** `{iv_percentile, earnings_date}`.

### 3.4 `gex_pinning` (Tier 1, mega-caps + opex only)

**Reads:** existing GEX-by-strike data + spot price.

**Eligibility:**
- Ticker must be in `MEGA_CAPS = {SPY, QQQ, IWM, DIA, AAPL, MSFT, NVDA, GOOGL, GOOG, AMZN, META, TSLA}`
- Current date must be opex week (need `is_opex_week(date)` helper — port from `xenon.analysis.gex`)

**Detection:** Port `detect_pinning(strikes, price, opex_week=True, min_gamma=1.0)` from xenon. Returns `{distance_pct, gamma, strike}` or `None`.

**Score:** `0.5 × (1 - distance_pct) + 0.5 × min(|gamma| / 10, 1.0)`.

**Evidence:** the full `pin` dict from `detect_pinning`.

### 3.5 `pcr_sentiment` (Context flag, zero weight)

**Reads:** existing `cards/pcr.py` per-ticker PCR.

**Bucketing:**
| PCR range | Label |
|---|---|
| > 1.5 | Extreme Fear |
| > 1.2 | Elevated Fear |
| < 0.5 | Complacent |
| else | no flag emitted |

**Suppressed when:** earnings within 14 days (PCR is noisy around earnings).

**Effect:** displayed as a colored badge on the candidate tile; **does not affect scoring or ranking**.

---

## 4. Gates

Pre-filters evaluated for every ticker. **Only `regime_gate` is a hard block** — when it fails, no candidate is emitted. `earnings_gate` and `liquidity_gate` are **advisory**: their pass/block status is recorded per-ticker per-run and shown on the candidate tile, but they do NOT suppress the candidate.

Reason for the asymmetry: `earnings_iv_crush` REQUIRES earnings within 14d, so a hard `earnings_gate` block would prevent EIC from ever firing. Xenon's `scan.py` confirms this — only `regime_gate` causes `return None`; the other two are advisory annotations.

| Gate | Pass condition | Block effect |
|---|---|---|
| `earnings_gate` | no earnings within 14 days | **advisory** — recorded only |
| `liquidity_gate` | aggregate `option_volume ≥ 1000` over recent flow alerts | **advisory** — recorded only |
| `regime_gate` | market regime ≠ R2 (risk-off) | **hard block** — candidate suppressed entirely |

**Regime gate mapping (proposed; final mapping resolved during implementation):**

Xenon uses an R0/R1/R2 trichotomy. Unusual-whales uses GOLD COMPASS five-tier posture (shipped in PR #40 — exact tier names: see `cards/matrix_state.py` or the recent gold A1 commits). Proposed starting mapping, **to be verified by reading the actual posture enum during implementation Task 1; update inline if names differ**:

| GOLD posture | xenon equivalent |
|---|---|
| `STABLE` / `EXPANSION` (tier 1-2) | R0 — pass |
| `CAUTIOUS` (tier 3) | R1 — pass |
| `DEFENSIVE` / `CRISIS` (tier 4-5) | R2 — block |

If the GOLD posture enum doesn't match these names, the implementation MUST update the mapping in `scanner/gates.py` and document it inline. Do not silently invent labels.

---

## 5. Scoring & ranking

```
RANKING_TIER_WEIGHTS    = { 1: 3.0, 2: 1.5 }
RAW_RANKING_EXCLUDE     = frozenset({"dark_pool_accumulation"})

raw_score           = Σ (hit.score × tier_weight) for hits where signal_type NOT IN RAW_RANKING_EXCLUDE
confluence_score    = Σ tier_weight for ALL hits (DP included)
final_score         = raw_score + confluence_score
is_type_f           = ≥ 2 distinct non-DP signal types

rank_order = (is_type_f desc, final_score desc, ticker asc)
```

**Worked example:**

AAPL has hits: `deep_conviction_flow` (tier 1, score 0.85) + `dark_pool_accumulation` (tier 2, score 0.40) + `earnings_iv_crush` (tier 1, score 0.72).

```
raw_score        = 0.85*3.0 + 0.72*3.0           = 4.71   (DP excluded from raw)
confluence_score = 3.0 + 1.5 + 3.0               = 7.5    (all hits)
final_score      = 4.71 + 7.5                    = 12.21
is_type_f        = True (DCF and EIC are 2 distinct non-DP types)
```

MSFT has hits: `deep_conviction_flow` (tier 1, score 0.70) only.

```
raw_score        = 0.70*3.0                      = 2.10
confluence_score = 3.0                           = 3.0
final_score      = 2.10 + 3.0                    = 5.10
is_type_f        = False
```

Ranking: AAPL (Type-F) first, MSFT second.

---

## 6. Persistence

New migration: `src/uw_scan/storage/migrations/036_scanner_signals.sql`.

```sql
-- 036_scanner_signals.sql — idempotent
-- Three tables: signal_hits (positive), signal_context_flags (colored badges),
-- signal_gates (audit of pass/block per ticker per run).

CREATE TABLE IF NOT EXISTS uw_scan.signal_hits (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  signal_type     TEXT NOT NULL,
  tier            SMALLINT NOT NULL CHECK (tier IN (1, 2)),
  score           NUMERIC(6,3) NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
  evidence        JSONB NOT NULL,
  freshness       TEXT NOT NULL CHECK (freshness IN ('live', 'stale', 'unavailable')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signal_hits_ticker_recent
  ON uw_scan.signal_hits (ticker, inserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_hits_run
  ON uw_scan.signal_hits (run_id);

CREATE TABLE IF NOT EXISTS uw_scan.signal_context_flags (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  layer           TEXT NOT NULL,
  label           TEXT NOT NULL,
  value           NUMERIC(10,4),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signal_context_flags_run
  ON uw_scan.signal_context_flags (run_id);

CREATE TABLE IF NOT EXISTS uw_scan.signal_gates (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  earnings        TEXT NOT NULL CHECK (earnings IN ('pass', 'block')),
  liquidity       TEXT NOT NULL CHECK (liquidity IN ('pass', 'block')),
  regime          TEXT NOT NULL CHECK (regime IN ('pass', 'block')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signal_gates_ticker_recent
  ON uw_scan.signal_gates (ticker, inserted_at DESC);

COMMENT ON TABLE uw_scan.signal_hits IS 'One row per (run, ticker, signal) emission. Append-only.';
COMMENT ON TABLE uw_scan.signal_context_flags IS 'Zero-weight badges (e.g., PCR sentiment).';
COMMENT ON TABLE uw_scan.signal_gates IS 'Gate audit — enables "why is this ticker missing" UX.';
```

**Why JSONB for `evidence`:** each detector's evidence shape is different (`{cluster_size, anchor_price}` for DP vs `{qualifying_alerts, top_strike}` for DCF). Typed columns would force a wide sparse table. JSONB lets each detector own its evidence shape; the frontend reads it as `Record<string, unknown>`.

**Why `freshness` per-hit:** xenon's `dark_pool_accumulation` returns `"stale"` because UW DP data lags real-time, while `deep_conviction_flow` returns `"live"`. This belongs at the hit level, not the run level.

**Why persist gate fails:** answers "why is AAPL not in the scanner today?" without making the user open dev tools. Storage cost is negligible (one short row per ticker per scan).

---

## 7. Module layout

### Backend (new)

```
src/uw_scan/
├── scanner/                              # NEW package
│   ├── __init__.py
│   ├── models.py                         # SignalHit, ContextFlag, ScanCandidate dataclasses
│   ├── gates.py                          # earnings_gate, liquidity_gate, regime_gate
│   ├── ranking.py                        # build_candidate, rank_candidates
│   ├── pipeline.py                       # run_detectors(repo, run_id, ticker) orchestrator
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── deep_conviction_flow.py
│   │   ├── dark_pool_accumulation.py
│   │   ├── earnings_iv_crush.py
│   │   └── gex_pinning.py
│   └── context/
│       ├── __init__.py
│       └── pcr_sentiment.py
├── storage/
│   ├── signals_repository.py             # NEW persistence module (NOT appended to repository.py)
│   └── migrations/036_scanner_signals.sql
├── sources/uw.py                         # EXTENDED: add fetch_flow_alerts() if not present;
│                                         #           add fetch_earnings_calendar()
├── api/routers/scanner.py                # NEW: GET /api/scanner
├── api/server.py                         # MODIFIED: include scanner router
└── worker/jobs/flow_data_refresh.py      # MODIFIED: call scanner.pipeline.run_detectors
                                          #           before finish_scan_run
```

### Frontend (new)

```
web/
├── app/scanner/
│   ├── page.tsx                          # MODIFIED — replaces stub; RSC, force-dynamic
│   └── loading.tsx                       # NEW — tile-stack skeleton
├── components/scanner/                   # NEW directory
│   ├── ScannerFilters.tsx                # "use client" — Type-F toggle, Tier-1-only toggle, sector chips
│   ├── CandidateTile.tsx                 # one ranked candidate
│   ├── SignalBadge.tsx                   # [DCF · tier 1 · $2.4M premium]
│   ├── ContextFlagBadge.tsx              # flag: Extreme Fear
│   ├── GatesIndicator.tsx                # gates: ✓ ✓ ✓
│   └── GatedList.tsx                     # "GATED (4 watchlist tickers excluded)" block
└── lib/types.ts                          # regenerated via npm run gen:types
```

### Tests

```
tests/unit/scanner/
├── test_deep_conviction_flow.py          # fixture-based: qualifying / non-qualifying alerts
├── test_dark_pool_accumulation.py        # cluster detection edge cases
├── test_earnings_iv_crush.py             # IV pctile thresholds + earnings presence
├── test_gex_pinning.py                   # mega-cap filter + opex week + distance/gamma scoring
├── test_pcr_sentiment.py                 # bucket boundaries
├── test_gates.py                         # earnings / liquidity / regime
├── test_ranking.py                       # Type-F precedence, tiebreaks, DP exclusion from raw
└── test_pipeline.py                      # full orchestration on synthetic ticker data

tests/integration/scanner/
├── test_signals_repository.py            # CRUD + idempotency + freshness window query
├── test_scanner_router.py                # GET /api/scanner shape, empty state, gated tickers
└── test_pipeline_e2e.py                  # full scan run → detectors fire → API returns ranked

web/tests/
├── scanner-page.test.ts                  # Vitest: page renders + tiles + filters
└── scanner-page.spec.ts                  # Playwright: smoke test
```

---

## 8. API contract

### `GET /api/scanner`

**Query params:**
- `tier_1_only`: `true | false` (default `false`) — when true, only show candidates that have at least one tier-1 signal hit (i.e., hide candidates whose only hits are tier-2 dark pool clusters)
- `type_f_only`: `true | false` (default `false`) — when true, only show Type-F candidates (≥ 2 distinct non-DP signal types)
- `sector`: optional sector filter (reuses watchlist sector groups)
- `freshness_hours`: optional override (default from `SCANNER_FRESHNESS_HOURS` env, default 6)

Tier semantics note: lower tier number = higher signal importance (xenon convention — tier 1 is the headline edge, tier 2 is confirmation-only). The boolean `tier_1_only` filter avoids the min/max-tier ambiguity that arises with numeric range params.

**Response (Pydantic v2 model in `api/models/scanner.py`):**

```python
class ScannerSignalHit(BaseModel):
    signal_type: Literal["deep_conviction_flow", "dark_pool_accumulation",
                          "earnings_iv_crush", "gex_pinning"]
    tier: Literal[1, 2]
    score: Decimal
    evidence: dict[str, Any]
    freshness: Literal["live", "stale", "unavailable"]

class ScannerContextFlag(BaseModel):
    layer: Literal["pcr_sentiment"]
    label: str
    value: Decimal | None

class ScannerGatesStatus(BaseModel):
    earnings: Literal["pass", "block"]    # advisory
    liquidity: Literal["pass", "block"]   # advisory
    regime: Literal["pass", "block"]      # candidate exists ⇒ regime is always "pass" here

class ScannerCandidate(BaseModel):
    ticker: str
    spot: Decimal | None
    is_type_f: bool
    raw_score: Decimal
    confluence_score: Decimal
    final_score: Decimal
    hits: list[ScannerSignalHit]
    context_flags: list[ScannerContextFlag]
    gates: ScannerGatesStatus            # advisory states for the candidate tile
    scanned_at: datetime

class ScannerGatedTicker(BaseModel):
    ticker: str
    reason: Literal["regime_R2", "stale_scan"]   # only regime is hard-block; stale_scan = no recent ok run
    scanned_at: datetime | None

class ScannerResponse(BaseModel):
    scanned_universe_size: int
    candidates_with_hits: int
    candidates: list[ScannerCandidate]   # already ranked
    gated: list[ScannerGatedTicker]
    generated_at: datetime
```

**Empty state:** when no watchlist tickers have recent scans, return `{candidates: [], gated: [], scanned_universe_size: N, candidates_with_hits: 0, generated_at: ...}` — frontend renders an "no recent scans" message.

---

## 9. UI specification

### Layout

```
SCANNER

[Type F only ☐]  [Tier 1 only ☐]   [sector chips from watchlist]

┌──────────────────────────────────────────────────────────────────┐
│ * AAPL  $185.20                                       score 5.20 │
│        [DCF · tier 1 · $2.4M premium · 38 DTE]                   │
│        [DP  · tier 2 · cluster of 5 @ $184.95]                   │
│        flag: Extreme Fear   gates: earnings ✓ liq ✓ regime ✓     │
│        scanned 2m ago                            Evaluate →      │
├──────────────────────────────────────────────────────────────────┤
│   MSFT  $412.10                                       score 4.10 │
│        [DCF · tier 1 · $890K premium · 21 DTE]                   │
│        gates: ✓ ✓ ✓                                              │
│        scanned 4m ago                            Evaluate →      │
└──────────────────────────────────────────────────────────────────┘

GATED (2 watchlist tickers excluded by regime gate)
    AMD      regime R2 (DEFENSIVE)
    INTC     regime R2 (CRISIS)
```

The GATED list **only contains regime-blocked tickers** (the sole hard-block gate). Earnings and liquidity advisory results appear on the candidate tiles themselves (e.g., `gates: earnings ✗ liq ✓ regime ✓` shows a candidate with earnings advisory failing but still listed). A ticker may simultaneously have an earnings advisory failure AND be a valid EIC candidate — that's the point of the design.

### Styling conventions (from `web/CLAUDE.md`)

- Argon dark theme, inline styles via `var(--…)` tokens
- Mono labels uppercase, 10px letter-spacing 1.5, `var(--text-muted)`
- Score values: 22px bold mono, `var(--text-primary)` (matches `Tile` pattern in `panels/VolMetricsCard.tsx`)
- Type-F marker: `*` prefix rendered in `var(--accent-warm)` to draw the eye
- Tile container: `var(--bg-panel)` + `1px solid var(--border-dim)` + 4px radius (matches `TickerCard`)
- No charts, no SVG; this is a text-and-data page

### Color encoding

- Score: monochrome `var(--text-primary)` (no green/red — score is good-direction always)
- Signal-type tags: `var(--accent-warm)` for tier 1, `var(--accent-bg)` for tier 2
- Context flags: `var(--negative)` for Extreme Fear / Elevated Fear, `var(--positive)` for Complacent, `var(--warning)` for in-between
- Gate ✓: `var(--positive)` for pass, `var(--negative)` for block (in GATED list only — blocked tickers never appear in the candidate list)

### Interaction

- Tile click target: the "Evaluate →" link; entire tile not clickable (avoid accidental navigation when scanning)
- Per-tile rescan button: reuse existing `<RescanButton ticker={ticker} initialJob={null} />` from `components/shared/RescanButton`
- Filter chips: client-side URL param updates (`?type_f_only=true&tier_1_only=true`), same pattern as watchlist `FilterBar`
- Page is `force-dynamic` — searchParams-driven, no Router Cache caching

---

## 10. Configuration

New env vars in `src/uw_scan/config.py`:

| Var | Default | Purpose |
|---|---|---|
| `SCANNER_FRESHNESS_HOURS` | `6` | Hits older than this are treated as stale; ticker drops to GATED with reason `stale_scan` |
| `SCANNER_DCF_MIN_PREMIUM_USD` | `500000` | DCF detector threshold (overridable for tuning) |
| `SCANNER_DCF_MIN_ASK_SIDE` | `0.80` | DCF ask-side threshold |
| `SCANNER_DP_MIN_PRINT_PREMIUM_USD` | `1000000` | DP detector per-print min |
| `SCANNER_DP_MIN_CLUSTER_SIZE` | `3` | DP detector cluster size threshold |
| `SCANNER_DP_PRICE_SPREAD_PCT` | `0.5` | DP detector price clustering tolerance |
| `SCANNER_EIC_MIN_IV_PCTL` | `75.0` | EIC detector IV percentile floor |
| `SCANNER_GEX_PIN_MIN_GAMMA` | `1.0` | GEX-pinning gamma threshold |
| `SCANNER_LIQUIDITY_MIN_OPTION_VOLUME` | `1000` | Liquidity gate threshold |
| `SCANNER_REGIME_BLOCK_POSTURES` | `DEFENSIVE,CRISIS` | Comma list of GOLD postures that block (mapped in `scanner/gates.py`) |

All env-var-overridable so the user can tune thresholds without code changes during early operation.

---

## 11. Out of scope (explicitly)

These items are flagged elsewhere in this conversation and are NOT covered by this spec:

- **Multi-day rolling dark pool aggregate / 3+ consecutive day sustained-direction detector.** That's the "Strategy 1 as the doc describes" path the user rejected during brainstorming. Could be added later as a new `dark_pool_sustained` detector alongside `dark_pool_accumulation`.
- **Intraday interpolation with LOW/MED/HIGH confidence.** Same rationale.
- **Market-wide "discover" mode.** Phase 4 work, separate spec.
- **News / earnings / FDA catalyst surfacing.** Phase 4 work; requires data-source decisions.
- **In-page deep-evaluate view.** Evaluate handoff is a link to `/stock/[ticker]/trade-plan` — the existing Trade Insights AI surface owns deep eval.
- **Removal of existing `scoring.py` Setup C/F.** Kept alongside this release; retirement is a follow-up spec.
- **"Scan all watchlist now" bulk-rescan button.** Per-row rescan is sufficient for V1.

---

## 12. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| GOLD COMPASS posture enum doesn't map cleanly to R0/R1/R2 | Medium | Implementation Task 1 reads the actual posture enum from `cards/matrix_state.py` and updates the gate mapping inline; spec assumes the proposed mapping is a starting point, not gospel |
| Earnings calendar data not in UW or out of date | Medium | Spec adds `fetch_earnings_calendar()` to `sources/uw.py`; if UW endpoint doesn't return clean dates, fall back to FMP earnings calendar per data-source priority (UW → FMP, never Yahoo) |
| `is_opex_week` helper port introduces opex calendar drift | Low | Port unit tests from xenon along with the helper; assert against known opex weeks for next 2 quarters |
| Per-ticker scan latency increases noticeably with detector overhead | Low | Detectors are pure functions on already-fetched data; expected overhead < 50ms per ticker. If observed, profile and consider running detectors as a separate post-scan job in a follow-up |
| Setup C/F badges on watchlist cards become confusing alongside scanner page | Medium | Document the duality in `web/components/watchlist/CLAUDE.md` during the change; plan a Setup C/F retirement spec for the next quarter |
| `signal_hits` table grows unboundedly | Low (over months) | Add a TTL cleanup job in a follow-up; not urgent for V1 (assume ~50 tickers × ~4 signals × 24 scans/day × 365 days ≈ 1.75M rows/year, well within Postgres comfort) |

---

## 13. Success criteria

The spec is implementation-complete when:

1. `/scanner` page renders a ranked tile-stack of watchlist candidates with at least 2 distinct detector types firing in production data within 24 hours of deployment
2. Clicking "Evaluate →" navigates to `/stock/[ticker]/trade-plan` and the page loads with the existing trade-plan tab
3. Gated watchlist tickers are visible in the GATED section with a human-readable reason
4. Per-row rescan button enqueues a job and refreshing the page shows the new hit
5. All four detectors have unit tests covering qualifying / non-qualifying inputs
6. `signal_hits` / `signal_context_flags` / `signal_gates` tables populate as expected (verified via integration test)
7. `npm run gen:types` produces a clean diff for the new `ScannerResponse` model
8. No regression in existing watchlist landing or stock detail pages

---

## 14. Open questions for implementation-plan phase

These do not block writing this spec, but the implementation plan must resolve them:

1. **Exact GOLD COMPASS posture enum names** — to be confirmed by reading `cards/matrix_state.py` at start of Task 1, with the regime-gate mapping updated inline if needed.
2. **UW earnings calendar endpoint exact path** — to be confirmed against `docs/uw-samples/unusual_whales_api.md`; if missing, fall back to FMP.
3. **Whether `fetch_flow_alerts()` already exists in `sources/uw.py`** — if not, add it as part of DCF detector wiring (single endpoint, pattern is well-established).
4. **`is_opex_week` helper** — port directly from `xenon/src/xenon/analysis/gex.py` to `cards/` or a new `scanner/calendars.py`.
5. **Whether the existing `RescanButton` works out-of-the-box on scanner tiles** — should be a drop-in; verify during UI implementation.

---

## 15. Implementation phasing (high-level — full breakdown belongs in plan)

Suggested sequence for the implementation plan to flesh out task-by-task:

1. Schema migration + `signals_repository.py` (zero behavior change)
2. Scanner package skeleton (`models.py`, `gates.py`, `ranking.py`, empty `pipeline.py`)
3. `deep_conviction_flow` detector + unit tests + flow_alerts fetcher (if missing)
4. `dark_pool_accumulation` detector + unit tests
5. Wire `pipeline.run_detectors` into `flow_data_refresh` worker job
6. `GET /api/scanner` router + response models + integration test
7. Scanner page UI (`page.tsx` + components) + Vitest + Playwright smoke test
8. `earnings_iv_crush` detector + earnings calendar fetcher + persistence
9. `gex_pinning` detector + `is_opex_week` helper port
10. `pcr_sentiment` context flag
11. Regime gate mapping to GOLD COMPASS posture (read enum, document mapping, write test)
12. Tuning + threshold env var wiring + final integration test pass

Steps 1-7 = minimum walking-skeleton (DCF + DP only). Steps 8-11 = feature parity with xenon. Step 12 = production-ready.

---

*End of spec.*
