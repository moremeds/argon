# Scanner Discovery Expansion + Markout-Ready Persistence — Design

**Date:** 2026-06-15
**Status:** Approved (brainstorming) — ready for implementation plan
**Author:** chenxi

## Problem

The `/scanner` page has two sections over two universes:

- **Watchlist** (`BULLISH/BEARISH/MIXED/NO DIRECTIONAL READ` cards) — the curated
  watchlist, scanned by `full_scan` with the full multi-signal engine
  (DCF + dark-pool accumulation + EIC + GEX → confluence / Type-F). This is the
  "good" engine.
- **DISCOVERED** — non-watchlist tickers surfaced from the live market-wide
  flow-alert feed. Today it is **DCF-only and ranked purely by premium dollar
  size**: `score = 0.5 + 0.5 · min(total_premium / 2_000_000, 1.0)`
  (`scanner/signals/deep_conviction_flow.py:111-112`, sorted in
  `scanner/discovery.py:109`). It is **ephemeral** — re-derived per request with a
  30s cache; only the audit run is stored, never the candidates.

Two concrete weaknesses:

1. **Discovery double-counts size.** The universe is already premium-gated, then
   ranked by premium again. radon's `Discover` (`scripts/discover.py`) was built
   to avoid exactly this — it ranks by *edge quality*, with premium as a filter
   only.
2. **Nothing is markout-ready.** Discovery persists no results; the watchlist
   persists per-signal rows but no candidate-grain entry spot. There is no way to
   later ask "did these signals actually lead price?" — unlike GRG/VCG, which have
   forward-return backtests.

## Goal

Expand the DISCOVERED section to radon's 5-factor edge-quality scoring (dark-pool
included), persist **all** scanner candidates (watchlist + discovery) in a
markout-ready shape, and capture entry spot so forward-return (markout) validation
can be built later.

## Scope & phases

- **Phase 1 (this spec):** expanded discovery scoring + the live dark-pool
  enrichment that feeds it + unified markout-ready persistence for both sections.
- **Phase 2 (later, separate spec):** markout / forward-return validation job +
  UI. This build only makes data markout-*ready* (entry spot + `scored_at`
  persisted); it does **not** compute forward returns.

**Out of scope (Phase 1):**

- Changing the watchlist detector scoring — it stays as-is (additive snapshot
  persistence only).
- EIC / GEX on discovery — they need deep per-ticker data (IV rank, by-strike GEX
  curve) we do not fetch for non-watchlist names. radon `Discover` is flow + DP
  only; we match that.
- A "promote to watchlist" button — deferred.

## Key decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| Discovery depth | **Full radon 5-factor edge-quality**, live dark-pool for **every** discovered candidate (bounded by a top-N cap), cache + concurrency cap + rate guard |
| Dark-pool storage | **Reuse `dark_pool_events`** warm table — one DP table app-wide; prior days served warm, only "today" refetched; history accrues; markout-ready |
| Cadence | **Scheduled every :00/:30 RTH + close** (~13 runs/day); page reads the latest persisted snapshot |
| Persistence shape | **Unified `scanner_candidate_snapshots`** table — one row per candidate emission (both sections), with `spot_at_signal` + `score_breakdown` jsonb |
| Compute path | **Approach A** — scheduled discovery service does the heavy compute; the API endpoint is a thin read of the latest snapshot |
| Earnings handling | **Unchanged** — keep dropping alerts with unknown earnings; keep excluding known earnings inside the window (`discovery.py:77-79`) |

## Architecture

```
worker/jobs/discovery_scan.py        (NEW scheduled job, Approach A)
  └─ fetch_market_flow_alerts()      (sources/uw.py:128)
  └─ group by ticker, drop watchlist + unknown-earnings (existing rules)
  └─ STAGE 1 (0 UW): flow-only edge-quality → rank → cap to top-N
  └─ STAGE 2 (live UW, bounded concurrency + rate guard):
        per top-N ticker:
          read warm dark_pool_events (prior days)
          fetch_darkpool_ticker() for today (sources/uw.py:452)
          insert_dark_pool_rows() (storage/options.py:651)  ← warm cache write
  └─ scanner/edge_quality.py         (NEW pure scoring: 5-factor 0-100)
  └─ persist scanner_candidate_snapshots (section='discovery')
  └─ scan_runs row, notes='discovery_scan'

worker/jobs/full_scan.py (run_detectors)  (MODIFIED, additive)
  └─ after build_candidate → insert scanner_candidate_snapshots (section='watchlist')

api/routers/scanner.py  GET /api/scanner/discover  (MODIFIED → thin read)
  └─ fetch_latest_discovery_snapshot(limit)  → enriched DiscoveryCandidate

web/components/scanner/DiscoveredCard.tsx  (MODIFIED)
  └─ render 5-factor breakdown + edge-quality score
```

