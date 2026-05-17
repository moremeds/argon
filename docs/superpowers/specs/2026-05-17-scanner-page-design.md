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
PER-TICKER DEEP SCAN PIPELINE (existing, extended)
──────────────────────────────────────────────────
worker dequeues rescan job → run_single_stock(ticker, client, repo)
    (defined at src/uw_scan/pipeline.py:107 — the actual rescan entry point;
     used by both rescan_loop and full_scan, NOT flow_data_refresh which
     only refreshes flow data and lacks the IV/GEX/earnings inputs detectors need)
    → fetches all UW data into existing tables for this run_id
    → NEW final stage: scanner.pipeline.run_detectors(repo, run_id, ticker)
        → reads back this run's freshly-persisted data + last 5 days of
          dark_pool_events (rolling window) from the DB
        → evaluates ALL 3 gates and records status
            (earnings, liquidity, regime — see §4 for which block)
        → IF regime_gate == "block": write signal_gates row and stop
        → ELSE: run 4 signal detectors + pcr_sentiment context flag
        → writes results to uw_scan.signal_hits / signal_context_flags / signal_gates
        → also tags scan_runs.notes with "scanner_emit=1" so the read query can
          select scanner-producing runs (avoids the latest_run_id() ambiguity
          across job types — see §8)
    → finish_scan_run(run_id, status="ok")

SCANNER PAGE READ PATH (new)
─────────────────────────────────────────────
user opens /scanner
    → RSC fetches GET /api/scanner
        → for each watchlist ticker, find latest ok scan_run within
          last SCANNER_FRESHNESS_HOURS (default 3h — matches the existing
          bucketFreshness "stale" threshold in web/lib/freshness.ts)
          AND scan_runs.notes LIKE '%scanner_emit=1%'  (only scanner-producing runs)
        → pull associated signal_hits / context_flags / gates
        → join watchlist_cards for spot price (ScannerCandidate.spot)
        → build ScanCandidate per ticker (regime-pass only)
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

**Reads:** existing `uw_scan.flow_events` table populated by `sources/uw.fetch_flow_alerts()` (already wired — see `sources/uw.py:103` and `EndpointSlug.FLOW_ALERTS`). Per-run rows; the detector reads only this run's rows.

**Deviation from xenon (documented):** xenon's DCF qualifies per-alert using `ask_side_percent`, `multileg_percent`, `moneyness`, and `expiry_dte`/`dte` fields that exist on UW's raw payload but are **not stored on this repo's `FlowAlert` model**. Rather than expand the schema (deferred to a separate spec), the detector derives equivalents from fields that ARE persisted:

| xenon field | unusual-whales source | Derivation |
|---|---|---|
| `ask_side_percent` | `total_ask_side_prem`, `total_bid_side_prem` | `ask / (ask + bid)` (per-alert ratio of premium attributable to ask-side prints) |
| `multileg_percent < 0.10` | `has_multileg` boolean | EXCLUDE any alert where `has_multileg=true` (stricter than xenon's <10%; conservative) |
| `moneyness` | `strike`, `underlying_price` | `(strike - underlying_price) / underlying_price` |
| `dte` | `expiry`, scan date | `(expiry - scan_date).days` |
| earnings check | `next_earnings_date` (on the alert itself!) | `(next_earnings_date - scan_date).days <= 14` blocks |

**Per-alert qualification (revised for unusual-whales fields):**
| Field | Threshold |
|---|---|
| `volume > open_interest` | required (new positioning, not closing) — `FlowAlert.volume / .open_interest` |
| derived `ask_side_ratio` | ≥ 0.80 |
| `total_premium` | ≥ $500,000 |
| `has_multileg` | must be `False` |
| derived `\|moneyness\|` | ≤ 0.12 |
| derived `dte` | ≥ 6 |

**Detector-internal earnings check:** uses `FlowAlert.next_earnings_date` (already on the alert payload). If `next_earnings_date` is `None` (unknown), the alert is treated as having earnings imminent — **conservative block**, matching xenon's `_parse_next_earnings` behavior of returning `(None, True)`. This redundancy with the framework's advisory `earnings_gate` is intentional: DCF must never emit during the earnings window.

**Score:** `0.5 + 0.5 × min(total_premium / $2,000,000, 1.0)` aggregated over all qualifying alerts.

**Evidence stored:** `{qualifying_alerts: N, total_premium, top_strike, top_expiry, top_ask_side_ratio, top_dte}`.

### 3.2 `dark_pool_accumulation` (Tier 2, confirmation-only)

**Reads:** existing `uw_scan.dark_pool_events` table — but **across the last 5 calendar days** of `executed_at`, not just this `run_id`. Xenon achieves this by re-fetching 5 days from the UW API before detection (`xenon/analysis/ticker_data.py:321-336`). This spec achieves equivalence by querying the already-persisted DB:

```sql
SELECT * FROM uw_scan.dark_pool_events
WHERE ticker = %s
  AND executed_at >= NOW() - INTERVAL '5 days'
  AND COALESCE(canceled, false) = false
  AND premium IS NOT NULL
  AND price IS NOT NULL;
```

This uses persisted state without adding ingestion load, on the assumption that `dark_pool_events` is being refreshed often enough by existing scans of the same ticker. If a ticker hasn't been scanned recently, the 5-day window will simply be sparse — `signals_repository.fetch_dark_pool_window()` returns whatever exists.

**Cluster detection (unchanged from xenon):**
- Filter to prints with `premium ≥ $1,000,000`
- For each such print as anchor: find all prints within `0.5%` of anchor price
- If cluster size ≥ 3, signal fires

**Premium units:** the `dark_pool_events.premium` column is `NUMERIC` (no scale). Detector treats the value as USD directly — verified consistent with the UW API's `darkpool/{ticker}` response shape. If implementation discovers the stored values are in cents, adjust the thresholds during Task 4 (not a spec change).

**Score:** `min(1.0, total_cluster_premium / $10,000,000)`.

**Direction-neutral.** Evidence stores `{cluster_size, anchor_price, total_premium, window_start, window_end, direction_neutral: true}`. The signal asserts "size is being moved around this level over 5 days," not "they're buying."

**Confluence-only:** excluded from `raw_score` via `RAW_RANKING_EXCLUDE = {"dark_pool_accumulation"}`. Contributes to `confluence_score` only. Reason: a dark-pool cluster alone is too easy to confuse with routine OTC routing; it needs another signal to matter. **A ticker whose ONLY hit is `dark_pool_accumulation` produces NO candidate** (xenon's `build_candidate` returns `None` when `non_dp_hits` is empty — see §5).

**Freshness:** `"stale"` (UW dark pool data lags real-time; combined with the 5-day window the freshness label is appropriate).

### 3.3 `earnings_iv_crush` (Tier 1)

**Reads:** existing `iv_rank` field on this run's volatility data + earnings calendar.

**IV metric — deliberate deviation from xenon:** xenon uses `volatility_stats.iv_rank` (already on a 0-100 scale). Unusual-whales has the same shape — `iv_rank` field on multiple models (verified in `models.py` lines 89, 366, 688, 732, 879). This detector reads `iv_rank` directly (NOT `iv_percentile_30d` from `interpolated_iv_snapshots`, which is a different metric). The 0-100 scale convention is preserved (per `web/CLAUDE.md` scale gotcha note: `iv_rank` is 0-100, `percentile` is 0-1).

**Earnings calendar source:** `FlowAlert.next_earnings_date` is already present per-alert (verified in `models.py:68`). For tickers with no recent flow alerts (and thus no `next_earnings_date` signal), the spec needs a fallback: query UW's earnings endpoint. The exact UW endpoint path is in `docs/uw-samples/unusual_whales_api.md` (verify during implementation; if missing, fall back to FMP per data-source priority).

**Threshold:**
- `iv_rank ≥ 75`
- earnings within 14 days **must be present and known** (unknown → no fire, NOT a fire — matches DCF's conservative-block stance)

**Score:** `min(1.0, (iv_rank - 75) / 25 + 0.5)`.

**Evidence:** `{iv_rank, earnings_date, earnings_within_days}`.

### 3.4 `gex_pinning` (Tier 1, mega-caps + opex only)

**Reads:** existing `strike_gex_curve` (the per-run by-strike GEX surface for the nearest expiry persisted by `pipeline.run_single_stock`).

**GEX input — deliberate near-equivalence with xenon:** xenon reads `greek_exposure_by_strike` returning the latest-date by-strike surface across all near-term expiries. Unusual-whales' `strike_gex_curve` is the per-strike curve for one chosen expiry (typically the nearest). For this detector specifically, this is functionally equivalent because the detector only fires during **opex week for mega-caps** — and during opex week the nearest expiry IS the front-month opex expiry, which is exactly what xenon's by-strike surface would resolve to as the active pinning candidate. Document this equivalence in the detector docstring.

**Eligibility:**
- Ticker must be in `MEGA_CAPS = {SPY, QQQ, IWM, DIA, AAPL, MSFT, NVDA, GOOGL, GOOG, AMZN, META, TSLA}`
- Current date must be opex week (need `is_opex_week(date)` helper — port from `xenon/src/xenon/analysis/gex.py`; port the unit tests too, per §15 Task 9)

**Detection:** Port `detect_pinning(strikes, price, opex_week=True, min_gamma=1.0)` from xenon. Returns `{distance_pct, gamma, strike}` or `None`.

**Score:** `0.5 × max(0, 1 - distance_pct) + 0.5 × min(|gamma| / 10, 1.0)`.

The `max(0, ...)` clamp on the distance term mirrors xenon's `distance_score = max(0.0, 1.0 - pin["distance_pct"])` (`xenon/scanners/uw/signals/gex_pinning.py:42`) and prevents negative contribution if `distance_pct > 1.0`.

**Evidence:** the full `pin` dict from `detect_pinning` (`{strike, distance_pct, gamma}`).

### 3.5 `pcr_sentiment` (Context flag, zero weight)

**Reads:** this run's `flow_events` (the same per-run flow alerts DCF uses). **Does NOT use `cards/pcr.py`** — that file computes 30-day deltas on OI/volume PCR history, which is a different metric.

**Derivation (matches xenon exactly):** count-based PCR derived from current snapshot flow alerts:
```python
calls = sum(1 for a in alerts if str(a.type).lower() == "call")
puts  = sum(1 for a in alerts if str(a.type).lower() == "put")
pcr   = puts / calls if calls > 0 else None
```
This matches `xenon/analysis/ticker_data.py:424-432` exactly. The detector reads `FlowAlert.type` per-alert.

**Bucketing:**
| PCR range | Label |
|---|---|
| > 1.5 | Extreme Fear |
| > 1.2 | Elevated Fear |
| < 0.5 | Complacent |
| else | no flag emitted |

**Suppressed when:** the ticker has earnings within 14 days (PCR is noisy around earnings — uses the same `next_earnings_date` check as DCF). If `next_earnings_date` is unknown, flag is still emitted (the flag is informational, not a trade trigger).

**Effect:** displayed as a colored badge on the candidate tile; **does not affect scoring or ranking**.

---

## 4. Gates

Pre-filters evaluated for every ticker. **Only `regime_gate` is a hard block** — when it fails, no candidate is emitted. `earnings_gate` and `liquidity_gate` are **advisory**: their pass/block status is recorded per-ticker per-run and shown on the candidate tile, but they do NOT suppress the candidate.

Reason for the asymmetry: `earnings_iv_crush` REQUIRES earnings within 14d, so a hard `earnings_gate` block would prevent EIC from ever firing. Xenon's `scan.py` confirms this — only `regime_gate` causes `return None`; the other two are advisory annotations.

| Gate | Pass condition | Block effect |
|---|---|---|
| `earnings_gate` | `next_earnings_date` known AND > 14 days away | **advisory** — recorded only. Unknown earnings → `block` (conservative, matches xenon `_parse_next_earnings`) |
| `liquidity_gate` | sum of this run's `FlowAlert.volume` ≥ 1000 | **advisory** — recorded only |
| `regime_gate` | market regime is not risk-off (see mapping below) | **hard block** — candidate suppressed entirely |

**Regime gate — deliberate deviation from xenon, using unusual-whales' existing data:**

Xenon derives a **per-ticker** regime via `build_vrp_state(td)` + `classify_regime(td, vrp)` from term-structure inversion, VRP z-score, net GEX, and flip distance (`xenon/analysis/vrp.py:125-182`). Porting that wholesale would require expanding several persisted shapes and adding a per-ticker classifier — out of scope for this spec.

Instead this spec uses unusual-whales' existing GOLD COMPASS market-state model. The **actual** `PostureChipState` enum (verified at `src/uw_scan/models.py:1305`) is:

```python
PostureChipState = Literal["FAVORABLE", "NEUTRAL", "STRETCHED", "SUSPENDED", "DEGRADED"]
```

GOLD persists **three separate posture chips** per snapshot (`structural_posture_chip`, `cyclical_posture_chip`, `valuation_posture_chip` — `reports/gold_posture.py:516-518`). For the regime gate, this spec uses **`structural_posture_chip`** as the closest proxy to xenon's R0/R1/R2 (it represents the macro market-structure state, which is what xenon's regime classifier approximates).

**Mapping:**
| `structural_posture_chip` | regime gate result |
|---|---|
| `FAVORABLE` | pass |
| `NEUTRAL` | pass |
| `STRETCHED` | pass |
| `SUSPENDED` | **block** (risk-off equivalent) |
| `DEGRADED` | **block** (risk-off equivalent) |

The blocking chips (`SUSPENDED`, `DEGRADED`) are configurable via the `SCANNER_REGIME_BLOCK_CHIPS` env var (§10). The implementation should fetch `repo.fetch_gold_posture_latest()` — fail-open on missing posture data (treat absent posture as `NEUTRAL`/pass; do NOT block all detection just because GOLD hasn't run yet today).

This is a **market-wide** gate (same regime applies to every ticker in the same scan window) — a coarser cut than xenon's per-ticker classifier. Acceptable trade-off for V1; a per-ticker regime classifier can be added as a separate spec later.

---

## 5. Scoring & ranking

```
RANKING_TIER_WEIGHTS    = { 1: 3.0, 2: 1.5 }
RAW_RANKING_EXCLUDE     = frozenset({"dark_pool_accumulation"})

build_candidate(ticker, hits, context_flags):
    non_dp_hits = [h for h in hits if h.signal_type not in RAW_RANKING_EXCLUDE]
    if not non_dp_hits:
        return None                  # ← DP-only tickers produce NO candidate
                                     #    (matches xenon/scanners/uw/ranking.py:18-19)
    raw_score        = Σ (hit.score × tier_weight) for hits in non_dp_hits
    confluence_score = Σ tier_weight for ALL hits (DP included)
    final_score      = raw_score + confluence_score
    is_type_f        = ≥ 2 distinct non-DP signal types fired
    return ScanCandidate(...)

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

New migration: `src/uw_scan/storage/migrations/045_scanner_signals.sql` (latest existing migration is `044_gold_posture_extensions.sql`; 045 is the next free number — verified `ls migrations/`).

The schema uses composite primary keys keyed on `(run_id, ticker, ...)` matching the existing per-run table convention (e.g., `flow_event_id` UNIQUE on `(run_id, alert_id)`, `oi_per_strike_snapshots` PRIMARY KEY `(run_id, ticker, expiry, strike)`). This makes writes idempotent under retry via `ON CONFLICT DO UPDATE`.

```sql
-- 045_scanner_signals.sql — idempotent
SET search_path TO uw_scan, public;
-- Three tables: signal_hits (positive), signal_context_flags (colored badges),
-- signal_gates (audit of pass/block per ticker per run).

CREATE TABLE IF NOT EXISTS uw_scan.signal_hits (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  signal_type     TEXT NOT NULL,    -- 'deep_conviction_flow' | 'dark_pool_accumulation' | 'earnings_iv_crush' | 'gex_pinning'
  tier            SMALLINT NOT NULL CHECK (tier IN (1, 2)),
  score           NUMERIC(6,3) NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
  evidence        JSONB NOT NULL,
  freshness       TEXT NOT NULL CHECK (freshness IN ('live', 'stale', 'unavailable')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker, signal_type)
);
CREATE INDEX IF NOT EXISTS idx_signal_hits_ticker_signal_recent
  ON uw_scan.signal_hits (ticker, signal_type, inserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_hits_run
  ON uw_scan.signal_hits (run_id);

CREATE TABLE IF NOT EXISTS uw_scan.signal_context_flags (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  layer           TEXT NOT NULL,    -- 'pcr_sentiment'
  label           TEXT NOT NULL,
  value           NUMERIC(10,4),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker, layer)
);

CREATE TABLE IF NOT EXISTS uw_scan.signal_gates (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  earnings        TEXT NOT NULL CHECK (earnings IN ('pass', 'block')),
  liquidity       TEXT NOT NULL CHECK (liquidity IN ('pass', 'block')),
  regime          TEXT NOT NULL CHECK (regime IN ('pass', 'block')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_signal_gates_ticker_recent
  ON uw_scan.signal_gates (ticker, inserted_at DESC);

COMMENT ON TABLE uw_scan.signal_hits IS 'One row per (run, ticker, signal) emission. Composite PK; ON CONFLICT DO UPDATE on retry.';
COMMENT ON TABLE uw_scan.signal_context_flags IS 'Zero-weight badges (e.g., PCR sentiment).';
COMMENT ON TABLE uw_scan.signal_gates IS 'Gate audit — enables "why is this ticker missing" UX.';
```

**Writer pattern:** all three tables use `INSERT ... ON CONFLICT (PRIMARY KEY columns) DO UPDATE SET ...` so worker retries are idempotent and never produce duplicate rows that would inflate `raw_score` / `confluence_score`.

**Why FK column is `run_id` not `id`:** verified — `scan_runs.run_id` is the BIGSERIAL PRIMARY KEY (`migrations/001_s1_core_tables.sql:12`). Every other per-run FK in this schema uses `REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE` (e.g., lines 28, 61, 158, 178, 213, 248).

**Why JSONB for `evidence`:** each detector's evidence shape is different (`{cluster_size, anchor_price, window_start}` for DP vs `{qualifying_alerts, top_strike, top_ask_side_ratio}` for DCF). Typed columns would force a wide sparse table. JSONB lets each detector own its evidence shape; the frontend reads it as `Record<string, unknown>`.

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
│   ├── calendars.py                      # is_opex_week(date) — port from xenon/analysis/gex.py
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
│   ├── signals_repository.py             # NEW standalone module (NOT a Repository mixin)
│   │                                     # following the provider_usage.py precedent for
│   │                                     # write-time persistence modules. Class: SignalsRepository
│   │                                     # taking a psycopg connection. Does NOT extend Repository
│   │                                     # to avoid pulling in the 5,000+-line class. Read queries
│   │                                     # consumed by the API also live here.
│   └── migrations/045_scanner_signals.sql
├── sources/uw.py                         # EXTENDED: fetch_flow_alerts() already exists (line 103);
│                                         #           add fetch_earnings_by_ticker() ONLY if needed
│                                         #           as fallback when FlowAlert.next_earnings_date
│                                         #           is None for tickers with no recent alerts
├── api/routers/scanner.py                # NEW: GET /api/scanner
├── api/models/scanner.py                 # NEW: ScannerResponse + sub-models (per §8)
├── api/server.py                         # MODIFIED: include scanner router (after gold router)
└── pipeline.py                           # MODIFIED: run_single_stock() — call
                                          # scanner.pipeline.run_detectors(repo, run_id, ticker)
                                          # as the final stage before finish_scan_run.
                                          # NOT flow_data_refresh — that job doesn't fetch
                                          # the IV/GEX/earnings inputs detectors need.
```

**Note on the standalone vs mixin choice:** the storage CLAUDE.md prescribes the mixin pattern for new `Repository` domains (`_<Domain>Mixin` composed in). This spec opts instead for the **standalone module pattern** modeled on `provider_usage.py` (which the storage CLAUDE.md calls out as "Not part of `Repository`"). Rationale: the scanner writes from a single hook point (`run_single_stock`'s final stage), it doesn't need to be composed with the rest of `Repository`, and keeping it standalone avoids importing 5,000+ lines of unrelated MRO. If consumers later need scanner queries from inside other Repository methods, promotion to a mixin is a mechanical refactor.

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
- `freshness_hours`: optional override (default from `SCANNER_FRESHNESS_HOURS` env, default `3` — matches the existing `bucketFreshness` "stale" threshold in `web/lib/freshness.ts`)

Tier semantics note: lower tier number = higher signal importance (xenon convention — tier 1 is the headline edge, tier 2 is confirmation-only). The boolean `tier_1_only` filter avoids the min/max-tier ambiguity that arises with numeric range params.

**Query implementation:** select the latest `ok` `scan_runs` row per watchlist ticker within the freshness window, **filtered to scanner-producing runs** via `notes LIKE '%scanner_emit=1%'` (avoids selecting `flow_data_refresh` / `cockpit_daily_snapshot` runs that don't emit scanner rows — see §2). Then join `signal_hits` / `signal_context_flags` / `signal_gates` keyed by `(run_id, ticker)`, plus `watchlist_cards` for `spot`.

**Source of `ScannerCandidate.spot`:** the existing `watchlist_cards.spot` column (already populated per ticker by the watchlist refresh path). The scanner endpoint joins on `watchlist_cards` to compose the response. The field is not part of xenon's `ScanCandidate` model — it's an unusual-whales-specific addition to render price on the tile without forcing the frontend to do a second fetch.

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
- Per-tile rescan button: reuse existing `<RescanButton ticker={ticker} initialJob={null} />` from `components/shared/RescanButton` (verified interface: `ticker: string; initialJob?: QueueStatus | null`)
- Filter chips: client-side URL param updates (`?type_f_only=true&tier_1_only=true`), same pattern as watchlist `FilterBar`
- Page is `force-dynamic` — searchParams-driven, no Router Cache caching
- Tile freshness label: rendered via existing `bucketFreshness(scanned_at)` from `web/lib/freshness.ts` (returns `'fresh' | 'stale' | 'dead'`). Per-tile dot color matches the watchlist `TickerCard` convention (`var(--positive)` / `var(--warning)` / `var(--negative)`)

### Per-signal freshness display (V1: deferred)

The API returns `freshness: 'live' | 'stale' | 'unavailable'` per `ScannerSignalHit` because `dark_pool_accumulation` is inherently stale data (UW dark-pool API lags) while the others are live. V1 UI does NOT render per-signal freshness on the badges — they all use the same visual treatment. A V2 enhancement may apply reduced opacity to `stale` signal badges. The field is kept in the response so this enhancement requires UI-only work.

---

## 10. Configuration

New env vars in `src/uw_scan/config.py`:

| Var | Default | Purpose |
|---|---|---|
| `SCANNER_FRESHNESS_HOURS` | `3` | Hits older than this are treated as stale; ticker drops to GATED with reason `stale_scan`. Matches `bucketFreshness` "stale" threshold (180min) in `web/lib/freshness.ts` so the API window and UI freshness label agree |
| `SCANNER_DP_LOOKBACK_DAYS` | `5` | Number of calendar days of `dark_pool_events` to read for cluster detection (xenon equivalent) |
| `SCANNER_DCF_MIN_PREMIUM_USD` | `500000` | DCF detector per-alert premium threshold |
| `SCANNER_DCF_MIN_ASK_SIDE` | `0.80` | DCF ask-side ratio threshold (derived from `total_ask_side_prem / (ask + bid)`) |
| `SCANNER_DCF_MAX_MONEYNESS` | `0.12` | DCF |moneyness| threshold |
| `SCANNER_DCF_MIN_DTE` | `6` | DCF DTE floor |
| `SCANNER_DP_MIN_PRINT_PREMIUM_USD` | `1000000` | DP detector per-print premium min |
| `SCANNER_DP_MIN_CLUSTER_SIZE` | `3` | DP detector cluster-size threshold |
| `SCANNER_DP_PRICE_SPREAD_PCT` | `0.5` | DP detector price-clustering tolerance (percent of anchor price) |
| `SCANNER_EIC_MIN_IV_RANK` | `75.0` | EIC detector `iv_rank` floor (0-100 scale) |
| `SCANNER_GEX_PIN_MIN_GAMMA` | `1.0` | GEX-pinning gamma threshold |
| `SCANNER_LIQUIDITY_MIN_OPTION_VOLUME` | `1000` | Liquidity gate threshold (sum of `FlowAlert.volume` in the run) |
| `SCANNER_REGIME_BLOCK_CHIPS` | `SUSPENDED,DEGRADED` | Comma list of `structural_posture_chip` values that block (mapped in `scanner/gates.py`); valid values are `FAVORABLE,NEUTRAL,STRETCHED,SUSPENDED,DEGRADED` per `models.py:1305` |
| `SCANNER_EARNINGS_WINDOW_DAYS` | `14` | DCF earnings-block window and EIC earnings-required window |

All env-var-overridable so the user can tune thresholds without code changes during early operation.

---

## 11. Out of scope (explicitly)

These items are flagged elsewhere in this conversation and are NOT covered by this spec:

- **Multi-day "3+ consecutive days same direction" sustained-DP detector.** Spec ports xenon's single-snapshot 5-day cluster detection (direction-neutral). The "sustained direction" version from the user's original Strategy 1 doc is a future detector that could be added alongside.
- **Intraday interpolation with LOW/MED/HIGH confidence.** Same rationale.
- **Market-wide "discover" mode.** Phase 4 work, separate spec.
- **News / FDA catalyst surfacing.** Phase 4 work; requires data-source decisions.
- **In-page deep-evaluate view.** Evaluate handoff is a link to `/stock/[ticker]/trade-plan` — the existing Trade Insights AI surface owns deep eval.
- **Removal of existing `scoring.py` Setup C/F.** Kept in parallel for this release. Consumed by `pipeline.py:233/454/459` legacy full-scan path — this spec does NOT touch `pipeline.py`'s legacy Setup C/F call sites. Retirement is a follow-up spec.
- **"Scan all watchlist now" bulk-rescan button.** Per-row rescan is sufficient for V1.
- **Per-ticker regime classifier port from xenon.** Spec uses GOLD COMPASS's market-wide `structural_posture_chip` as a coarser proxy. Porting xenon's per-ticker `classify_regime` (term-structure / VRP-z / GEX-flip composite) is a separate future spec.
- **Expanding `FlowAlert` schema for per-alert percentage fields** (`ask_side_percent`, `multileg_percent`). Spec derives equivalents from persisted fields instead. If the derivation proves insufficient in practice, schema expansion is a follow-up.
- **Per-signal freshness display in UI.** API returns it; V1 UI doesn't render it (see §9).

---

## 12. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Derived `ask_side_ratio` doesn't match xenon's per-alert `ask_side_percent` closely enough; DCF surfaces too many false positives or misses | Medium | Tune `SCANNER_DCF_MIN_ASK_SIDE` against backtest. If derivation proves insufficient, expand `FlowAlert` schema in a follow-up spec to capture UW's raw `ask_side_percent` field |
| Market-wide regime gate is too coarse; legitimate ticker signals get suppressed when GOLD posture is `DEGRADED` for unrelated macro reasons | Medium | The blocking chips are env-var-overridable. Default `SUSPENDED,DEGRADED` can be widened to `DEGRADED`-only or disabled entirely during tuning. Per-ticker regime classifier is a future spec |
| `dark_pool_events` 5-day rolling window is sparse for thinly-traded tickers | Medium | Spec accepts sparse windows — detector returns `None` if cluster threshold isn't met. Documented behavior, not a bug |
| `FlowAlert.next_earnings_date` is missing for tickers with no recent alerts | High | Detector treats unknown as conservative-block (matches xenon). If false-suppression rate is high, implement fallback to `sources/uw.fetch_earnings_by_ticker()` |
| GOLD posture not yet computed at scan time (early in the trading day) | Medium | `regime_gate` fails open: missing posture → treat as `NEUTRAL` (pass). Documented in §4 |
| `is_opex_week` helper port introduces opex calendar drift | Low | Port unit tests from xenon along with the helper; assert against known opex weeks for next 2 quarters |
| Per-ticker scan latency increases noticeably with detector overhead | Low | Detectors are pure functions on already-fetched data; expected overhead < 50ms per ticker. If observed, profile and consider running detectors as a separate post-scan job in a follow-up |
| Setup C/F badges on watchlist cards become confusing alongside scanner page | Medium | Document the duality in `web/components/watchlist/CLAUDE.md` during the change; plan a Setup C/F retirement spec for the next quarter |
| `signal_hits` table grows unboundedly | Low (over months) | Composite PK on `(run_id, ticker, signal_type)` means at most ~50 × 4 rows per run; pruning by `run_id` is straightforward when `scan_runs` is cleaned. Add a TTL cleanup job in a follow-up |
| `dark_pool_events.premium` units mismatch (stored as cents instead of dollars) | Low | Detector reads raw `NUMERIC` value; if implementation discovers cents-scale, adjust `SCANNER_DP_MIN_PRINT_PREMIUM_USD` (env override) without code change |

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

1. **UW earnings calendar endpoint exact path** — `FlowAlert.next_earnings_date` covers most cases, but the fallback `sources/uw.fetch_earnings_by_ticker()` needs the right endpoint. Verify against `docs/uw-samples/unusual_whales_api.md`; if missing, fall back to FMP.
2. **`dark_pool_events.premium` units (dollars vs cents)** — assumed dollars to match xenon's $1M/$10M thresholds. Verify against a sample row during Task 4. If cents, override via `SCANNER_DP_MIN_PRINT_PREMIUM_USD=100000000` env var (no code change).
3. **`is_opex_week` helper signature** — port directly from `xenon/src/xenon/analysis/gex.py` to new `scanner/calendars.py`. Verify import path during Task 9.
4. **`watchlist_cards` join shape for spot price** — confirm the column is named `spot` and is `Decimal | None`; spec assumes `watchlist_cards` schema from `repository.py:3499-3540` (verify during Task 6).
5. **GOLD posture chip availability at scan time** — if `repo.fetch_gold_posture_latest()` returns no row (e.g., GOLD warmup hasn't run yet), regime_gate fails open per §4. Verify behavior during integration test Task 6.

**Resolved by tribunal review (no longer open):**
- ~~`fetch_flow_alerts()` existence~~ — verified present at `sources/uw.py:103` with `EndpointSlug.FLOW_ALERTS`
- ~~GOLD posture enum names~~ — verified at `models.py:1305`: `Literal["FAVORABLE","NEUTRAL","STRETCHED","SUSPENDED","DEGRADED"]`

---

## 15. Implementation phasing (high-level — full breakdown belongs in plan)

Suggested sequence for the implementation plan to flesh out task-by-task:

1. **Schema migration `045_scanner_signals.sql` + `signals_repository.py`** (zero behavior change). Verify `dark_pool_events.premium` units against a sample row during this task.
2. **Scanner package skeleton** (`models.py`, `gates.py` with regime-gate using `repo.fetch_gold_posture_latest()`, `ranking.py` with `build_candidate` returning `None` on DP-only, empty `pipeline.py`).
3. **`deep_conviction_flow` detector** + unit tests on derived `ask_side_ratio`, `moneyness`, `dte`, `next_earnings_date` paths (no new UW fetcher — `fetch_flow_alerts` already exists).
4. **`dark_pool_accumulation` detector** with 5-day DB read via `signals_repository.fetch_dark_pool_window()` + unit tests on cluster detection edge cases.
5. **Wire `scanner.pipeline.run_detectors` into `pipeline.run_single_stock`** as the final stage before `finish_scan_run`. Tag `scan_runs.notes` with `scanner_emit=1` so the read query can filter. NOT `flow_data_refresh` — that job doesn't fetch the required inputs.
6. **`GET /api/scanner` router** + response models in `api/models/scanner.py` + integration test (uses `pytest-postgresql`). Joins `signal_hits` + `signal_context_flags` + `signal_gates` + `watchlist_cards` for spot.
7. **Scanner page UI** (`page.tsx` + components) + Vitest + Playwright smoke test. Replaces the stub.
8. **`earnings_iv_crush` detector** using `iv_rank` field (not `iv_percentile_30d`). Add `sources/uw.fetch_earnings_by_ticker()` only if `next_earnings_date` proves insufficient on test data.
9. **`gex_pinning` detector** + port `is_opex_week` from `xenon/src/xenon/analysis/gex.py` to new `scanner/calendars.py` (with the xenon unit tests).
10. **`pcr_sentiment` context flag** using count-based PCR from this run's `FlowAlert` rows.
11. **End-to-end tuning** — verify GOLD posture mapping behaves as expected, tune env-var thresholds against real watchlist data for a few days, document any threshold adjustments inline.

Steps 1-7 = minimum walking-skeleton (DCF + DP only, plus regime gate). Steps 8-10 = feature parity with xenon. Step 11 = production-ready.

---

*End of spec.*