### Component: `scanner/edge_quality.py` (new, pure)

Ports radon's 0–100 weighted score; **premium is a filter, never a score input**.

| Factor | Weight (knob) | Source |
|---|---|---|
| DP strength | 30 | mid-relative buy ratio (radon `analyze_darkpool_day`) |
| DP sustained | 20 | consecutive same-direction days |
| Confluence | 20 | options bias (call/put) aligns with DP direction |
| Vol/OI | 15 | avg vol/OI across the ticker's qualifying alerts |
| Sweeps | 15 | sweep count (0→0, 1→50, 2+→100) |

- Pure function, `Decimal` throughout, target < 500 lines.
- DP **direction/strength/sustained** is a small ported helper that reads
  `dark_pool_events` rows and classifies each print buy/sell by
  `price >= midpoint(nbbo_bid, nbbo_ask)`, then aggregates per day and counts
  sustained days. **This is new logic** — distinct from argon's existing
  `dark_pool_accumulation` detector (which clusters prints near spot and is
  direction-neutral). We need the directional version radon uses.
- `score_model = 'edge_quality_v1'`. Output includes a `score_breakdown` dict
  (per-factor contributions) for persistence + UI.

### Component: `worker/jobs/discovery_scan.py` (new scheduled job)

1. `fetch_market_flow_alerts(limit=scanner_discover_alerts_limit)`.
2. Group by ticker; drop watchlist names; drop unknown-earnings (keep dropped
   count); exclude known earnings inside the window — existing discovery rules.
3. **Stage 1 (no UW):** compute the flow-only sub-score (vol/OI + sweeps +
   direction + ask-side), rank, cap to **top-N** (`scanner_discover_dp_top_n`,
   default 50) for DP enrichment — bounds worst-case fetches. The post-filter set
   is usually < 50, so this approximates "all discovered" while capping the tail;
   **if it truncates, log the dropped count** (no silent caps).
4. **Stage 2 (live UW):** for each top-N ticker, read warm `dark_pool_events`
   prior days, `fetch_darkpool_ticker` for today, `insert_dark_pool_rows`. Run
   with **bounded concurrency** (`scanner_discover_dp_concurrency`, default 6) and
   a **rate guard** so a burst can't starve the watchlist UW budget. The exact
   concurrency mechanism (thread pool vs async semaphore) depends on the UW
   client's sync/async nature — resolved in the implementation plan.
5. Compute the full 5-factor score; derive `bias` + `direction` (long/short for
   the markout sign).
6. `spot_at_signal` = alert `underlying_price` (fallback: most recent DP print
   price).
7. Persist `scanner_candidate_snapshots` (section='discovery') + a `scan_runs`
   row with `notes='discovery_scan'` (distinguishable from `full_scan` per the
   scan_runs.notes convention).
8. Advisory-locked single-flight (like `full_scan`). Cadence via APScheduler
   cron, :00/:30 RTH + close.

### Component: schema — migration `072_scanner_candidate_snapshots.sql` (idempotent)

```sql
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.scanner_candidate_snapshots (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT,
  section         TEXT NOT NULL,            -- 'watchlist' | 'discovery'
  ticker          TEXT NOT NULL,
  scored_at       TIMESTAMPTZ NOT NULL,
  bias            TEXT,                     -- 'bullish'|'bearish'|'mixed'|'neutral'
  direction       TEXT,                     -- 'long'|'short'|NULL  (markout sign)
  score           NUMERIC(8,3),
  score_model     TEXT NOT NULL,            -- 'edge_quality_v1' | 'watchlist_tier_v1'
  score_breakdown JSONB,
  spot_at_signal  NUMERIC,
  is_type_f       BOOLEAN,                  -- watchlist multi-signal flag (NULL for discovery)
  evidence        JSONB,                    -- alert_count, vol_oi, sweeps, dp_direction, sustained, confluence, ...
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_scs_ticker_scored
  ON uw_scan.scanner_candidate_snapshots (ticker, scored_at DESC);
CREATE INDEX IF NOT EXISTS ix_scs_section_scored
  ON uw_scan.scanner_candidate_snapshots (section, scored_at DESC);
```

New storage mixin `storage/scanner_snapshots.py` (`_ScannerSnapshotsMixin`) per the
mixin pattern — **not** appended to `repository.py`; add to the assembler +
re-export the row dataclass from `rows.py`. Methods:
`insert_candidate_snapshots_bulk(...)`, `fetch_latest_discovery_snapshot(limit)`,
`fetch_latest_watchlist_snapshot(...)`.

### Component: API — `GET /api/scanner/discover` (thin read)

- Reads `fetch_latest_discovery_snapshot(limit)` — no inline compute. The inline
  `discover_from_alerts` path moves into the job.
- Enriched `DiscoveryCandidate`: adds `score`, `score_breakdown`, `dp_direction`,
  `dp_strength`, `dp_sustained_days`, `confluence`, `vol_oi`, `sweeps`, `spot`,
  `scored_at`. Keeps `alerts_pulled` / `earnings_unknown_dropped` from run metadata.
- Model edits follow the contract-identity rules (preserve exports / `__all__` /
  OpenAPI names); run `npm run gen:types` + regenerate the OpenAPI snapshot.

### Component: watchlist markout-readiness (`run_detectors`)

After `build_candidate`, insert one `scanner_candidate_snapshots` row
(section='watchlist', score_model='watchlist_tier_v1') with `spot_at_signal`
(already fetched via `_fetch_spot_for_ticker`), bias, final_score, breakdown
(raw/confluence/type_f), evidence. `signal_hits` stays the granular audit,
unchanged. Additive only.

### Component: UI — `web/components/scanner/DiscoveredCard.tsx`

Render the 5-factor breakdown: DP-direction badge (ACC/DIST), strength, sustained
days, confluence ✓, vol/OI, sweeps, and the edge-quality score; order by score
desc. Header → "DISCOVERED · N (edge-quality · DP-confirmed · scored {time})".
Keep the `hide_discovered` toggle.

## New config knobs (`config.py`)

| Knob | Default | Purpose |
|---|---|---|
| `scanner_edge_quality_weight_dp_strength` | 30 | DP strength weight |
| `scanner_edge_quality_weight_dp_sustained` | 20 | sustained-direction weight |
| `scanner_edge_quality_weight_confluence` | 20 | options↔DP confluence weight |
| `scanner_edge_quality_weight_vol_oi` | 15 | vol/OI weight |
| `scanner_edge_quality_weight_sweeps` | 15 | sweeps weight |
| `scanner_discover_dp_top_n` | 50 | max candidates DP-enriched per run |
| `scanner_discover_dp_concurrency` | 6 | bounded concurrency for live DP fetches |
| `scanner_discover_dp_lookback_days` | 3 | DP direction lookback (radon parity) |
| `scanner_discover_alerts_limit` | 200 | market-wide alerts pulled per run |
| `scanner_discover_scan_enabled` | true | discovery job kill switch |

Weights are validated to sum to 100 at load (mirrors radon's `WEIGHTS` assert).

## Error handling / robustness

- **DP fetch fails for a candidate** → skip the DP factors, still score on the
  flow factors (graceful degrade), tag `dp_status` in evidence. One bad ticker
  never fails the run.
- **Alerts-feed outage** → log `.exception`, write no snapshot; the page serves
  the previous snapshot.
- **Empty feed** → write a 0-candidate run so the page shows "none" cleanly.
- **Rate budget** → concurrency cap + rate guard; discovery must not starve the
  watchlist's own UW calls.
- All except-handlers log (`repr(exc)` / `.exception(...)`) per CI Guardrail 2.
- Discovery job advisory-locked (single-flight) like `full_scan`.

## Testing

- **Unit:** each edge-quality factor + composite, with an explicit assertion that
  premium is **not** in the score; DP direction/strength/sustained computation;
  earnings drop preserved.
- **Integration (pytest-postgresql):** `scanner_candidate_snapshots` insert/read;
  discovery job end-to-end with fake UW alerts + DP fixtures (asserts DP prints
  land in `dark_pool_events` and snapshots persist); API reads latest snapshot;
  degraded-DP path (DP fetch raises → flow-only score).
- **Web:** vitest for `DiscoveredCard` breakdown rendering; Playwright e2e that the
  scanner page shows edge-quality discovered cards. `npm run gen:types` + OpenAPI
  snapshot green.

## Phase 2 (later — explicitly deferred)

Markout / forward-return validation: a job that joins each snapshot to forward
OHLC at +1 / +5 / +20 sessions, computes the signed return by `direction`, stores
`markout_results` keyed on `(ticker, scored_at)`, plus a UI markout column +
aggregate hit-rate. Separate spec; this build only guarantees the inputs exist.

## Success criteria

1. DISCOVERED candidates are ranked by the 5-factor edge-quality score (premium
   provably absent from the formula), with DP direction/confluence shown per card.
2. Every discovery run persists candidate snapshots **and** the underlying DP
   prints into `dark_pool_events`; reruns serve prior days warm.
3. Watchlist candidates persist markout-ready snapshots (entry spot + scored_at).
4. The page loads from the latest snapshot with no inline DP fetching.
5. Discovery runs on the :00/:30 RTH + close schedule, single-flight,
   concurrency-capped, without starving watchlist UW calls.
6. All gates green: `uv run pytest`, web typecheck/test/lint/build, `gen:types`
   diff clean, OpenAPI snapshot updated, migration idempotent (re-run = no-op).
